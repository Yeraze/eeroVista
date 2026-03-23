"""Bandwidth utilization heatmap service.

Builds a 7-day-of-week x 288-bucket (5-minute intervals) heatmap showing
peak download/upload bandwidth for a device, aggregated across weeks.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import get_settings
from src.models.database import Device, DeviceConnection

logger = logging.getLogger(__name__)

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
BUCKETS_PER_DAY = 288  # 24 * 12 (5-minute buckets)


def get_bandwidth_heatmap(
    db: Session,
    mac_address: str,
    network_name: str,
    days: int = 7,
) -> Dict[str, Any]:
    """Get bandwidth utilization heatmap for a device.

    Returns 7 rows (Mon-Sun), each with 288 five-minute buckets showing
    the peak download/upload Mbps, aggregated across all matching days.

    Args:
        db: Database session.
        mac_address: Device MAC address.
        network_name: Network name.
        days: Number of days of data to include (default 7).

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

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Group by (day_of_week, 5-min bucket) in local time
    # SQLite %w: 0=Sunday, 1=Monday, ..., 6=Saturday
    results = db.execute(text("""
        SELECT
            CAST(strftime('%w', datetime(timestamp, :offset)) AS INTEGER) as dow,
            (CAST(strftime('%H', datetime(timestamp, :offset)) AS INTEGER) * 12
             + CAST(strftime('%M', datetime(timestamp, :offset)) AS INTEGER) / 5) as bucket,
            MAX(COALESCE(bandwidth_down_mbps, 0)) as max_down,
            MAX(COALESCE(bandwidth_up_mbps, 0)) as max_up
        FROM device_connections
        WHERE device_id = :device_id
          AND timestamp >= :cutoff
          AND is_connected = 1
        GROUP BY dow, bucket
        ORDER BY dow, bucket
    """), {
        "device_id": device.id,
        "cutoff": cutoff,
        "offset": f"{utc_offset_seconds} seconds",
    }).fetchall()

    if not results:
        return {
            "mac": mac_address,
            "hostname": device.hostname,
            "days": _empty_heatmap(),
            "max_down_mbps": 0,
            "max_up_mbps": 0,
            "period_days": days,
            "bucket_minutes": 5,
        }

    # SQLite dow -> Python weekday mapping
    # SQLite %w: 0=Sunday, 1=Monday ... 6=Saturday
    # Python:    0=Monday ... 6=Sunday
    sqlite_to_python_dow = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}

    # Build lookup: (python_dow, bucket) -> (max_down, max_up)
    data = {}
    global_max_down = 0
    global_max_up = 0

    for row in results:
        sqlite_dow = int(row[0])
        bucket = int(row[1])
        max_down = float(row[2])
        max_up = float(row[3])
        python_dow = sqlite_to_python_dow[sqlite_dow]
        data[(python_dow, bucket)] = (max_down, max_up)
        if max_down > global_max_down:
            global_max_down = max_down
        if max_up > global_max_up:
            global_max_up = max_up

    # Build 7 day-of-week rows
    heatmap_days = []
    for dow in range(7):
        buckets = []
        for b in range(BUCKETS_PER_DAY):
            entry = data.get((dow, b))
            if entry and (entry[0] > 0 or entry[1] > 0):
                buckets.append({
                    "down": round(entry[0], 1),
                    "up": round(entry[1], 1),
                })
            else:
                buckets.append(None)

        heatmap_days.append({
            "day": DAYS_OF_WEEK[dow],
            "label": DAYS_OF_WEEK[dow][:3],
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


def _empty_heatmap() -> List[Dict[str, Any]]:
    return [
        {"day": d, "label": d[:3], "buckets": [None] * BUCKETS_PER_DAY}
        for d in DAYS_OF_WEEK
    ]
