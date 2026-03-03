from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from hotelrate.config import get_settings
from hotelrate.schemas import LiveQuoteRequest, Platform
from hotelrate.services import LiveQuoteService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live meta quote across Trip/Booking/Google/Agoda")
    parser.add_argument("--hotel", required=True)
    parser.add_argument("--city", default="")
    parser.add_argument("--checkin", required=True, help="YYYY-MM-DD")
    parser.add_argument("--checkout", required=True, help="YYYY-MM-DD")
    parser.add_argument("--adults", type=int, default=2)
    parser.add_argument("--children", type=int, default=0)
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--platforms", default="trip,booking,google_hotels,agoda")
    parser.add_argument("--trip-url", default="")
    parser.add_argument("--booking-url", default="")
    parser.add_argument("--google-url", default="")
    parser.add_argument("--agoda-url", default="")
    parser.add_argument("--probe-days", type=int, default=12)
    parser.add_argument("--probe-step", type=int, default=3)
    parser.add_argument("--out", default="")
    parser.add_argument("--demo-mode", action="store_true", help="Use deterministic demo offers.")
    return parser.parse_args()


def build_known_urls(args: argparse.Namespace) -> dict[str, str]:
    data = {
        Platform.TRIP.value: args.trip_url.strip(),
        Platform.BOOKING.value: args.booking_url.strip(),
        Platform.GOOGLE_HOTELS.value: args.google_url.strip(),
        Platform.AGODA.value: args.agoda_url.strip(),
    }
    valid: dict[str, str] = {}
    for platform, raw in data.items():
        if not raw:
            continue
        parsed = urlparse(raw)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            valid[platform] = raw
            continue
        print(
            f"warning: ignored invalid --{platform.replace('_hotels', '')}-url value: {raw}",
            file=sys.stderr,
        )
    return valid


async def main() -> None:
    args = parse_args()
    requested_platforms = [
        Platform(item.strip())
        for item in args.platforms.split(",")
        if item.strip()
    ]

    req = LiveQuoteRequest(
        hotel_name=args.hotel,
        city=args.city,
        checkin=date.fromisoformat(args.checkin),
        checkout=date.fromisoformat(args.checkout),
        adults=args.adults,
        children=args.children,
        currency=args.currency,
        platforms=requested_platforms,
        known_urls=build_known_urls(args),
        probe_days_ahead=args.probe_days,
        probe_step_days=args.probe_step,
    )

    settings = get_settings().model_copy(update={"demo_mode": bool(args.demo_mode)})
    service = LiveQuoteService(settings)
    resp = await service.quote(req)
    payload = resp.model_dump(mode="json")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved report: {out_path}")

    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
