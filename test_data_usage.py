#!/usr/bin/env python3
"""
Test script for eero data_usage endpoint.

Exercises the new get_data_usage / get_data_usage_devices methods on
EeroClientWrapper and compares against the existing accumulated bandwidth.
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

from src.config import ensure_data_directory, get_settings
from src.eero_client import EeroClientWrapper
from src.models.database import DailyBandwidth
from src.utils.database import get_db_context, init_database


def fmt_bytes(b: float) -> str:
    """Format bytes into a human-readable string."""
    if b >= 1e9:
        return f"{b / 1e9:.2f} GB"
    if b >= 1e6:
        return f"{b / 1e6:.2f} MB"
    if b >= 1e3:
        return f"{b / 1e3:.2f} KB"
    return f"{b:.0f} B"


def print_series(result: dict, label: str) -> None:
    """Print a data_usage response in readable format."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")

    if not result:
        print("  (no data)")
        return

    series = result.get("series", [])
    if not series:
        print("  (empty series)")
        print(f"  Raw keys: {list(result.keys())}")
        print(f"  Raw: {json.dumps(result, indent=2)[:500]}")
        return

    for s in series:
        direction = s.get("type", "?")
        total = s.get("sum", 0)
        values = s.get("values", [])
        non_zero = [v for v in values if v and v != 0]
        print(f"  {direction:>10}: {fmt_bytes(total):>12}  "
              f"({len(values)} buckets, {len(non_zero)} non-zero)")

    # Show raw if there are extra keys we didn't expect
    extra = set(result.keys()) - {"series"}
    if extra:
        print(f"  Extra keys: {extra}")


def print_device_usage(result: dict) -> None:
    """Print per-device data_usage response."""
    print(f"\n{'=' * 60}")
    print("  Per-Device Data Usage")
    print(f"{'=' * 60}")

    if not result:
        print("  (no data)")
        return

    # The response structure may vary — dump what we get
    if isinstance(result, list):
        for entry in result[:10]:
            name = (entry.get("nickname") or entry.get("hostname")
                    or entry.get("mac", "?"))
            series = entry.get("series", [])
            dl = next((s.get("sum", 0) for s in series if s.get("type") == "download"), 0)
            ul = next((s.get("sum", 0) for s in series if s.get("type") == "upload"), 0)
            print(f"  {name:30s}  DL: {fmt_bytes(dl):>12}  UL: {fmt_bytes(ul):>12}")
        if len(result) > 10:
            print(f"  ... and {len(result) - 10} more devices")
    elif isinstance(result, dict):
        # Might be wrapped
        print(f"  Keys: {list(result.keys())}")
        print(f"  {json.dumps(result, indent=2)[:1000]}")


def compare_with_accumulated(db, network_name: str, today, dl_bytes: float, ul_bytes: float) -> None:
    """Compare data_usage totals against accumulated DailyBandwidth."""
    print(f"\n{'=' * 60}")
    print("  Comparison: data_usage vs accumulated DailyBandwidth")
    print(f"{'=' * 60}")

    # Query accumulated bandwidth for today (network-wide = device_id IS NULL)
    record = (
        db.query(DailyBandwidth)
        .filter(
            DailyBandwidth.network_name == network_name,
            DailyBandwidth.device_id.is_(None),
            DailyBandwidth.date == today,
        )
        .first()
    )

    dl_mb = dl_bytes / 1e6 if dl_bytes else 0
    ul_mb = ul_bytes / 1e6 if ul_bytes else 0

    if record:
        print(f"  {'Source':30s} {'Download':>14s} {'Upload':>14s}")
        print(f"  {'-' * 58}")
        print(f"  {'data_usage endpoint':30s} {fmt_bytes(dl_bytes):>14s} {fmt_bytes(ul_bytes):>14s}")
        print(f"  {'Accumulated (DailyBandwidth)':30s} {fmt_bytes(record.download_mb * 1e6):>14s} {fmt_bytes(record.upload_mb * 1e6):>14s}")

        if record.download_mb > 0:
            ratio = dl_mb / record.download_mb
            print(f"\n  Download ratio (endpoint/accumulated): {ratio:.2f}x")
        if record.upload_mb > 0:
            ratio = ul_mb / record.upload_mb
            print(f"  Upload ratio (endpoint/accumulated):   {ratio:.2f}x")
        print(f"\n  Last collection: {record.updated_at}")
    else:
        print("  No accumulated DailyBandwidth record found for today.")
        print(f"  data_usage endpoint: DL={fmt_bytes(dl_bytes)}  UL={fmt_bytes(ul_bytes)}")


