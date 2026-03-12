from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from playwright.async_api import async_playwright

from hotelrate.collectors.base import BaseCollector
from hotelrate.schemas import Platform, RawRateOffer, SearchRequest


class GoogleHotelsCollector(BaseCollector):
    platform = Platform.GOOGLE_HOTELS
    RESPONSE_PATTERNS = (
        "google.com",
        "travel",
        "TravelFrontendUi",
        "HotelRoom",
        "HotelSearch",
        "mercury",
        "batch",
        "hotel",
        "offers",
        "price",
        "availability",
        "search",
    )
    DROPPED_QUERY_KEYS = (
        "ved",
        "ei",
        "ictx",
        "sxsrf",
        "sourceid",
    )
    SUPPLIER_KEYWORDS = (
        "booking",
        "agoda",
        "trip.com",
        "trip",
        "expedia",
        "hotels.com",
        "hotels",
        "klook",
        "priceline",
        "traveluro",
        "travelocity",
        "kayak",
        "wego",
        "official site",
        "official website",
        "官方网站",
    )

    async def fetch_rates(self, request: SearchRequest) -> list[RawRateOffer]:
        if self.settings.demo_mode:
            return [self.build_demo_offer(request, low=85, high=330)]
        return await self._fetch_live_rates(request)

    async def _fetch_live_rates(self, request: SearchRequest) -> list[RawRateOffer]:
        url = self._build_search_url(request)
        try:
            async with async_playwright() as pw:
                browser, context = await self.open_playwright_context(pw)
                page = await context.new_page()
                payloads = await self.capture_json_payloads(
                    page=page,
                    url=url,
                    response_patterns=self.RESPONSE_PATTERNS,
                    settle_ms=4500,
                    after_load=lambda p: self._after_load_interactions(p, request=request),
                )
                offers = self._parse_structured_offers(request=request, payloads=payloads)
                if not offers:
                    offers = await self._parse_script_json_offers(page=page, request=request)
                if not offers:
                    offers = await self.parse_ld_json_fallback(page=page, request=request, max_offers=10)
                if not offers:
                    offers = await self._parse_google_travel_dom_selectors(page=page, request=request)
                if not offers:
                    offers = await self._parse_google_price_panel_dom(page=page, request=request)
                if not offers:
                    offers = await self._parse_supplier_text_offers(page=page, request=request)
                if not offers:
                    offers = await self._parse_aria_label_card_offers(page=page, request=request)
                if not offers:
                    offers = await self._parse_listing_dom_offers(page=page, request=request)
                if not offers:
                    offers = await self.parse_text_price_fallback(page=page, request=request, max_offers=8)
                structured_count = sum(1 for o in offers if str(o.raw_payload.get("mode", "")).lower() not in ("text_fallback", "url_fallback", "demo"))
                if getattr(self.settings, "google_debug_save_html", False) and structured_count == 0 and offers:
                    try:
                        from pathlib import Path
                        import time as _time
                        html = await page.content()
                        reports_dir = Path("reports")
                        reports_dir.mkdir(parents=True, exist_ok=True)
                        path = reports_dir / f"google_debug_{_time.strftime('%Y%m%d_%H%M%S', _time.localtime())}.html"
                        path.write_text(html, encoding="utf-8")
                        self.logger.info("google debug: saved page HTML to %s", path)
                    except Exception as e:
                        self.logger.debug("google debug save failed: %s", e)
                self.logger.info(
                    "google hotels crawl url=%s payloads=%d offers=%d",
                    url,
                    len(payloads),
                    len(offers),
                )
                await self.close_playwright_context(browser=browser, context=context)
            return offers
        except Exception as exc:
            self.logger.warning("google hotels crawl error: %s", exc, exc_info=False)
            return []

    async def _parse_supplier_text_offers(self, *, page, request: SearchRequest) -> list[RawRateOffer]:
        text = await page.inner_text("body")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []

        has_detail_signal = any(
            marker in " ".join(lines).lower()
            for marker in ("all options", "所有选项", "selected options", "精选选项", "view all prices", "compare prices")
        )
        if has_detail_signal:
            start_markers = (
                "selected options",
                "精选选项",
                "all options",
                "所有选项",
                "view all prices",
                "compare prices",
            )
            end_markers = (
                "similar hotels",
                "类似酒店",
                "nearby hotels",
                "附近酒店",
            )
            start_idx = 0
            for idx, line in enumerate(lines):
                lower = line.lower()
                if any(marker in lower for marker in start_markers):
                    start_idx = idx
                    break
            end_idx = len(lines)
            for idx in range(start_idx + 1, len(lines)):
                lower = lines[idx].lower()
                if any(marker in lower for marker in end_markers):
                    end_idx = idx
                    break
            segment = lines[start_idx:end_idx]
        else:
            segment = lines
        offers: list[RawRateOffer] = []
        seen: set[tuple[str, str, str]] = set()

        for idx, line in enumerate(segment):
            supplier = self._normalize_supplier_name(line)
            if not supplier:
                continue

            price_value: Decimal | None = None
            currency = request.currency.upper()
            price_idx = -1
            for probe in range(idx + 1, min(idx + 10, len(segment))):
                next_line = segment[probe]
                if probe > idx + 1 and self._normalize_supplier_name(next_line):
                    break
                parsed_price = self._extract_price_and_currency(next_line, default_currency=request.currency)
                if parsed_price is None:
                    continue
                price_value, currency = parsed_price
                price_idx = probe
                break

            if price_value is None or price_value <= Decimal("0"):
                continue

            notes: list[str] = []
            if price_idx > idx:
                for note_idx in range(idx + 1, price_idx):
                    note = segment[note_idx]
                    if self._is_action_line(note):
                        continue
                    if self._extract_price_and_currency(note, default_currency=request.currency):
                        continue
                    notes.append(note)
            cancellation = self._extract_supplier_cancellation(notes)

            dedupe = (supplier.lower(), f"{price_value:.2f}", currency)
            if dedupe in seen:
                continue
            seen.add(dedupe)

            amount = price_value.quantize(Decimal("0.01"))
            offers.append(
                RawRateOffer(
                    platform=self.platform,
                    platform_hotel_id=request.platform_hotel_id,
                    room_name=f"{supplier} offer",
                    meal_plan=None,
                    cancellation_policy=cancellation,
                    currency=currency,
                    base_price=amount,
                    tax_fee=Decimal("0"),
                    final_price=amount,
                    checkin=request.checkin,
                    checkout=request.checkout,
                    adults=request.adults,
                    children=request.children,
                    source_url=request.platform_url,
                    raw_payload={"mode": "supplier_text"},
                )
            )
            if len(offers) >= 20:
                break

        return offers

    def _normalize_supplier_name(self, line: str) -> str | None:
        value = line.strip()
        if not value:
            return None
        lower = value.lower()

        if self._is_action_line(value):
            return None
        if self._extract_price_and_currency(value, default_currency="USD"):
            return None

        if "官方网站" in value or "official website" in lower or "official site" in lower:
            return "Official website"

        domain_match = re.search(r"([a-z0-9.-]+\.(?:com|cn|net|org|co|io|travel))", lower)
        if domain_match:
            domain = domain_match.group(1)
            canonical = {
                "booking.com": "Booking.com",
                "agoda.com": "Agoda",
                "trip.com": "Trip.com",
                "expedia.com": "Expedia.com",
                "hotels.com": "Hotels.com",
                "klook.com": "Klook",
                "travelocity.com": "Travelocity.com",
                "kayak.com": "KAYAK.com",
                "orbitz.com": "Orbitz.com",
                "bluepillow.com": "Bluepillow.com",
                "wego.com": "Wego",
            }
            return canonical.get(domain, domain)

        if any(keyword in lower for keyword in self.SUPPLIER_KEYWORDS):
            if "booking" in lower:
                return "Booking.com"
            if "agoda" in lower:
                return "Agoda"
            if "trip" in lower:
                return "Trip.com"
            if "expedia" in lower:
                return "Expedia.com"
            if "hotels" in lower:
                return "Hotels.com"
            if "kayak" in lower:
                return "KAYAK.com"
            return value

        return None

    def _is_action_line(self, line: str) -> bool:
        lower = line.strip().lower()
        return lower.startswith(("visit", "访问")) or "网站" in lower and "访问" in lower

    def _extract_price_and_currency(
        self,
        line: str,
        *,
        default_currency: str,
    ) -> tuple[Decimal, str] | None:
        patterns: list[tuple[re.Pattern[str], str]] = [
            (re.compile(r"US\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", flags=re.IGNORECASE), "USD"),
            (re.compile(r"USD\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", flags=re.IGNORECASE), "USD"),
            (re.compile(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(?:per night|nightly|total|/night)?", flags=re.IGNORECASE), "USD"),
            (re.compile(r"[¥￥]\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", flags=re.IGNORECASE), "CNY"),
        ]
        for pattern, currency in patterns:
            match = pattern.search(line)
            if not match:
                continue
            amount = self._to_decimal(match.group(1))
            if amount is None:
                continue
            if amount < Decimal("20"):
                continue
            return amount, currency

        return None

    def _extract_supplier_cancellation(self, notes: list[str]) -> str | None:
        if not notes:
            return None
        merged = " · ".join(item.strip() for item in notes if item.strip())
        if not merged:
            return None

        lower = merged.lower()
        if "free cancellation" in lower or "免费取消" in merged:
            return merged[:255]
        if "non-refundable" in lower or "不可退款" in merged or "不可退" in merged:
            return merged[:255]

        return merged[:255]

    def _build_search_url(self, request: SearchRequest) -> str:
        query = {
            "q": request.platform_hotel_id,
            "checkin": request.checkin.isoformat(),
            "checkout": request.checkout.isoformat(),
            "adults": request.adults,
            "children": request.children,
            "hl": "en-US",
            "gl": "us",
        }

        if request.platform_url:
            cleaned = self.remove_url_query_keys(request.platform_url, self.DROPPED_QUERY_KEYS)
            return self.merge_url_query(cleaned, query)

        return self.merge_url_query("https://www.google.com/travel/search", query)

    def _parse_structured_offers(
        self,
        *,
        request: SearchRequest,
        payloads: list[dict],
    ) -> list[RawRateOffer]:
        return self.parse_payloads_to_offers(
            request=request,
            payloads=payloads,
            room_keys=("roomName", "room_type", "roomType", "offerName", "name"),
            final_price_keys=("totalPrice", "finalPrice", "price", "amount"),
            price_keys=("basePrice", "priceBeforeTax", "price", "amount"),
            tax_keys=("tax", "fees", "taxesAndFees"),
            meal_keys=("mealPlan", "board", "breakfast"),
            cancellation_keys=("cancellationPolicy", "freeCancellation"),
            currency_keys=("currencyCode", "currency"),
            max_offers=25,
        )

    async def _parse_script_json_offers(self, *, page, request: SearchRequest) -> list[RawRateOffer]:
        """Extract offers from embedded JSON (e.g. __INITIAL_STATE__)."""
        try:
            raw = await page.evaluate(
                """
                () => {
                    const out = [];
                    const tryParse = (obj, depth) => {
                        if (depth > 6) return;
                        if (!obj || typeof obj !== 'object') return;
                        if (Array.isArray(obj)) { obj.slice(0, 50).forEach(i => tryParse(i, depth + 1)); return; }
                        const keys = Object.keys(obj);
                        const hasPrice = keys.some(k => /price|amount|total/i.test(k));
                        const hasName = keys.some(k => /name|room|supplier|provider|title/i.test(k));
                        if (hasPrice && hasName) {
                            const name = obj.name || obj.roomName || obj.supplierName || obj.providerName || obj.title || '';
                            const price = obj.price || obj.totalPrice || obj.finalPrice || obj.amount;
                            if (typeof name === 'string' && (typeof price === 'number' || (typeof price === 'string' && /^[0-9.]+$/.test(price)))) {
                                const num = typeof price === 'string' ? parseFloat(price) : price;
                                if (num >= 20 && num < 5000) out.push({ name: name.slice(0, 200), price: num });
                            }
                        }
                        keys.forEach(k => tryParse(obj[k], depth + 1));
                    };
                    ['__INITIAL_STATE__', '__NEXT_DATA__', '__NUXT__', 'initialState', 'pageData'].forEach(k => {
                        if (typeof window[k] !== 'undefined') tryParse(window[k], 0);
                    });
                    return out.slice(0, 25);
                }
                """
            )
        except Exception:
            return []
        if not raw or not isinstance(raw, list):
            return []
        offers = []
        seen: set[tuple[str, str]] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            price = self._to_decimal(item.get("price"))
            if not name or price is None or price < Decimal("20"):
                continue
            key = (name.lower()[:80], f"{price:.2f}")
            if key in seen:
                continue
            seen.add(key)
            offers.append(
                RawRateOffer(
                    platform=self.platform,
                    platform_hotel_id=request.platform_hotel_id,
                    room_name=name[:255],
                    meal_plan=None,
                    cancellation_policy=None,
                    currency=request.currency.upper(),
                    base_price=price,
                    tax_fee=Decimal("0"),
                    final_price=price,
                    checkin=request.checkin,
                    checkout=request.checkout,
                    adults=request.adults,
                    children=request.children,
                    source_url=request.platform_url,
                    raw_payload={"mode": "script_json"},
                )
            )
            if len(offers) >= 15:
                break
        return offers

    async def _parse_google_travel_dom_selectors(self, *, page, request: SearchRequest) -> list[RawRateOffer]:
        """Extract offers from Google Travel price panel using exact DOM: .ADs2Tc/.CcERhd cards, .RjilDd/.FjC1We supplier, .iqYCVb/.nDkDDb price."""
        try:
            # Wait for price cards to appear (panel may load after click or after Retry)
            try:
                await page.wait_for_selector(".ADs2Tc, .CcERhd", state="visible", timeout=6000)
            except Exception:
                return []
            # Scroll price panel into view in case it's in a drawer/sidebar
            try:
                first_card = page.locator(".ADs2Tc, .CcERhd").first
                await first_card.scroll_into_view_if_needed(timeout=2000)
                await page.wait_for_timeout(500)
            except Exception:
                pass
            rows = await page.eval_on_selector_all(
                "body",
                """
                (body) => {
                    const out = [];
                    const priceRe = /(?:US\\$|\\$|USD)\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)/i;
                    const cards = body.querySelectorAll('.ADs2Tc, .CcERhd');
                    for (const card of cards) {
                        const nameEl = card.querySelector('.RjilDd') || card.querySelector('.FjC1We.ogfYpf.zUyrwb');
                        const priceEl = card.querySelector('.iqYCVb') || card.querySelector('.nDkDDb');
                        if (!nameEl || !priceEl) continue;
                        const supplier = (nameEl.textContent || '').trim();
                        const priceText = (priceEl.textContent || '').trim();
                        const m = priceText.match(priceRe);
                        if (!supplier || !m) continue;
                        const price = parseFloat(m[1].replace(/,/g, ''));
                        if (isNaN(price) || price < 20 || price > 10000) continue;
                        out.push({ supplier, price });
                        if (out.length >= 25) break;
                    }
                    return out;
                }
                """
            )
        except Exception:
            return []
        if not rows or not isinstance(rows, list):
            return []
        offers = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            supplier = str(row.get("supplier", "")).strip()
            price = self._to_decimal(row.get("price"))
            if not supplier or price is None or price < Decimal("20"):
                continue
            key = (supplier.lower(), f"{price:.2f}")
            if key in seen:
                continue
            seen.add(key)
            offers.append(
                RawRateOffer(
                    platform=self.platform,
                    platform_hotel_id=request.platform_hotel_id,
                    room_name=f"{supplier}",
                    meal_plan=None,
                    cancellation_policy=None,
                    currency=request.currency.upper(),
                    base_price=price,
                    tax_fee=Decimal("0"),
                    final_price=price,
                    checkin=request.checkin,
                    checkout=request.checkout,
                    adults=request.adults,
                    children=request.children,
                    source_url=request.platform_url,
                    raw_payload={"mode": "google_travel_selectors"},
                )
            )
            if len(offers) >= 20:
                break
        return offers

    async def _parse_google_price_panel_dom(self, *, page, request: SearchRequest) -> list[RawRateOffer]:
        """Extract supplier + price from price comparison panel."""
        try:
            rows = await page.eval_on_selector_all(
                "body",
                """
                (body) => {
                    const out = []; const priceRe = /(?:US\\$|\\$|USD)\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)/gi;
                    const suppliers = ['Booking.com', 'Agoda', 'Trip.com', 'Expedia', 'Hotels.com', 'KAYAK', 'Official website', '官方网站'];
                    const walk = (node, depth) => {
                        if (depth > 8) return;
                        if (!node || node.nodeType !== 1) return;
                        const text = (node.innerText || '').trim();
                        if (text.length < 10 || text.length > 1200) { for (const ch of node.children || []) walk(ch, depth + 1); return; }
                        const matches = [...text.matchAll(priceRe)];
                        if (matches.length === 0) { for (const ch of node.children || []) walk(ch, depth + 1); return; }
                        let supplier = ''; for (const s of suppliers) { if (text.includes(s)) { supplier = s; break; } }
                        if (!supplier) { const m = text.match(/([a-z0-9.-]+\\.(?:com|cn|net|org))/i); if (m) supplier = m[1]; }
                        if (!supplier && node.parentElement) { const pt = (node.parentElement.innerText || '').trim(); if (pt.length < 2000) for (const s of suppliers) { if (pt.includes(s)) { supplier = s; break; } } }
                        if (!supplier) { for (const ch of node.children || []) walk(ch, depth + 1); return; }
                        const price = parseFloat(matches[0][1].replace(/,/g, ''));
                        if (isNaN(price) || price < 20 || price > 10000) return;
                        const key = supplier + '|' + price; if (!window.__gSeen) window.__gSeen = new Set();
                        if (window.__gSeen.has(key)) return; window.__gSeen.add(key);
                        out.push({ supplier, price }); if (out.length >= 20) return;
                    };
                    window.__gSeen = new Set(); walk(body, 0); return out;
                }
                """
            )
        except Exception:
            return []
        if not rows or not isinstance(rows, list):
            return []
        offers = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            supplier = str(row.get("supplier", "")).strip()
            price = self._to_decimal(row.get("price"))
            if not supplier or price is None or price < Decimal("20"):
                continue
            key = (supplier.lower(), f"{price:.2f}")
            if key in seen:
                continue
            seen.add(key)
            offers.append(
                RawRateOffer(
                    platform=self.platform,
                    platform_hotel_id=request.platform_hotel_id,
                    room_name=f"{supplier}",
                    meal_plan=None,
                    cancellation_policy=None,
                    currency=request.currency.upper(),
                    base_price=price,
                    tax_fee=Decimal("0"),
                    final_price=price,
                    checkin=request.checkin,
                    checkout=request.checkout,
                    adults=request.adults,
                    children=request.children,
                    source_url=request.platform_url,
                    raw_payload={"mode": "google_price_panel"},
                )
            )
            if len(offers) >= 15:
                break
        return offers

    async def _after_load_interactions(self, page, request: SearchRequest | None = None) -> None:
        # Google Travel often shows "Loading results" first; wait for hotel list to render
        # (hotel name or "Prices starting from" in body). Without this, saved HTML has no
        # price panel and no link to click.
        name_part = (request.platform_hotel_id or "").replace("+", " ").strip()[:30] if request else ""
        try:
            await page.wait_for_function(
                """(namePart) => {
                    const t = (document.body && document.body.innerText) ? document.body.innerText : '';
                    if (/Loading results|Loading map/i.test(t) && t.length < 800) return false;
                    if (namePart && t.includes(namePart)) return true;
                    if (/Prices starting from|Back to list of all results/i.test(t)) return true;
                    return false;
                }""",
                name_part,
                timeout=18000,
            )
            await page.wait_for_timeout(1500)
        except Exception:
            try:
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.5)")
                await page.wait_for_timeout(3000)
            except Exception:
                pass

        await page.wait_for_timeout(1500)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.4)")
        await page.wait_for_timeout(1200)

        if request and getattr(request, "platform_hotel_id", None):
            name_part = (request.platform_hotel_id or "").replace("+", " ").strip()[:30]
            if name_part:
                try:
                    link_with_name = page.locator("a[href*='/travel/']").filter(has_text=name_part[:20]).first
                    if await link_with_name.count() > 0:
                        await link_with_name.scroll_into_view_if_needed(timeout=3000)
                        await page.wait_for_timeout(500)
                        await link_with_name.click(timeout=3000)
                        await page.wait_for_timeout(3000)
                except Exception:
                    pass
                try:
                    prices_link = page.locator("a[aria-label*='Prices starting from']").first
                    if await prices_link.count() > 0:
                        await prices_link.scroll_into_view_if_needed(timeout=2000)
                        await page.wait_for_timeout(400)
                        await prices_link.click(timeout=2000)
                        await page.wait_for_timeout(3000)
                except Exception:
                    pass

        expand_selectors = [
            "a[aria-label*='Prices starting from']",
            "a[aria-label*='price']",
            "a[aria-label*='Price']",
            "button[aria-label*='price']",
            "button[aria-label*='Price']",
            "button[aria-label*='options']",
            "button[aria-label*='Options']",
            "span:has-text('View all prices')",
            "span:has-text('All options')",
            "span:has-text('See all prices')",
            "span:has-text('Compare prices')",
            "div[role='button']:has-text('View all')",
            "div[role='button']:has-text('All options')",
            "a[href*='/travel/hotels']",
            "button:has-text('Prices')",
            "a:has-text('Prices')",
        ]
        for selector in expand_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.count() == 0:
                    continue
                await locator.scroll_into_view_if_needed(timeout=2000)
                await page.wait_for_timeout(300)
                await locator.click(timeout=1500)
                await page.wait_for_timeout(2000)
                break
            except Exception:
                continue

        hotel_cards = page.locator("a[aria-label*='Prices starting from'], a[aria-label*='price']")
        if await hotel_cards.count() > 0:
            try:
                await hotel_cards.first.scroll_into_view_if_needed(timeout=2000)
                await page.wait_for_timeout(400)
                await hotel_cards.first.click(timeout=1800)
                await page.wait_for_timeout(3500)
            except Exception:
                pass

        # If price panel shows "Error loading prices", click Retry so cards can render
        for _ in range(2):
            try:
                retry_btn = page.locator("button:has-text('Retry'), button:has-text('重试')").first
                if await retry_btn.count() > 0:
                    await retry_btn.click(timeout=2000)
                    await page.wait_for_timeout(5000)
            except Exception:
                break

        # Wait for price comparison panel to render (saved debug HTML often lacks panel content
        # because we captured before it opened; wait for supplier names or panel text)
        try:
            await page.wait_for_function(
                """() => {
                    const t = (document.body && document.body.innerText) ? document.body.innerText : '';
                    return /Booking|Agoda|Trip\\.com|Expedia|Compare prices|All options|View all prices|精选选项|所有选项/.test(t);
                }""",
                timeout=10000,
            )
            await page.wait_for_timeout(2000)
        except Exception:
            pass

        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.3)")
        await page.wait_for_timeout(800)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 0.6)")
        await page.wait_for_timeout(1000)

    async def _parse_aria_label_card_offers(self, *, page, request: SearchRequest) -> list[RawRateOffer]:
        rows = await page.eval_on_selector_all(
            "a[aria-label]",
            """
            (nodes) => {
              const out = [];
              const seen = new Set();
              const extract = (aria) => {
                const patterns = [
                  /Prices starting from\\s*(?:US\\$|\\$)\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)\\s*,\\s*(.+)$/i,
                  /^(.+?)\\s*,\\s*(?:US\\$|\\$)\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)$/i,
                  /^(.+?)\\s*[，,]\\s*(?:¥|￥|€|£)\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)$/i,
                ];
                for (const re of patterns) {
                  const m = aria.match(re);
                  if (!m) continue;
                  if (m.length === 3 && /Prices starting from/i.test(m[0])) {
                    return { name: m[2].trim(), price: m[1] };
                  }
                  return { name: m[1].trim(), price: m[2] };
                }
                return null;
              };
              const nightlyRe = /\\$\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)\\s*nightly/i;
              const totalRe = /\\$\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)\\s*total/i;
              for (const node of nodes) {
                const aria = (node.getAttribute('aria-label') || '').trim();
                const parsed = extract(aria);
                if (!parsed) continue;
                const price = parsed.price;
                const name = parsed.name;
                if (!name) continue;
                const text = (node.innerText || '').trim();
                const nightlyMatch = text.match(nightlyRe);
                const totalMatch = text.match(totalRe);
                const key = `${name}|${price}`;
                if (seen.has(key)) continue;
                seen.add(key);
                out.push({
                  name,
                  startPrice: price,
                  nightlyPrice: nightlyMatch ? nightlyMatch[1] : '',
                  totalPrice: totalMatch ? totalMatch[1] : '',
                  snippet: text.slice(0, 200),
                });
                if (out.length >= 18) break;
              }
              return out;
            }
            """,
        )

        offers: list[RawRateOffer] = []
        for row in rows:
            name = str(row.get("name", "")).strip()
            if not name:
                continue

            nightly = self._to_decimal(row.get("nightlyPrice"))
            total = self._to_decimal(row.get("totalPrice"))
            start_price = self._to_decimal(row.get("startPrice"))

            final_price = nightly or total or start_price
            if final_price is None or final_price < Decimal("20"):
                continue

            final_price = final_price.quantize(Decimal("0.01"))
            offers.append(
                RawRateOffer(
                    platform=self.platform,
                    platform_hotel_id=request.platform_hotel_id,
                    room_name=name[:255],
                    meal_plan=None,
                    cancellation_policy=None,
                    currency=request.currency.upper(),
                    base_price=final_price,
                    tax_fee=Decimal("0"),
                    final_price=final_price,
                    checkin=request.checkin,
                    checkout=request.checkout,
                    adults=request.adults,
                    children=request.children,
                    source_url=request.platform_url,
                    raw_payload={
                        "mode": "dom_card",
                        "snippet": str(row.get("snippet", ""))[:200],
                    },
                )
            )
            if len(offers) >= 10:
                break
        return offers

    async def _parse_listing_dom_offers(
        self,
        *,
        page,
        request: SearchRequest,
    ) -> list[RawRateOffer]:
        rows = await page.eval_on_selector_all(
            "a, div[role='button'], div",
            """
            (nodes) => {
              const out = [];
              const seen = new Set();
              const priceRe = /\\$\\s*([0-9][0-9,]*(?:\\.[0-9]{1,2})?)/;
              for (const node of nodes) {
                const text = (node.innerText || '').trim();
                if (!text || text.length < 10) continue;
                const match = text.match(priceRe);
                if (!match) continue;
                const lines = text.split('\\n').map((x) => x.trim()).filter(Boolean);
                const name = lines[0] || '';
                if (!name || /^\\$/.test(name)) continue;
                const price = match[1];
                const key = `${name}|${price}`;
                if (seen.has(key)) continue;
                seen.add(key);
                out.push({
                  name,
                  price,
                  snippet: text.slice(0, 220),
                });
                if (out.length >= 20) break;
              }
              return out;
            }
            """,
        )

        offers: list[RawRateOffer] = []
        for row in rows:
            name = str(row.get("name", "")).strip()
            raw_price = str(row.get("price", "")).strip().replace(",", "")
            if not name or not raw_price:
                continue
            if "results" in name.lower():
                continue
            if not re.match(r"^[0-9]+(?:\.[0-9]{1,2})?$", raw_price):
                continue
            amount = Decimal(raw_price).quantize(Decimal("0.01"))
            if amount < Decimal("20"):
                continue

            offers.append(
                RawRateOffer(
                    platform=self.platform,
                    platform_hotel_id=request.platform_hotel_id,
                    room_name=name[:255],
                    meal_plan=None,
                    cancellation_policy=None,
                    currency=request.currency,
                    base_price=amount,
                    tax_fee=Decimal("0"),
                    final_price=amount,
                    checkin=request.checkin,
                    checkout=request.checkout,
                    adults=request.adults,
                    children=request.children,
                    source_url=request.platform_url,
                    raw_payload={"mode": "dom_listing", "snippet": row.get("snippet", "")},
                )
            )
            if len(offers) >= 10:
                break

        return offers
