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
                tax_fee = self._extract_decimal_deep(room, ("taxAndServiceFee", "tax", "taxesAndFees"), depth=4) or Decimal("0")

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
                        cancellation_policy=None,
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
