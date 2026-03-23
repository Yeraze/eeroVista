"""Device activity pattern analysis service.

Builds 7x24 heatmaps showing when devices are typically online.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.database import Device, DeviceConnection

logger = logging.getLogger(__name__)


def get_activity_pattern(
    db: Session,
    mac_address: str,
    network_name: str,
    days: int = 7,
) -> Dict[str, Any]:
    """Get activity heatmap for a device.

    Builds a 7 (day-of-week) x 24 (hour) matrix of connection probability.

    Args:
        db: Database session.
        mac_address: Device MAC address.
        network_name: Network name.
        days: Number of days to analyze (default 7).

    Returns:
        Dict with heatmap matrix and anomaly flags.
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

    readings = (
        db.query(
            DeviceConnection.timestamp,
            DeviceConnection.is_connected,
        )
        .filter(
            DeviceConnection.device_id == device.id,
            DeviceConnection.timestamp >= cutoff,
        )
        .order_by(DeviceConnection.timestamp.asc())
        .all()
    )

    if not readings:
        return {
            "mac": mac_address,
            "hostname": device.hostname,
            "heatmap": _empty_heatmap(),
            "total_readings": 0,
            "period_days": days,
        }

    # Build heatmap: count connected / total per (day_of_week, hour)
    buckets: Dict[tuple, Dict[str, int]] = {}
    for dow in range(7):
        for hour in range(24):
            buckets[(dow, hour)] = {"connected": 0, "total": 0}

    for r in readings:
        ts = r.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        dow = ts.weekday()
        hour = ts.hour
        buckets[(dow, hour)]["total"] += 1
        if r.is_connected:
            buckets[(dow, hour)]["connected"] += 1

    # Convert to probability matrix
    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    heatmap = []
    for dow in range(7):
        row = []
        for hour in range(24):
            b = buckets[(dow, hour)]
            prob = round(b["connected"] / b["total"], 2) if b["total"] > 0 else None
            row.append(prob)
        heatmap.append({
            "day": days_of_week[dow],
            "hours": row,
        })

    return {
        "mac": mac_address,
        "hostname": device.hostname,
        "heatmap": heatmap,
        "total_readings": len(readings),
        "period_days": days,
    }


def _empty_heatmap() -> List[Dict[str, Any]]:
    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    return [{"day": d, "hours": [None] * 24} for d in days_of_week]
