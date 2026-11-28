"""Collect indicative public rates, never assume taxes are included."""
import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

def identity(url):
    p = urlsplit(url or "")
    return (p.hostname, p.path.rstrip("/"))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["booking", "agoda"], required=True)
    parser.add_argument("--days", type=int, choices=range(1, 8), default=1)
    args = parser.parse_args()
    platform = args.platform
    currency = 'EUR' if platform == 'booking' else 'USD'
    hotels = json.loads((ROOT / "config/nomads_competitors.json").read_text())
    today = datetime.now(ZoneInfo("Europe/Istanbul")).date()
    folder = ROOT / "reports" / ("competitors-" + platform)
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, hotel in enumerate(hotels):
        for offset in range(1, args.days + 1):
            checkin = today + timedelta(days=offset)
            checkout = checkin + timedelta(days=1)
            url = hotel.get(platform)
            row = dict(scan_date=str(today), hotel=hotel["name"], platform=platform,
                       checkin=str(checkin), checkout=str(checkout), currency=currency,
                       price="", room="", status="not_listed", tax_inclusion="unknown")
            report = folder / f"{i}-{checkin}.json"
            if url:
                row["status"] = "collection_failed"
                cmd = [sys.executable, str(ROOT / "scripts/live_meta_quote.py"),
                       "--hotel", hotel["name"], "--city", "Göreme", "--checkin", str(checkin),
                       "--checkout", str(checkout), "--adults", "2", "--children", "0",
                       "--currency", currency, "--platforms", platform, f"--{platform}-url", url,
                       "--probe-days", "0", "--no-rich", "--out", str(report)]
                try:
                    report.unlink(missing_ok=True)
                    subprocess.run(cmd, cwd=ROOT, check=True, timeout=150)
                    data = json.loads(report.read_text())
                    result = next((x for x in data["results"] if x["platform"] == platform), {})
                    if identity(result.get("selected_url")) != identity(url):
                        row["status"] = "property_url_mismatch"
                    elif (result.get("selected_checkin"), result.get("selected_checkout")) != (str(checkin), str(checkout)):
                        row["status"] = "date_mismatch"
                    elif not result.get("offers"):
                        row["status"] = "no_offers"
                    else:
                        candidates = []
                        for offer in result["offers"]:
                            if offer.get("currency") != currency:
                                continue
                            if offer.get("mode") not in {"booking_env", "room_grid_offer"}:
                                continue
                            try:
                                price = Decimal(str(offer["final_price"]))
                                if price.is_finite() and price > 0:
                                    candidates.append((price, offer.get("room_name") or ""))
                            except (InvalidOperation, KeyError):
                                continue
                        if candidates:
                            price, room = min(candidates)
                            row.update(price=str(price), room=room, status="indicative_unverified")
                        else:
                            row["status"] = "no_eligible_currency_offer"
                except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError) as exc:
                    print(f"Collection failed for {hotel['name']}: {type(exc).__name__}", flush=True)
            rows.append(row)
            print("NOMADS_SUMMARY", json.dumps(row, ensure_ascii=False), flush=True)
    with (folder / "summary.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    if not any(row["price"] for row in rows):
        raise SystemExit("No eligible candidate prices collected")

if __name__ == "__main__":
    main()
