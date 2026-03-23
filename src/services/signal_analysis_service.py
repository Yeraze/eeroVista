"""Signal quality analysis service for per-device signal trends."""

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func
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

    readings = (
        db.query(
            DeviceConnection.timestamp,
            DeviceConnection.signal_strength,
        )
        .filter(
            DeviceConnection.device_id == device.id,
            DeviceConnection.timestamp >= cutoff,
            DeviceConnection.signal_strength.isnot(None),
            DeviceConnection.is_connected == True,
        )
        .order_by(DeviceConnection.timestamp.asc())
        .all()
    )

    if not readings:
        return {
            "mac": mac_address,
            "hostname": device.hostname,
            "stats": None,
            "quality_band": None,
            "trend": "unknown",
            "history": [],
        }

    signals = [r.signal_strength for r in readings]
    mean_val = sum(signals) / len(signals)
    min_val = min(signals)
    max_val = max(signals)
    variance = sum((s - mean_val) ** 2 for s in signals) / len(signals)
    stddev = math.sqrt(variance)

    # Trend: compare last 24h avg vs previous 24h avg
    now = datetime.now(timezone.utc)
    recent_cutoff = now - timedelta(hours=24)
    prev_cutoff = now - timedelta(hours=48)

    def _make_aware(ts: datetime) -> datetime:
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts

    recent_signals = [r.signal_strength for r in readings if _make_aware(r.timestamp) >= recent_cutoff]
    prev_signals = [
        r.signal_strength for r in readings
        if prev_cutoff <= _make_aware(r.timestamp) < recent_cutoff
    ]

    trend = "stable"
    if recent_signals and prev_signals:
        recent_avg = sum(recent_signals) / len(recent_signals)
        prev_avg = sum(prev_signals) / len(prev_signals)
        diff = recent_avg - prev_avg
        if diff < -5:
            trend = "degrading"
        elif diff > 5:
            trend = "improving"

    # Downsample history for the response (max ~500 points)
    step = max(1, len(readings) // 500)
    history = [
        {
            "timestamp": r.timestamp.isoformat(),
            "signal_strength": r.signal_strength,
        }
        for i, r in enumerate(readings) if i % step == 0
    ]

    return {
        "mac": mac_address,
        "hostname": device.hostname,
        "stats": {
            "mean": round(mean_val, 1),
            "min": min_val,
            "max": max_val,
            "stddev": round(stddev, 1),
            "count": len(signals),
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
