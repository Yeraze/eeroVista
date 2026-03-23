"""Speedtest performance trends analysis service."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from src.config import get_settings
from src.models.database import Speedtest

logger = logging.getLogger(__name__)

DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def get_speedtest_analysis(
    db: Session,
    network_name: str,
    days: int = 30,
) -> Dict[str, Any]:
    """Analyze speedtest performance trends.

    Args:
        db: Database session.
        network_name: Network name.
        days: Number of days to analyze.

    Returns:
        Dict with averages, time-of-day patterns, day-of-week patterns,
        and trend assessment.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    tests = (
        db.query(Speedtest)
        .filter(
            Speedtest.network_name == network_name,
            Speedtest.timestamp >= cutoff,
        )
        .order_by(Speedtest.timestamp.asc())
        .all()
    )

    if not tests:
        return {
            "period_days": days,
            "test_count": 0,
            "avg_download_mbps": None,
            "avg_upload_mbps": None,
            "avg_latency_ms": None,
            "time_of_day_pattern": [],
            "day_of_week_pattern": [],
            "trend": "unknown",
        }

    # Overall averages
    downloads = [t.download_mbps for t in tests if t.download_mbps is not None]
    uploads = [t.upload_mbps for t in tests if t.upload_mbps is not None]
    latencies = [t.latency_ms for t in tests if t.latency_ms is not None]

    avg_down = round(sum(downloads) / len(downloads), 1) if downloads else None
    avg_up = round(sum(uploads) / len(uploads), 1) if uploads else None
    avg_lat = round(sum(latencies) / len(latencies), 1) if latencies else None

    # Convert timestamps to local time for time-of-day/day-of-week patterns
    settings = get_settings()
    tz = settings.get_timezone()

    # Time-of-day pattern (hourly buckets in local time)
    hourly = {}
    for t in tests:
        if t.download_mbps is not None:
            local_ts = t.timestamp.replace(tzinfo=timezone.utc).astimezone(tz) if t.timestamp.tzinfo is None else t.timestamp.astimezone(tz)
            hour = local_ts.hour
            hourly.setdefault(hour, []).append(t.download_mbps)

    time_of_day = [
        {
            "hour": h,
            "avg_download": round(sum(vals) / len(vals), 1),
            "test_count": len(vals),
        }
        for h, vals in sorted(hourly.items())
    ]

    # Day-of-week pattern (in local time)
    daily = {}
    for t in tests:
        if t.download_mbps is not None:
            local_ts = t.timestamp.replace(tzinfo=timezone.utc).astimezone(tz) if t.timestamp.tzinfo is None else t.timestamp.astimezone(tz)
            dow = local_ts.weekday()
            daily.setdefault(dow, []).append(t.download_mbps)

    day_of_week = [
        {
            "day": DAYS_OF_WEEK[dow],
            "avg_download": round(sum(vals) / len(vals), 1),
            "test_count": len(vals),
        }
        for dow, vals in sorted(daily.items())
    ]

    # Trend: compare first half vs second half of the period
    trend = "stable"
    if len(downloads) >= 4:
        mid = len(downloads) // 2
        first_half_avg = sum(downloads[:mid]) / mid
        second_half_avg = sum(downloads[mid:]) / (len(downloads) - mid)
        pct_change = ((second_half_avg - first_half_avg) / first_half_avg) * 100

        if pct_change < -10:
            trend = "degrading"
        elif pct_change > 10:
            trend = "improving"

    return {
        "period_days": days,
        "test_count": len(tests),
        "avg_download_mbps": avg_down,
        "avg_upload_mbps": avg_up,
        "avg_latency_ms": avg_lat,
        "time_of_day_pattern": time_of_day,
        "day_of_week_pattern": day_of_week,
        "trend": trend,
    }
