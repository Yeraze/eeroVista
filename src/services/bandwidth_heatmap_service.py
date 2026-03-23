"""Bandwidth utilization heatmap service.

Builds a 7-day x 288-bucket (5-minute intervals) heatmap showing
peak download/upload bandwidth for a device.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.config import get_settings
from src.models.database import Device, DeviceConnection

logger = logging.getLogger(__name__)

BUCKETS_PER_HOUR = 12  # 60 / 5 = 12 five-minute buckets
BUCKETS_PER_DAY = 24 * BUCKETS_PER_HOUR  # 288


def get_bandwidth_heatmap(
    db: Session,
    mac_address: str,
    network_name: str,
    days: int = 7,
) -> Dict[str, Any]:
    """Get bandwidth utilization heatmap for a device.

    Returns a list of day rows, each containing 288 five-minute buckets
    with peak download/upload Mbps values.

    Args:
        db: Database session.
        mac_address: Device MAC address.
        network_name: Network name.
        days: Number of days to show (default 7).

    Returns:
        Dict with heatmap data, max values for color scaling, and metadata.
    """
    device = (
        db.query(Device)
        .filter(
            Device.mac_address == mac_address,
            Device.network_name == network_name,
        )
        .first()
    )
    if not device:
        return {"error": "Device not found"}

    # Compute timezone offset for local time grouping
    settings = get_settings()
    tz = settings.get_timezone()
    utc_offset_seconds = int(datetime.now(tz).utcoffset().total_seconds())
    offset_str = f"{utc_offset_seconds} seconds"

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Query: group by (date, 5-min bucket) in local time, get max bandwidth
    # SQLite: strftime('%Y-%m-%d', ts, offset) for date
    # 5-min bucket = (hour * 12) + (minute / 5)
    local_ts = func.datetime(DeviceConnection.timestamp, text(f"'{offset_str}'"))

    results = db.execute(text("""
        SELECT
            strftime('%Y-%m-%d', datetime(timestamp, :offset)) as day,
            (CAST(strftime('%H', datetime(timestamp, :offset)) AS INTEGER) * 12
             + CAST(strftime('%M', datetime(timestamp, :offset)) AS INTEGER) / 5) as bucket,
            MAX(COALESCE(bandwidth_down_mbps, 0)) as max_down,
            MAX(COALESCE(bandwidth_up_mbps, 0)) as max_up
        FROM device_connections
        WHERE device_id = :device_id
          AND timestamp >= :cutoff
          AND is_connected = 1
        GROUP BY day, bucket
        ORDER BY day, bucket
    """), {
        "device_id": device.id,
        "cutoff": cutoff,
        "offset": f"{utc_offset_seconds} seconds",
    }).fetchall()

    if not results:
        return {
            "mac": mac_address,
            "hostname": device.hostname,
            "days": [],
            "max_down_mbps": 0,
            "max_up_mbps": 0,
            "period_days": days,
            "bucket_minutes": 5,
        }

    # Build lookup: (date_str, bucket) -> (max_down, max_up)
    data = {}
    global_max_down = 0
    global_max_up = 0
    dates_seen = set()

    for row in results:
        day_str = row[0]
        bucket = int(row[1])
        max_down = float(row[2])
        max_up = float(row[3])
        dates_seen.add(day_str)
        data[(day_str, bucket)] = (max_down, max_up)
        if max_down > global_max_down:
            global_max_down = max_down
        if max_up > global_max_up:
            global_max_up = max_up

    # Build day rows sorted by date
    sorted_dates = sorted(dates_seen)
    # Limit to the most recent `days` entries
    sorted_dates = sorted_dates[-days:]

    heatmap_days = []
    for date_str in sorted_dates:
        from datetime import date as date_type
        d = date_type.fromisoformat(date_str)
        day_name = d.strftime("%A")
        short_name = d.strftime("%a %m/%d")

        buckets = []
        for b in range(BUCKETS_PER_DAY):
            entry = data.get((date_str, b))
            if entry:
                buckets.append({
                    "down": round(entry[0], 1),
                    "up": round(entry[1], 1),
                })
            else:
                buckets.append(None)

        heatmap_days.append({
            "date": date_str,
            "label": short_name,
            "day": day_name,
            "buckets": buckets,
        })

    return {
        "mac": mac_address,
        "hostname": device.hostname,
        "days": heatmap_days,
        "max_down_mbps": round(global_max_down, 1),
        "max_up_mbps": round(global_max_up, 1),
        "period_days": days,
        "bucket_minutes": 5,
    }
