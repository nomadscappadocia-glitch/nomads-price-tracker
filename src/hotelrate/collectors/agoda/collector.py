from __future__ import annotations

from decimal import Decimal

from playwright.async_api import async_playwright

from hotelrate.collectors.base import BaseCollector
from hotelrate.schemas import Platform, RawRateOffer, SearchRequest


class AgodaCollector(BaseCollector):
    platform = Platform.AGODA
    RESPONSE_PATTERNS = (
        "agoda.com",
        "api",
        "room",
        "offer",
        "price",
        "availability",
    )
    DROPPED_QUERY_KEYS = (
        "searchrequestid",
        "cid",
        "tag",
        "finalPriceView",
        "utm_source",
        "utm_medium",
        "utm_campaign",
    )

    async def fetch_rates(self, request: SearchRequest) -> list[RawRateOffer]:
        if self.settings.demo_mode:
            return [self.build_demo_offer(request, low=70, high=280)]
        return await self._fetch_live_rates(request)

    async def _fetch_live_rates(self, request: SearchRequest) -> list[RawRateOffer]:
        url = self._build_search_url(request)
        async with async_playwright() as pw:
            browser, context = await self.open_playwright_context(pw)
            page = await context.new_page()
            payloads = await self.capture_json_payloads(
                page=page,
                url=url,
                response_patterns=self.RESPONSE_PATTERNS,
                settle_ms=3000,
                after_load=self._after_load_interactions,
            )
            
            # Debug: save raw API responses if enabled
            if getattr(self.settings, "agoda_debug_save_json", False) and payloads:
                try:
                    from pathlib import Path
                    import json
                    import time
                    reports_dir = Path("reports")
                    reports_dir.mkdir(parents=True, exist_ok=True)
                    path = reports_dir / f"agoda_debug_{int(time.time()*1000)}.json"
                    path.write_text(json.dumps(payloads, indent=2, default=str), encoding="utf-8")
                    self.logger.info("agoda debug: saved %d payloads to %s", len(payloads), path)
                except Exception as e:
                    self.logger.debug("agoda debug save failed: %s", e)
            
            offers = self._parse_structured_offers(request=request, payloads=payloads)
            if not offers:
                offers = await self.parse_ld_json_fallback(page=page, request=request, max_offers=10)
            if not offers:
                offers = self._parse_below_fold_payloads(request=request, payloads=payloads)
            if not offers:
                offers = await self.parse_text_price_fallback(page=page, request=request, max_offers=6)

            # Parse rendered HTML for dynamic prices (e.g., data-fpc-value="225")
            html_offers = await self._parse_html_prices(page=page, request=request)
            if html_offers:
                # Merge with existing offers
                seen = {(o.room_name.strip().lower(), f"{o.final_price:.2f}") for o in offers}
                for o in html_offers:
                    key = (o.room_name.strip().lower(), f"{o.final_price:.2f}")
                    if key not in seen:
                        seen.add(key)
                        offers.append(o)

            self.logger.info(
                "agoda crawl url=%s payloads=%d offers=%d",
                url,
                len(payloads),
                len(offers),
            )
            await self.close_playwright_context(browser=browser, context=context)
        return offers

    def _build_search_url(self, request: SearchRequest) -> str:
        query = {
            "adults": request.adults,
            "children": request.children,
            "rooms": 1,
            "checkIn": request.checkin.isoformat(),
            "los": (request.checkout - request.checkin).days,
            "currencyCode": request.currency,
            "finalPriceView": 1,
        }

        if request.platform_url:
            cleaned = self.remove_url_query_keys(request.platform_url, self.DROPPED_QUERY_KEYS)
            return self.merge_url_query(cleaned, query)

        path = request.platform_hotel_id.strip("/")
        if "/hotel/" in path or path.endswith(".html"):
            base_url = f"https://www.agoda.com/{path}"
        else:
            base_url = f"https://www.agoda.com/{path}/hotel.html"

        return self.merge_url_query(base_url, query)

    def _parse_structured_offers(
        self,
        *,
        request: SearchRequest,
        payloads: list[dict],
    ) -> list[RawRateOffer]:
        room_grid_offers = self._parse_room_grid_payloads(request=request, payloads=payloads)
        if room_grid_offers:
            return room_grid_offers

        below_fold_offers = self._parse_below_fold_payloads(request=request, payloads=payloads)
        if below_fold_offers:
            return below_fold_offers

        return self.parse_payloads_to_offers(
            request=request,
            payloads=payloads,
            room_keys=("roomName", "masterRoomTypeName", "masterRoomName", "roomTypeName"),
            final_price_keys=("finalPrice", "inclusivePrice", "totalPrice"),
            price_keys=("displayPrice", "basePrice", "exclusivePrice", "price"),
            tax_keys=("taxAndServiceFee", "taxesAndFees", "tax"),
            meal_keys=("mealPlanName", "mealPlan", "boardType"),
            cancellation_keys=("cancellationPolicyText", "cancellationPolicy"),
            currency_keys=("currency", "currencyCode"),
            max_offers=25,
        )

    def _parse_room_grid_payloads(
        self,
        *,
        request: SearchRequest,
        payloads: list[dict],
    ) -> list[RawRateOffer]:
        offers: list[RawRateOffer] = []
        for payload in payloads:
            if "/api/v1/property/room-grid" not in str(payload.get("url", "")):
                continue
            data = payload.get("data")
            if not isinstance(data, dict):
                continue
            rooms = data.get("rooms")
            if not isinstance(rooms, list):
                continue

            for room in rooms:
                if not isinstance(room, dict):
                    continue
                room_name = (
                    str(room.get("masterRoomTypeName", "")).strip()
                    or str(room.get("roomName", "")).strip()
                    or str(room.get("name", "")).strip()
                )
                if not room_name:
                    continue

                final_price = self._extract_decimal_deep(room, ("finalPrice", "inclusivePrice", "totalPrice"), depth=4)
                base_price = self._extract_decimal_deep(room, ("displayPrice", "exclusivePrice", "basePrice"), depth=4)
                tax_fee = self._extract_decimal_deep(room, ("taxesAndFeesAmount", "taxAndServiceFee", "tax", "taxesAndFees"), depth=4) or Decimal("0")

                # Extract cancellation policy
                cancellation_policy = None
                raw_cancel = room.get("cancellationPolicy") or room.get("cancellationType") or room.get("cancellation")
                if raw_cancel:
                    cancellation_policy = str(raw_cancel)[:255]

                if final_price is None and base_price is None:
                    continue
                if final_price is None and base_price is not None:
                    final_price = base_price + tax_fee
                if base_price is None and final_price is not None:
                    base_price = max(final_price - tax_fee, Decimal("0"))
                if final_price is None or base_price is None:
                    continue
                if final_price <= Decimal("0"):
                    continue

                currency = str(room.get("currencyCode") or room.get("currency") or request.currency).upper()
                offers.append(
                    RawRateOffer(
                        platform=self.platform,
                        platform_hotel_id=request.platform_hotel_id,
                        room_name=room_name[:255],
                        meal_plan=None,
                        cancellation_policy=cancellation_policy,
                        currency=currency,
                        base_price=base_price.quantize(Decimal("0.01")),
                        tax_fee=tax_fee.quantize(Decimal("0.01")),
                        final_price=final_price.quantize(Decimal("0.01")),
                        checkin=request.checkin,
                        checkout=request.checkout,
                        adults=request.adults,
                        children=request.children,
                        source_url=str(payload.get("url", "")) or request.platform_url,
                        raw_payload={"mode": "room_grid"},
                    )
                )
                if len(offers) >= 25:
                    return offers
        return offers

    def _parse_below_fold_payloads(
        self,
        *,
        request: SearchRequest,
        payloads: list[dict],
    ) -> list[RawRateOffer]:
        offers: list[RawRateOffer] = []
        for payload in payloads:
            url = str(payload.get("url", ""))
            if "BelowFoldParams/GetSecondaryData" not in url:
                continue
            data = payload.get("data")
            if not isinstance(data, dict):
                continue

            room_grid = data.get("roomGridData")
            if isinstance(room_grid, dict):
                master_rooms = room_grid.get("masterRooms")
                if isinstance(master_rooms, list):
                    for room in master_rooms:
                        if not isinstance(room, dict):
                            continue
                        room_name = (
                            str(room.get("masterRoomTypeName", "")).strip()
                            or str(room.get("roomName", "")).strip()
                            or str(room.get("name", "")).strip()
                        )
                        if not room_name:
                            continue

                        final_price = self._extract_decimal_deep(
                            room,
                            ("finalPrice", "inclusivePrice", "totalPrice", "displayPrice", "price"),
                            depth=5,
                        )
                        if final_price is None or final_price <= Decimal("0"):
                            continue

                        # Extract tax fee from API response
                        tax_fee = self._extract_decimal_deep(
                            room,
                            ("taxesAndFeesAmount", "taxAndServiceFee", "tax"),
                            depth=3,
                        ) or Decimal("0")

                        # Extract cancellation policy from API response
                        cancellation_policy = None
                        raw_cancel = room.get("cancellationPolicy") or room.get("cancellationType") or room.get("cancellation")
                        if raw_cancel:
                            cancellation_policy = str(raw_cancel)[:255]

                        currency = str(
                            room.get("currencyCode")
                            or room.get("currency")
                            or data.get("hotelSearchCriteria", {}).get("currencyCode")
                            or request.currency
                        ).upper()
                        amount = final_price.quantize(Decimal("0.01"))
                        offers.append(
                            RawRateOffer(
                                platform=self.platform,
                                platform_hotel_id=request.platform_hotel_id,
                                room_name=room_name[:255],
                                meal_plan=None,
                                cancellation_policy=cancellation_policy,
                                currency=currency,
                                base_price=amount,
                                tax_fee=tax_fee.quantize(Decimal("0.01")),
                                final_price=amount,
                                checkin=request.checkin,
                                checkout=request.checkout,
                                adults=request.adults,
                                children=request.children,
                                source_url=url,
                                raw_payload={"mode": "below_fold_room_grid"},
                            )
                        )
                        if len(offers) >= 20:
                            return offers

            cheapest = self._to_decimal(data.get("inquiryProperty", {}).get("cheapestPrice"))
            if cheapest is None or cheapest <= Decimal("0"):
                sticky = data.get("stickyFooter", {}).get("discount", {}).get("cheapestPriceWithCurrency")
                cheapest = self._to_decimal(sticky)
            if cheapest is None or cheapest <= Decimal("0"):
                continue

            hotel_name = str(data.get("hotelInfo", {}).get("name", "")).strip() or "Agoda offer"
            currency = str(data.get("hotelSearchCriteria", {}).get("currencyCode") or request.currency).upper()
            amount = cheapest.quantize(Decimal("0.01"))
            offers.append(
                RawRateOffer(
                    platform=self.platform,
                    platform_hotel_id=request.platform_hotel_id,
                    room_name=hotel_name[:255],
                    meal_plan=None,
                    cancellation_policy=None,
                    currency=currency,
                    base_price=amount,
                    tax_fee=Decimal("0"),
                    final_price=amount,
                    checkin=request.checkin,
                    checkout=request.checkout,
                    adults=request.adults,
                    children=request.children,
                    source_url=url,
                    raw_payload={"mode": "below_fold_summary"},
                )
            )
        return offers

    async def _after_load_interactions(self, page) -> None:
        consent_selectors = [
            "button#onetrust-accept-btn-handler",
            "button:has-text('Accept')",
            "button:has-text('I agree')",
            "button:has-text('同意')",
        ]
        for selector in consent_selectors:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                continue
            try:
                await locator.click(timeout=1200)
                await page.wait_for_timeout(700)
                break
            except Exception:
                continue

        await page.wait_for_timeout(1200)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.55)")
        await page.wait_for_timeout(1200)

        candidates = [
            "button:has-text('Room')",
            "button:has-text('Price')",
            "button:has-text('查看')",
            "button:has-text('客房')",
        ]
        for selector in candidates:
            locator = page.locator(selector).first
            if await locator.count() == 0:
                continue
            try:
                await locator.click(timeout=1200)
                await page.wait_for_timeout(1200)
                break
            except Exception:
                continue

    async def _parse_html_prices(self, page, request: SearchRequest) -> list[RawRateOffer]:
        """Parse rendered HTML for dynamic prices like data-fpc-value='225'"""
        offers = []
        try:
            # Wait longer for JavaScript to fully execute
            await page.wait_for_timeout(5000)
            
            # Scroll to trigger lazy loading - multiple passes
            for i in range(3):
                await page.evaluate(f"window.scrollTo(0, {i * 500})")
                await page.wait_for_timeout(1000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(3000)
            
            # Try to click "Expand" or "Show More" buttons
            expand_selectors = [
                "button:has-text('Expand')",
                "button:has-text('Show More')",
                "button:has-text('展开更多')",
                "[data-selenium='show-more-rooms']",
                ".show-more-button",
            ]
            for sel in expand_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0:
                        await btn.click()
                        await page.wait_for_timeout(2000)
                except:
                    pass
            
            # Scroll back up and down after clicking
            await page.evaluate("window.scrollTo(0, 0)")
            await page.wait_for_timeout(1000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(3000)
            
            # Debug: get page content to check what's there
            content = await page.content()
            has_fpc = "data-fpc-value" in content
            has_childroom = "ChildRoomsList-room" in content
            print(f"DEBUG: Page has data-fpc-value: {has_fpc}, has ChildRoomsList-room: {has_childroom}")
            self.logger.info("Page has data-fpc-value: %s, has ChildRoomsList-room: %s", has_fpc, has_childroom)
            
            # Find all price elements with data-fpc-value attribute
            price_elements = await page.query_selector_all("[data-fpc-value]")
            
            print(f"DEBUG: Found {len(price_elements)} price elements with data-fpc-value")
            self.logger.info("Found %d price elements with data-fpc-value", len(price_elements))
            
            # Debug: also try other selectors
            display_rates = await page.query_selector_all("[data-element-display-rate]")
            print(f"DEBUG: Found {len(display_rates)} elements with data-element-display-rate")
            self.logger.info("Found %d elements with data-element-display-rate", len(display_rates))
            
            fpc_values = await page.eval_on_selector_all(
                "[data-fpc-value]",
                "elements => elements.map(e => e.getAttribute('data-fpc-value'))"
            )
            print(f"DEBUG: FPC values found: {fpc_values[:10]}")
            self.logger.info("FPC values found: %s", fpc_values[:10])
            
            # Also search entire HTML for "225" as string
            if "225" in content:
                print("DEBUG: Found '225' in page HTML!")
                # Find context
                idx = content.find("225")
                print(f"DEBUG: Context: ...{content[max(0,idx-100):idx+100]}...")
            
            # Try finding FIRST room's price - look for the first price display
            first_price = await page.eval_on_selector(
                ".PriceDisplay .finalPrice, [data-selenium='PriceDisplay'] .finalPrice, .MasterRoom .finalPrice",
                "el => el ? el.innerText.trim() : null"
            )
            print(f"DEBUG: First price displayed: {first_price}")
            
            # Also look for any price with "我们的最低价" (our lowest price) 
            lowest_price_elem = await page.query_selector("text=我们的最低价")
            if lowest_price_elem:
                print("DEBUG: Found 'our lowest price' element!")
                # Try to get the price from nearby elements
                parent = await lowest_price_elem.evaluate_handle("el => el.parentElement")
                for _ in range(10):
                    if not parent:
                        break
                    # Look for USD or price
                    price_text = await parent.evaluate("el => el ? el.innerText : ''")
                    if price_text and '$' in price_text:
                        print(f"DEBUG: Lowest price context: {price_text[:100]}")
                        break
                    parent = await parent.evaluate_handle("el => el ? el.parentElement : null")
            
            # Try finding prices in any attribute containing "225" or similar
            all_elements = await page.query_selector_all("*")
            print(f"DEBUG: Total elements on page: {len(all_elements)}")
            self.logger.info("Total elements on page: %d", len(all_elements))
            
            for elem in price_elements:
                try:
                    # Get the data-fpc-value attribute
                    fpc_value = await elem.get_attribute("data-fpc-value")
                    if not fpc_value:
                        continue
                    
                    price = self._to_decimal(fpc_value)
                    if price is None or price <= Decimal("0"):
                        continue
                    
                    # Try to find the room name - look in parent elements
                    room_name = None
                    
                    # Walk up the DOM to find room name
                    parent = elem
                    for _ in range(10):  # Max 10 levels up
                        parent = await parent.evaluate_handle("el => el.parentElement")
                        if not parent:
                            break
                        # Look for room name in various attributes/elements
                        name_selectors = [
                            "[data-selenium='MasterRoom-infoRoomType']",
                            ".MasterRoom-infoRoomType",
                            "[class*='room']",
                            "h3", "h4", 
                        ]
                        for sel in name_selectors:
                            name_elem = await parent.query_selector(sel)
                            if name_elem:
                                room_name = await name_elem.inner_text()
                                if room_name:
                                    room_name = room_name.strip()
                                    if room_name:
                                        break
                        if room_name:
                            break
                    
                    if not room_name:
                        # Try another approach - find the room container
                        container = elem
                        for _ in range(15):
                            container = await container.evaluate_handle("el => el.parentElement")
                            if not container:
                                break
                            # Look for room type name in data attributes
                            for attr in ["data-element-name", "data-master-id"]:
                                val = await container.get_attribute(attr)
                                if val and "room" in str(val).lower():
                                    room_name = str(val)
                                    break
                            if room_name:
                                break
                    
                    if not room_name:
                        room_name = "Agoda offer"
                    
                    # Extract currency - look for USD in nearby elements
                    currency = "USD"
                    
                    offers.append(
                        RawRateOffer(
                            platform=self.platform,
                            platform_hotel_id=request.platform_hotel_id,
                            room_name=room_name[:255],
                            meal_plan=None,
                            cancellation_policy=None,
                            currency=currency,
                            base_price=price.quantize(Decimal("0.01")),
                            tax_fee=Decimal("0"),
                            final_price=price.quantize(Decimal("0.01")),
                            checkin=request.checkin,
                            checkout=request.checkout,
                            adults=request.adults,
                            children=request.children,
                            source_url=request.platform_url or "",
                            raw_payload={"mode": "html_parsing"},
                        )
                    )
                except Exception as e:
                    self.logger.debug("Error parsing price element: %s", e)
                    continue
            
            # Also try to find prices in data attributes on room items
            if not offers:
                room_items = await page.query_selector_all("[data-element-master-room-id]")
                for room_item in room_items:
                    try:
                        # Get master room ID as identifier
                        master_id = await room_item.get_attribute("data-element-master-room-id")
                        if not master_id:
                            continue
                        
                        # Look for price within this room item
                        price_elem = await room_item.query_selector("[data-fpc-value], [data-element-display-rate], [data-element-hotel-price-per-book]")
                        if price_elem:
                            for attr in ["data-fpc-value", "data-element-display-rate", "data-element-hotel-price-per-book"]:
                                val = await price_elem.get_attribute(attr)
                                if val:
                                    price = self._to_decimal(val)
                                    if price and price > Decimal("0"):
                                        room_name = f"Room {master_id}"
                                        # Try to get better room name
                                        name_elem = await room_item.query_selector("[data-selenium*='room']")
                                        if name_elem:
                                            name_text = await name_elem.inner_text()
                                            if name_text:
                                                room_name = name_text.strip()
                                        
                                        offers.append(
                                            RawRateOffer(
                                                platform=self.platform,
                                                platform_hotel_id=request.platform_hotel_id,
                                                room_name=room_name[:255],
                                                meal_plan=None,
                                                cancellation_policy=None,
                                                currency="USD",
                                                base_price=price.quantize(Decimal("0.01")),
                                                tax_fee=Decimal("0"),
                                                final_price=price.quantize(Decimal("0.01")),
                                                checkin=request.checkin,
                                                checkout=request.checkout,
                                                adults=request.adults,
                                                children=request.children,
                                                source_url=request.platform_url or "",
                                                raw_payload={"mode": "html_parsing"},
                                            )
                                        )
                                        break
                    except Exception:
                        continue
                        
        except Exception as e:
            self.logger.debug("Error in _parse_html_prices: %s", e)
        
        return offers