def main():
    print("eero data_usage endpoint test")
    print("=" * 60)

    ensure_data_directory()
    init_database()

    settings = get_settings()
    tz = settings.get_timezone()
    tz_name = str(tz)

    now_local = datetime.now(tz)
    today = now_local.date()

    # Today's window: midnight-to-midnight local time, expressed in UTC
    day_start = datetime(today.year, today.month, today.day, tzinfo=tz)
    day_end = day_start + timedelta(days=1) - timedelta(seconds=1)
    start_utc = day_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_utc = day_end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Week window: last 7 days
    week_start = day_start - timedelta(days=6)
    week_start_utc = week_start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"  Timezone:    {tz_name}")
    print(f"  Today:       {today}")
    print(f"  Day window:  {start_utc} → {end_utc}")
    print(f"  Week window: {week_start_utc} → {end_utc}")

    with get_db_context() as db:
        client = EeroClientWrapper(db)

        if not client.is_authenticated():
            print("\nERROR: Not authenticated. Run cli_auth.py first.")
            sys.exit(1)

        # Get network name for comparison queries
        networks = client.get_networks()
        if not networks:
            print("\nERROR: No networks found.")
            sys.exit(1)
        network_name = networks[0].get("name") if isinstance(networks[0], dict) else networks[0].name
        print(f"  Network:     {network_name}")

        # --- Test 1: Today hourly ---
        print("\n\n>>> Test 1: Today (hourly cadence)")
        result_today = client.get_data_usage(
            start=start_utc, end=end_utc,
            cadence="hourly", timezone_str=tz_name,
        )
        print_series(result_today, "Today — Hourly")

        # --- Test 2: This week daily ---
        print("\n\n>>> Test 2: This week (daily cadence)")
        result_week = client.get_data_usage(
            start=week_start_utc, end=end_utc,
            cadence="daily", timezone_str=tz_name,
        )
        print_series(result_week, "This Week — Daily")

        # --- Test 3: Per-device breakdown for today ---
        print("\n\n>>> Test 3: Per-device breakdown (today, hourly)")
        result_devices = client.get_data_usage_devices(
            start=start_utc, end=end_utc,
            cadence="hourly", timezone_str=tz_name,
        )
        print_device_usage(result_devices)

        # --- Test 4: Compare against accumulated bandwidth ---
        dl_total = 0
        ul_total = 0
        if result_today:
            for s in result_today.get("series", []):
                if s.get("type") == "download":
                    dl_total = s.get("sum", 0)
                elif s.get("type") == "upload":
                    ul_total = s.get("sum", 0)
        compare_with_accumulated(db, network_name, today, dl_total, ul_total)

        # --- Test 5: Stability / live-update check ---
        print("\n\n>>> Test 5: Stability check (3 runs, 30s apart)")
        print("    Checking if data_usage values update in near-real-time...\n")
        runs = []
        for i in range(3):
            if i > 0:
                print(f"  Waiting 30 seconds... ({i}/2)")
                time.sleep(30)

            ts = datetime.now(tz).strftime("%H:%M:%S")
            r = client.get_data_usage(
                start=start_utc, end=end_utc,
                cadence="hourly", timezone_str=tz_name,
            )
            dl = ul = 0
            if r:
                for s in r.get("series", []):
                    if s.get("type") == "download":
                        dl = s.get("sum", 0)
                    elif s.get("type") == "upload":
                        ul = s.get("sum", 0)

            runs.append({"time": ts, "dl": dl, "ul": ul})
            print(f"  Run {i + 1} [{ts}]:  DL={fmt_bytes(dl):>12s}  UL={fmt_bytes(ul):>12s}")

        # Show deltas between runs
        if len(runs) >= 2:
            print(f"\n  {'Interval':20s} {'DL delta':>14s} {'UL delta':>14s}")
            print(f"  {'-' * 48}")
            for i in range(1, len(runs)):
                dl_delta = runs[i]["dl"] - runs[i - 1]["dl"]
                ul_delta = runs[i]["ul"] - runs[i - 1]["ul"]
                label = f"Run {i} → Run {i + 1}"
                print(f"  {label:20s} {fmt_bytes(dl_delta):>14s} {fmt_bytes(ul_delta):>14s}")

            total_dl_delta = runs[-1]["dl"] - runs[0]["dl"]
            total_ul_delta = runs[-1]["ul"] - runs[0]["ul"]
            if total_dl_delta == 0 and total_ul_delta == 0:
                print("\n  ⚠ Values did NOT change between runs — data appears batched, not live.")
            else:
                print(f"\n  ✓ Values changed! Total delta: DL={fmt_bytes(total_dl_delta)}, UL={fmt_bytes(total_ul_delta)}")
                print("    → data_usage updates in near-real-time (or at least within 30s windows)")

    print("\n\nDone.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
    except Exception as e:
        print(f"\nFATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
