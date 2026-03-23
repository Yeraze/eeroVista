"""Device activity pattern analysis service.

Builds 7x24 heatmaps showing when devices are typically online.
Uses SQL aggregation to avoid loading all readings into memory.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import case, cast, func, Integer, text
from sqlalchemy.orm import Session

from src.config import get_settings
from src.models.database import Device, DeviceConnection

logger = logging.getLogger(__name__)

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def get_activity_pattern(
    db: Session,
    mac_address: str,
    network_name: str,
    days: int = 7,
) -> Dict[str, Any]:
    """Get activity heatmap for a device using SQL aggregation.

    Builds a 7 (day-of-week) x 24 (hour) matrix of connection probability.
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

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Compute UTC offset for configured timezone so SQL groups by local time
    settings = get_settings()
    tz = settings.get_timezone()
    utc_offset_seconds = datetime.now(tz).utcoffset().total_seconds()
    offset_str = f"{int(utc_offset_seconds)} seconds"

    # Use SQL to count readings per (day_of_week, hour) bucket in local time.
    # We normalize against the max readings in any bucket for this device.
    local_ts = func.datetime(DeviceConnection.timestamp, text(f"'{offset_str}'"))
    results = (
        db.query(
            func.strftime('%w', local_ts).label('dow'),
            func.strftime('%H', local_ts).label('hour'),
            func.count().label('total'),
            func.sum(
                case(
                    (DeviceConnection.is_connected == True, 1),
                    else_=0
                )
            ).label('connected'),
        )
        .filter(
            DeviceConnection.device_id == device.id,
            DeviceConnection.timestamp >= cutoff,
        )
        .group_by('dow', 'hour')
        .all()
    )

    if not results:
        return {
            "mac": mac_address,
            "hostname": device.hostname,
            "heatmap": _empty_heatmap(),
            "total_readings": 0,
            "period_days": days,
        }

    # SQLite %w: 0=Sunday, 1=Monday, ..., 6=Saturday
    # Convert to Python weekday: 0=Monday, ..., 6=Sunday
    sqlite_to_python_dow = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}

    # First pass: collect raw connected counts and find the max per-hour count
    raw_data = {}
    total_readings = 0
    max_connected = 1
    for row in results:
        sqlite_dow = int(row.dow)
        hour = int(row.hour)
        python_dow = sqlite_to_python_dow[sqlite_dow]
        connected = int(row.connected)
        total = int(row.total)
        total_readings += total
        raw_data[(python_dow, hour)] = connected
        if connected > max_connected:
            max_connected = connected

    # Second pass: normalize against max to get meaningful variation
    # This shows relative activity: 1.0 = most active hour, 0.0 = no activity
    probabilities = {}
    for key, connected in raw_data.items():
        probabilities[key] = round(connected / max_connected, 2)

    # Build heatmap matrix
    heatmap = []
    for dow in range(7):
        row = []
        for hour in range(24):
            row.append(probabilities.get((dow, hour)))
        heatmap.append({
            "day": DAYS_OF_WEEK[dow],
            "hours": row,
        })

    return {
        "mac": mac_address,
        "hostname": device.hostname,
        "heatmap": heatmap,
        "total_readings": total_readings,
        "period_days": days,
    }


def _empty_heatmap() -> List[Dict[str, Any]]:
    return [{"day": d, "hours": [None] * 24} for d in DAYS_OF_WEEK]
