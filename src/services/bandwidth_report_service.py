"""Bandwidth summary report service for weekly/monthly usage analysis."""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from src.models.database import DailyBandwidth, Device

logger = logging.getLogger(__name__)


def _get_period_range(
    period: str, offset: int = 0
) -> tuple[date, date, str]:
    """Calculate start/end dates for a period.

    Args:
        period: 'week' or 'month'.
        offset: How many periods back (0=current).

    Returns:
        Tuple of (start_date, end_date, period_label).
    """
    today = date.today()

    if period == "week":
        # Week starts Monday
        current_start = today - timedelta(days=today.weekday())
        start = current_start - timedelta(weeks=offset)
        end = start + timedelta(days=6)
        label = f"{start.isoformat()} to {end.isoformat()}"
    elif period == "month":
        # Go back offset months
        month = today.month - offset
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        start = date(year, month, 1)
        # End of month
        if month == 12:
            end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)
        label = start.strftime("%B %Y")
    else:
        raise ValueError(f"Invalid period: {period}. Must be 'week' or 'month'.")

    return start, end, label


def _mb_to_gb(mb: float) -> float:
    """Convert MB to GB, rounded to 2 decimal places."""
    return round(mb / 1024, 2)


def get_bandwidth_summary(
    db: Session,
    network_name: str,
    period: str = "week",
    offset: int = 0,
) -> Dict[str, Any]:
    """Generate a bandwidth summary report for a given period.

    Args:
        db: Database session.
        network_name: Network to report on.
        period: 'week' or 'month'.
        offset: How many periods back (0=current).

    Returns:
        Summary dict with totals, top devices, daily breakdown, and
        comparison to previous period.
    """
    start, end, label = _get_period_range(period, offset)
    prev_start, prev_end, prev_label = _get_period_range(period, offset + 1)

    # Current period totals
    current_totals = _get_period_totals(db, network_name, start, end)
    prev_totals = _get_period_totals(db, network_name, prev_start, prev_end)

    # Period-over-period change
    change = _compute_change(current_totals, prev_totals)

    # Top devices
    top_devices = _get_top_devices(db, network_name, start, end, limit=10)

    # Daily breakdown
    daily = _get_daily_breakdown(db, network_name, start, end)

    # Peak day
    peak_day = max(daily, key=lambda d: d["total_gb"]) if daily else None

    return {
        "period": label,
        "previous_period": prev_label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "total_download_gb": current_totals["download_gb"],
        "total_upload_gb": current_totals["upload_gb"],
        "total_gb": current_totals["total_gb"],
        "change_vs_previous": change,
        "top_devices": top_devices,
        "daily_breakdown": daily,
        "peak_day": peak_day,
    }


def _get_period_totals(
    db: Session, network_name: str, start: date, end: date
) -> Dict[str, float]:
    """Get total download/upload for a date range."""
    result = (
        db.query(
            func.coalesce(func.sum(DailyBandwidth.download_mb), 0),
            func.coalesce(func.sum(DailyBandwidth.upload_mb), 0),
        )
        .filter(
            DailyBandwidth.network_name == network_name,
            DailyBandwidth.date >= start,
            DailyBandwidth.date <= end,
        )
        .first()
    )

    down_mb = float(result[0])
    up_mb = float(result[1])

    return {
        "download_gb": _mb_to_gb(down_mb),
        "upload_gb": _mb_to_gb(up_mb),
        "total_gb": _mb_to_gb(down_mb + up_mb),
    }


def _compute_change(
    current: Dict[str, float], previous: Dict[str, float]
) -> Dict[str, Optional[float]]:
    """Compute percentage change between periods."""
    def pct(cur: float, prev: float) -> Optional[float]:
        if prev == 0:
            return None
        return round(((cur - prev) / prev) * 100, 1)

    return {
        "download_pct": pct(current["download_gb"], previous["download_gb"]),
        "upload_pct": pct(current["upload_gb"], previous["upload_gb"]),
        "total_pct": pct(current["total_gb"], previous["total_gb"]),
    }


def _get_top_devices(
    db: Session,
    network_name: str,
    start: date,
    end: date,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Get top bandwidth-consuming devices for a period."""
    results = (
        db.query(
            DailyBandwidth.device_id,
            func.sum(DailyBandwidth.download_mb).label("total_down"),
            func.sum(DailyBandwidth.upload_mb).label("total_up"),
        )
        .filter(
            DailyBandwidth.network_name == network_name,
            DailyBandwidth.date >= start,
            DailyBandwidth.date <= end,
            DailyBandwidth.device_id.isnot(None),
        )
        .group_by(DailyBandwidth.device_id)
        .order_by(func.sum(DailyBandwidth.download_mb + DailyBandwidth.upload_mb).desc())
        .limit(limit)
        .all()
    )

    # Get total for percentage calculation
    total_mb = sum(float(r.total_down or 0) + float(r.total_up or 0) for r in results)

    devices = []
    for r in results:
        device = db.query(Device).filter(Device.id == r.device_id).first()
        down_gb = _mb_to_gb(float(r.total_down or 0))
        up_gb = _mb_to_gb(float(r.total_up or 0))
        device_total = float(r.total_down or 0) + float(r.total_up or 0)

        devices.append({
            "device_id": r.device_id,
            "hostname": device.hostname if device else "Unknown",
            "nickname": device.nickname if device else None,
            "mac_address": device.mac_address if device else None,
            "download_gb": down_gb,
            "upload_gb": up_gb,
            "total_gb": _mb_to_gb(device_total),
            "pct_of_total": round((device_total / total_mb * 100), 1) if total_mb > 0 else 0,
        })

    return devices


def _get_daily_breakdown(
    db: Session, network_name: str, start: date, end: date
) -> List[Dict[str, Any]]:
    """Get per-day bandwidth breakdown."""
    results = (
        db.query(
            DailyBandwidth.date,
            func.sum(DailyBandwidth.download_mb).label("total_down"),
            func.sum(DailyBandwidth.upload_mb).label("total_up"),
        )
        .filter(
            DailyBandwidth.network_name == network_name,
            DailyBandwidth.date >= start,
            DailyBandwidth.date <= end,
        )
        .group_by(DailyBandwidth.date)
        .order_by(DailyBandwidth.date.asc())
        .all()
    )

    days = []
    for r in results:
        d = r.date if isinstance(r.date, date) else date.fromisoformat(str(r.date))
        down_gb = _mb_to_gb(float(r.total_down or 0))
        up_gb = _mb_to_gb(float(r.total_up or 0))
        days.append({
            "date": d.isoformat(),
            "day": d.strftime("%A"),
            "download_gb": down_gb,
            "upload_gb": up_gb,
            "total_gb": _mb_to_gb(float(r.total_down or 0) + float(r.total_up or 0)),
        })

    return days
