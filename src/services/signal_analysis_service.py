"""Signal quality analysis service for per-device signal trends."""

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func, text
from sqlalchemy.orm import Session

from src.models.database import Device, DeviceConnection

logger = logging.getLogger(__name__)

# Quality bands
QUALITY_BANDS = [
    ("excellent", -50),   # > -50 dBm
    ("good", -65),        # -50 to -65
    ("fair", -75),        # -65 to -75
    ("poor", float("-inf")),  # < -75
]


def _classify_signal(dbm: float) -> str:
    """Classify signal strength into a quality band."""
    for band, threshold in QUALITY_BANDS:
        if dbm >= threshold:
            return band
    return "poor"


def get_signal_history(
    db: Session,
    mac_address: str,
    network_name: str,
    hours: int = 168,
) -> Dict[str, Any]:
    """Get signal strength history and statistics for a device.

    Args:
        db: Database session.
        mac_address: Device MAC address.
        network_name: Network name.
        hours: Hours to look back (default 7 days).

    Returns:
        Dict with stats, quality band, trend, and time-series history.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

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

    # Use SQL for stats — avoid loading all rows
    base_filter = [
        DeviceConnection.device_id == device.id,
        DeviceConnection.timestamp >= cutoff,
        DeviceConnection.signal_strength.isnot(None),
        DeviceConnection.is_connected == True,
    ]

    stats_row = (
        db.query(
            func.avg(DeviceConnection.signal_strength).label('mean'),
            func.min(DeviceConnection.signal_strength).label('min'),
            func.max(DeviceConnection.signal_strength).label('max'),
            func.count(DeviceConnection.signal_strength).label('count'),
        )
        .filter(*base_filter)
        .first()
    )

    if not stats_row or not stats_row.count or stats_row.count == 0:
        return {
            "mac": mac_address,
            "hostname": device.hostname,
            "stats": None,
            "quality_band": None,
            "trend": "unknown",
            "history": [],
        }

    mean_val = float(stats_row.mean)
    min_val = int(stats_row.min)
    max_val = int(stats_row.max)
    count = int(stats_row.count)

    # Stddev via SQL (SQLite doesn't have built-in STDDEV, compute from variance)
    var_row = (
        db.query(
            func.avg(
                (DeviceConnection.signal_strength - mean_val)
                * (DeviceConnection.signal_strength - mean_val)
            ).label('variance')
        )
        .filter(*base_filter)
        .first()
    )
    stddev = math.sqrt(float(var_row.variance)) if var_row and var_row.variance else 0

    # Trend: compare last 24h avg vs previous 24h avg using SQL
    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(hours=24)
    prev_cutoff = now - timedelta(hours=48)

    recent_avg_row = (
        db.query(func.avg(DeviceConnection.signal_strength))
        .filter(
            DeviceConnection.device_id == device.id,
            DeviceConnection.timestamp >= recent_cutoff,
            DeviceConnection.signal_strength.isnot(None),
            DeviceConnection.is_connected == True,
        )
        .scalar()
    )

    prev_avg_row = (
        db.query(func.avg(DeviceConnection.signal_strength))
        .filter(
            DeviceConnection.device_id == device.id,
            DeviceConnection.timestamp >= prev_cutoff,
            DeviceConnection.timestamp < recent_cutoff,
            DeviceConnection.signal_strength.isnot(None),
            DeviceConnection.is_connected == True,
        )
        .scalar()
    )

    trend = "stable"
    if recent_avg_row is not None and prev_avg_row is not None:
        diff = float(recent_avg_row) - float(prev_avg_row)
        if diff < -5:
            trend = "degrading"
        elif diff > 5:
            trend = "improving"

    # Fetch downsampled history — use SQL to pick every Nth row
    # Get ~300 evenly spaced points
    target_points = 300
    step = max(1, count // target_points)

    # Use ROW_NUMBER to downsample
    # rn starts at 1; use (rn - 1) % step = 0 to include first row and every Nth after
    history_rows = db.execute(text("""
        SELECT timestamp, signal_strength FROM (
            SELECT timestamp, signal_strength,
                   ROW_NUMBER() OVER (ORDER BY timestamp) as rn
            FROM device_connections
            WHERE device_id = :device_id
              AND timestamp >= :cutoff
              AND signal_strength IS NOT NULL
              AND is_connected = 1
        ) WHERE (rn - 1) % :step = 0
        ORDER BY timestamp
    """), {"device_id": device.id, "cutoff": cutoff, "step": step}).fetchall()

    history = [
        {"timestamp": str(r[0]), "signal_strength": r[1]}
        for r in history_rows
    ]

    return {
        "mac": mac_address,
        "hostname": device.hostname,
        "stats": {
            "mean": round(mean_val, 1),
            "min": min_val,
            "max": max_val,
            "stddev": round(stddev, 1),
            "count": count,
        },
        "quality_band": _classify_signal(mean_val),
        "trend": trend,
        "history": history,
    }


def get_signal_summary(
    db: Session,
    network_name: str,
) -> Dict[str, Any]:
    """Get signal quality summary for all devices on a network.

    Returns counts by quality band and list of degrading devices.
    """
    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_48h = now - timedelta(hours=48)

    devices = (
        db.query(Device)
        .filter(Device.network_name == network_name)
        .all()
    )

    band_counts = {"excellent": 0, "good": 0, "fair": 0, "poor": 0}
    degrading = []

    for device in devices:
        # Get average signal in last 24h
        avg_signal = (
            db.query(func.avg(DeviceConnection.signal_strength))
            .filter(
                DeviceConnection.device_id == device.id,
                DeviceConnection.timestamp >= cutoff_24h,
                DeviceConnection.signal_strength.isnot(None),
                DeviceConnection.is_connected == True,
            )
            .scalar()
        )

        if avg_signal is None:
            continue

        avg_signal = float(avg_signal)
        band = _classify_signal(avg_signal)
        band_counts[band] += 1

        # Check for degradation
        prev_avg = (
            db.query(func.avg(DeviceConnection.signal_strength))
            .filter(
                DeviceConnection.device_id == device.id,
                DeviceConnection.timestamp >= cutoff_48h,
                DeviceConnection.timestamp < cutoff_24h,
                DeviceConnection.signal_strength.isnot(None),
                DeviceConnection.is_connected == True,
            )
            .scalar()
        )

        if prev_avg is not None and avg_signal - float(prev_avg) < -5:
            degrading.append({
                "mac": device.mac_address,
                "hostname": device.hostname,
                "current_avg": round(avg_signal, 1),
                "previous_avg": round(float(prev_avg), 1),
                "change": round(avg_signal - float(prev_avg), 1),
            })

    return {
        "band_counts": band_counts,
        "degrading_devices": degrading,
        "total_wireless_devices": sum(band_counts.values()),
    }
