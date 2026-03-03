---
name: hotel-meta-live-quote
description: Run end-to-end live hotel quote collection across Trip.com, Booking.com, Google Hotels, and Agoda from hotel name + check-in/check-out dates. Includes auto URL discovery, persistent login profiles, structured parsing modes (trip_room_list_oversea, booking_env, below_fold_room_grid, dom_card/supplier_text), and troubleshooting workflow.
---

# Hotel Meta Live Quote

Use this workflow for the local project at `/Users/seanbase/Desktop/hotelrate`.

## Workflow

1) Validate runtime
- Ensure venv exists and is active:
  - `source /Users/seanbase/Desktop/hotelrate/.venv/bin/activate`
- Ensure core dependencies are installed:
  - `pip install -e /Users/seanbase/Desktop/hotelrate`
  - `playwright install chromium`
- Check Firecrawl local service (optional but preferred):
  - `curl -s -X POST http://localhost:3002/v1/map -H 'Content-Type: application/json' -d '{"url":"https://example.com"}'`

2) Run one-shot live quote (main entry, hotel-name-driven)
- Use:
  - `python /Users/seanbase/Desktop/hotelrate/scripts/live_meta_quote.py --hotel "<hotel name>" --city "<city>" --checkin YYYY-MM-DD --checkout YYYY-MM-DD --currency USD --probe-days 3 --probe-step 3 --out /Users/seanbase/Desktop/hotelrate/reports/live_quote_latest.json`
- If user provides platform URLs, pass them through:
  - `--trip-url ... --booking-url ... --google-url ... --agoda-url ...`
- If only testing one platform:
  - `--platforms trip` (or `booking`, `google_hotels`, `agoda`)

3) URL discovery check (when hit-rate is low)
- Run:
  - `python /Users/seanbase/Desktop/hotelrate/scripts/discover_platform_urls.py --hotel "<hotel name>" --city "<city>" --checkin YYYY-MM-DD --checkout YYYY-MM-DD --top 5`
- Expected: detail URLs should appear on top.
- Discovery stack already includes:
  - platform URL builders
  - Yahoo + Brave + DuckDuckGo
  - Firecrawl `map + crawl`
  - HTML and Playwright extraction of detail links

4) Diagnose platform failures quickly
- Run platform sample diagnostics:
  - `python /Users/seanbase/Desktop/hotelrate/scripts/run_sample_live_urls.py`
- Inspect payload-level issues:
  - `python /Users/seanbase/Desktop/hotelrate/scripts/inspect_live_payloads.py --platform <trip|booking|google_hotels|agoda> --platform-hotel-id <id> --platform-url "<url>" --checkin YYYY-MM-DD --nights 1`

5) Login/session warmup (persistent profile)
- Trip/Booking/Agoda/Google warmup:
  - `python /Users/seanbase/Desktop/hotelrate/scripts/platform_login_warmup.py --platform trip --wait-seconds 300`
  - `python /Users/seanbase/Desktop/hotelrate/scripts/platform_login_warmup.py --platform booking --wait-seconds 300`
  - `python /Users/seanbase/Desktop/hotelrate/scripts/platform_login_warmup.py --platform agoda --wait-seconds 300`
- Trip session probe:
  - `python /Users/seanbase/Desktop/hotelrate/scripts/trip_session_probe.py`
- Recommended `.env` profile settings:
  - `PLAYWRIGHT_USER_DATA_DIR_TRIP=.playwright/trip-profile`
  - `PLAYWRIGHT_USER_DATA_DIR_BOOKING=.playwright/booking-profile`
  - `PLAYWRIGHT_USER_DATA_DIR_AGODA=.playwright/agoda-profile`
  - `PLAYWRIGHT_USER_DATA_DIR_GOOGLE_HOTELS=.playwright/google_hotels-profile`
- Note: persistent profile mode avoids extra request headers to reduce Trip blank-page/no-payload issues.

6) Run nightly/batch job
- Execute:
  - `python /Users/seanbase/Desktop/hotelrate/scripts/nightly_quote_job.py`
- Print compact morning summary:
  - `python /Users/seanbase/Desktop/hotelrate/scripts/report_nightly_summary.py`

## Output Expectations

When replying to the user after running this skill:
- Report per platform: selected URL, offer count, structured offer count, diagnosis.
- Show top offers with room name + final price + currency + cancellation + mode.
- Call out parser mode quality explicitly:
  - Trip: `trip_room_list_oversea` (preferred)
  - Booking: `booking_env` (preferred)
  - Agoda: `below_fold_room_grid` / `below_fold_summary`
  - Google Hotels: `dom_card` (hotel cards) or `supplier_text` (detail page supplier quotes)
- Mention where artifacts are written:
  - `/Users/seanbase/Desktop/hotelrate/reports/live_quote_latest.json`
  - `/Users/seanbase/Desktop/hotelrate/reports/nightly_quote_report.json`

## Guardrails

- Prefer structured extraction (`trip_room_list_oversea`, `booking_env`, `below_fold_room_grid`, `dom_card`, `supplier_text`) over `text_fallback`.
- If no structured offers for a platform, keep fallback output but label it clearly as low confidence.
- For Google Hotels, distinguish:
  - exact hotel supplier offers from “All options”
  - similar/nearby hotel cards (do not mix into same-hotel decision).
- Do not skip execution: run commands, inspect outputs, and iterate automatically.
