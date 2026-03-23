"""ISP reliability tracking service.

Analyzes WAN status history to calculate uptime percentages,
detect outage events, and provide daily uptime breakdowns.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from src.models.database import NetworkMetric

logger = logging.getLogger(__name__)


def get_uptime_stats(
    db: Session,
    network_name: str,
) -> Dict[str, Any]:
    """Calculate WAN uptime percentages for standard windows.

    Returns uptime % for 24h, 7d, and 30d windows.
    """
    now = datetime.now(timezone.utc)

    windows = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }

    stats = {}
    for label, delta in windows.items():
        cutoff = now - delta
        total, online = _count_wan_status(db, network_name, cutoff, now)
        pct = round(online / total * 100, 2) if total > 0 else None
        stats[f"uptime_{label}_pct"] = pct

    # 30-day outage summary
    outages = detect_outages(db, network_name, days=30)
    total_downtime = sum(o["duration_minutes"] for o in outages)
    longest = max((o["duration_minutes"] for o in outages), default=0)

    stats["total_outages_30d"] = len(outages)
    stats["total_downtime_minutes_30d"] = round(total_downtime, 1)
    stats["longest_outage_minutes"] = round(longest, 1)

    return stats


def _count_wan_status(
    db: Session,
    network_name: str,
    start: datetime,
    end: datetime,
) -> tuple[int, int]:
    """Count total and online WAN status readings in a window."""
    total = (
        db.query(func.count())
        .select_from(NetworkMetric)
        .filter(
            NetworkMetric.network_name == network_name,
            NetworkMetric.timestamp >= start,
            NetworkMetric.timestamp <= end,
            NetworkMetric.wan_status.isnot(None),
        )
        .scalar()
    ) or 0

    online = (
        db.query(func.count())
        .select_from(NetworkMetric)
        .filter(
            NetworkMetric.network_name == network_name,
            NetworkMetric.timestamp >= start,
            NetworkMetric.timestamp <= end,
            NetworkMetric.wan_status.in_(["connected", "online"]),
        )
        .scalar()
    ) or 0

    return total, online


def detect_outages(
    db: Session,
    network_name: str,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Detect WAN outage events from consecutive offline readings.

    An outage starts when wan_status != 'connected' and ends when
    wan_status == 'connected' resumes.

    Returns list of outage events with start, end, and duration.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    readings = (
        db.query(NetworkMetric.timestamp, NetworkMetric.wan_status)
        .filter(
            NetworkMetric.network_name == network_name,
            NetworkMetric.timestamp >= cutoff,
            NetworkMetric.wan_status.isnot(None),
        )
        .order_by(NetworkMetric.timestamp.asc())
        .all()
    )

    outages = []
    outage_start = None

    for reading in readings:
        is_online = reading.wan_status in ("connected", "online")

        if not is_online and outage_start is None:
            outage_start = reading.timestamp
        elif is_online and outage_start is not None:
            duration = (reading.timestamp - outage_start).total_seconds() / 60
            outages.append({
                "start": outage_start.isoformat(),
                "end": reading.timestamp.isoformat(),
                "duration_minutes": round(duration, 1),
            })
            outage_start = None

    # Handle ongoing outage
    if outage_start is not None:
        now = datetime.now(timezone.utc)
        # Ensure timezone-aware comparison
        if outage_start.tzinfo is None:
            outage_start = outage_start.replace(tzinfo=timezone.utc)
        duration = (now - outage_start).total_seconds() / 60
        outages.append({
            "start": outage_start.isoformat(),
            "end": None,
            "duration_minutes": round(duration, 1),
            "ongoing": True,
        })

    return outages


def get_daily_uptime(
    db: Session,
    network_name: str,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Get per-day uptime percentages for a calendar heatmap.

    Returns list of {date, uptime_pct, outage_count} dicts.
    """
    today = date.today()
    daily = []

    for d in range(days - 1, -1, -1):
        day = today - timedelta(days=d)
        day_start = datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        total, online = _count_wan_status(db, network_name, day_start, day_end)
        pct = round(online / total * 100, 2) if total > 0 else None

        # Count outages that overlap this day
        outages = detect_outages(db, network_name, days=days)
        day_outages = 0
        for o in outages:
            o_start = datetime.fromisoformat(o["start"])
            o_end = datetime.fromisoformat(o["end"]) if o.get("end") else datetime.now(timezone.utc)
            if o_start < day_end and o_end > day_start:
                day_outages += 1

        daily.append({
            "date": day.isoformat(),
            "uptime_pct": pct,
            "outage_count": day_outages,
        })

    return daily
