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
    """Count total and online WAN status readings in a window.

    Also accounts for data gaps > GAP_THRESHOLD_MINUTES as downtime.
    When the WAN is down, the collector can't reach the eero API,
    so outages appear as gaps in readings rather than offline status values.
    """
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

    # Account for data gaps as downtime.
    # Each gap > threshold represents missed readings that would have been
    # collected if WAN was up. Estimate how many readings were missed.
    gap_outages = _detect_gap_outages(db, network_name, start, end)
    if gap_outages and total > 0:
        # Estimate collection interval from actual data
        window_seconds = (end - start).total_seconds()
        avg_interval = window_seconds / total if total > 0 else 60

        missed_readings = 0
        for gap in gap_outages:
            missed_readings += int(gap["duration_seconds"] / avg_interval)

        total += missed_readings
        # missed readings count as NOT online

    return total, online


# Gap detection uses a multiplier of the average collection interval.
# If the gap between two readings exceeds AVG_INTERVAL * GAP_MULTIPLIER,
# it's treated as an outage (collector couldn't reach the eero API).
GAP_MULTIPLIER = 3


def detect_outages(
    db: Session,
    network_name: str,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Detect WAN outage events from offline readings AND data gaps.

    Outages are detected two ways:
    1. Consecutive wan_status != 'online'/'connected' readings
    2. Gaps > GAP_THRESHOLD_SECONDS between readings (collector couldn't
       reach the cloud API because WAN was down)

    Returns list of outage events with start, end, and duration.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Status-based outages (original logic)
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
                "type": "status",
            })
            outage_start = None

    # Handle ongoing status-based outage
    if outage_start is not None:
        now = datetime.now(timezone.utc)
        if outage_start.tzinfo is None:
            outage_start = outage_start.replace(tzinfo=timezone.utc)
        duration = (now - outage_start).total_seconds() / 60
        outages.append({
            "start": outage_start.isoformat(),
            "end": None,
            "duration_minutes": round(duration, 1),
            "ongoing": True,
            "type": "status",
        })

    # Gap-based outages
    gap_outages = _detect_gap_outages(db, network_name, cutoff, datetime.now(timezone.utc))
    for gap in gap_outages:
        outages.append({
            "start": gap["start"],
            "end": gap["end"],
            "duration_minutes": round(gap["duration_seconds"] / 60, 1),
            "type": "gap",
        })

    # Sort by start time and deduplicate overlapping outages
    outages.sort(key=lambda o: o["start"])

    return outages


def _detect_gap_outages(
    db: Session,
    network_name: str,
    start: datetime,
    end: datetime,
) -> List[Dict[str, Any]]:
    """Detect outages from gaps in data collection.

    When WAN is down, the collector can't reach the eero cloud API,
    resulting in gaps between readings. The threshold is dynamically
    computed as GAP_MULTIPLIER * median interval between readings.
    """
    from sqlalchemy import text

    rows = db.execute(text("""
        SELECT timestamp,
               LAG(timestamp) OVER (ORDER BY timestamp) as prev_ts
        FROM network_metrics
        WHERE network_name = :network
          AND timestamp >= :start
          AND timestamp <= :end
        ORDER BY timestamp
    """), {"network": network_name, "start": start, "end": end}).fetchall()

    # Compute all intervals to find the median (typical collection interval)
    intervals = []
    parsed_rows = []
    for row in rows:
        if row[1] is None:
            continue
        curr_ts = row[0]
        prev_ts = row[1]
        if isinstance(curr_ts, str):
            curr_ts = datetime.fromisoformat(curr_ts)
        if isinstance(prev_ts, str):
            prev_ts = datetime.fromisoformat(prev_ts)
        # Ensure both are timezone-aware (SQLite returns naive datetimes)
        if curr_ts.tzinfo is None:
            curr_ts = curr_ts.replace(tzinfo=timezone.utc)
        if prev_ts.tzinfo is None:
            prev_ts = prev_ts.replace(tzinfo=timezone.utc)
        gap = (curr_ts - prev_ts).total_seconds()
        intervals.append(gap)
        parsed_rows.append((prev_ts, curr_ts, gap))

    if not intervals:
        return []

    # Use median interval as the baseline (robust against outliers)
    sorted_intervals = sorted(intervals)
    median_interval = sorted_intervals[len(sorted_intervals) // 2]
    threshold = median_interval * GAP_MULTIPLIER

    gaps = []
    for prev_ts, curr_ts, gap_seconds in parsed_rows:
        if gap_seconds > threshold:
            gaps.append({
                "start": prev_ts.isoformat(),
                "end": curr_ts.isoformat(),
                "duration_seconds": gap_seconds,
            })

    return gaps


def _ensure_aware(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (assume UTC if naive)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


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

    # Pre-fetch outages once instead of per-day
    outages = detect_outages(db, network_name, days=days)

    for d in range(days - 1, -1, -1):
        day = today - timedelta(days=d)
        day_start = datetime.combine(day, datetime.min.time()).replace(tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)

        total, online = _count_wan_status(db, network_name, day_start, day_end)
        pct = round(online / total * 100, 2) if total > 0 else None

        # Count outages that overlap this day
        day_outages = 0
        for o in outages:
            o_start = _ensure_aware(datetime.fromisoformat(o["start"]))
            o_end = _ensure_aware(datetime.fromisoformat(o["end"])) if o.get("end") else datetime.now(timezone.utc)
            if o_start < day_end and o_end > day_start:
                day_outages += 1

        daily.append({
            "date": day.isoformat(),
            "uptime_pct": pct,
            "outage_count": day_outages,
        })

    return daily
