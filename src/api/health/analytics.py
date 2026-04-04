"""Analytics, bandwidth, and health score API endpoints."""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.eero_client import EeroClientWrapper
from src.utils.database import get_db_context

from .models import (
    CACHE_TTL_SECONDS,
    _bandwidth_cache,
    get_eero_client,
    get_network_name_filter,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/nodes/{eero_id}/restart-history")
async def get_node_restart_history(
    eero_id: str,
    days: int = 30,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get restart history for a specific eero node.

    Detects restarts by monitoring uptime counter resets.

    Args:
        eero_id: The eero node's external ID.
        days: Number of days to look back (default 30, max 365).
        network: Optional network name filter.
    """
    days = min(days, 365)
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.models.database import EeroNode
            from src.services.node_analysis_service import get_node_restart_summary

            node = (
                db.query(EeroNode)
                .filter(
                    EeroNode.network_name == network_name,
                    EeroNode.eero_id == eero_id,
                )
                .first()
            )
            if not node:
                raise HTTPException(status_code=404, detail="Node not found")

            return get_node_restart_summary(
                db, node.id, node.location or f"Node {eero_id}", days
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get restart history for node {eero_id}: {e}")
        return {"error": str(e), "restarts": [], "total_restarts": 0}


@router.get("/nodes/restart-summary")
async def get_nodes_restart_summary(
    days: int = 30,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get restart counts for all nodes in a network.

    Args:
        days: Number of days to look back (default 30, max 365).
        network: Optional network name filter.
    """
    days = min(days, 365)
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {"nodes": [], "period_days": days}

        with get_db_context() as db:
            from src.models.database import EeroNode
            from src.services.node_analysis_service import get_all_nodes_restart_counts

            nodes = (
                db.query(EeroNode)
                .filter(EeroNode.network_name == network_name)
                .all()
            )
            counts = get_all_nodes_restart_counts(db, network_name, days)

            return {
                "nodes": [
                    {
                        "eero_id": node.eero_id,
                        "location": node.location,
                        "restart_count": counts.get(node.id, 0),
                    }
                    for node in nodes
                ],
                "period_days": days,
            }

    except Exception as e:
        logger.error(f"Failed to get restart summary: {e}")
        return {"nodes": [], "period_days": days, "error": str(e)}


@router.get("/network/health-score")
async def get_network_health_score(
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get current network health score (0-100)."""
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.services.health_score_service import compute_health_score
            return compute_health_score(db, network_name)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compute health score: {e}")
        return {"score": None, "error": str(e)}


@router.get("/network/health-history")
async def get_network_health_history(
    hours: int = 168,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get hourly health score history for trend display."""
    hours = min(hours, 720)  # Cap at 30 days
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.services.health_score_service import compute_health_history
            return {"history": compute_health_history(db, network_name, hours)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compute health history: {e}")
        return {"history": [], "error": str(e)}


@router.get("/network/uptime")
async def get_network_uptime(
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get WAN uptime percentages for 24h, 7d, 30d windows."""
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.services.isp_reliability_service import get_uptime_stats
            return get_uptime_stats(db, network_name)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get uptime stats: {e}")
        return {"error": str(e)}


@router.get("/network/outages")
async def get_network_outages(
    days: int = 30,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get WAN outage events and daily uptime breakdown."""
    days = min(days, 365)
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.services.isp_reliability_service import (
                detect_outages,
                get_daily_uptime,
            )
            return {
                "outages": detect_outages(db, network_name, days),
                "daily_uptime": get_daily_uptime(db, network_name, days),
                "period_days": days,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get outages: {e}")
        return {"outages": [], "daily_uptime": [], "error": str(e)}


@router.get("/devices/{mac_address}/signal-history")
async def get_device_signal_history(
    mac_address: str,
    hours: int = 168,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get signal strength history and trends for a device."""
    hours = min(hours, 720)
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.services.signal_analysis_service import get_signal_history
            return get_signal_history(db, mac_address, network_name, hours)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get signal history for {mac_address}: {e}")
        return {"error": str(e)}


@router.get("/devices/signal-summary")
async def get_devices_signal_summary(
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get signal quality summary across all devices."""
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.services.signal_analysis_service import get_signal_summary
            return get_signal_summary(db, network_name)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get signal summary: {e}")
        return {"error": str(e)}


@router.get("/speedtest/analysis")
async def get_speedtest_analysis(
    days: int = 30,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get speedtest performance trends and analysis."""
    days = min(days, 365)
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.services.speedtest_analysis_service import get_speedtest_analysis as analyze
            return analyze(db, network_name, days)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to analyze speedtest data: {e}")
        return {"error": str(e)}


@router.get("/devices/{mac_address}/bandwidth-heatmap")
async def get_device_bandwidth_heatmap(
    mac_address: str,
    days: int = 7,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get bandwidth utilization heatmap with 5-minute buckets."""
    days = min(days, 14)
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.services.bandwidth_heatmap_service import get_bandwidth_heatmap
            return get_bandwidth_heatmap(db, mac_address, network_name, days)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get bandwidth heatmap for {mac_address}: {e}")
        return {"error": str(e)}


@router.get("/devices/{mac_address}/activity-pattern")
async def get_device_activity_pattern(
    mac_address: str,
    days: int = 7,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get device activity heatmap (7x24 connection probability)."""
    days = min(days, 30)
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.services.activity_pattern_service import get_activity_pattern
            return get_activity_pattern(db, mac_address, network_name, days)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get activity pattern for {mac_address}: {e}")
        return {"error": str(e)}


@router.get("/nodes/load-analysis")
async def get_nodes_load_analysis(
    hours: int = 24,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get node load distribution and roaming analysis."""
    hours = min(hours, 720)
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.services.load_analysis_service import get_load_analysis
            return get_load_analysis(db, network_name, hours)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get load analysis: {e}")
        return {"error": str(e)}


@router.get("/network/guest-usage")
async def get_guest_network_usage(
    hours: int = 24,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get guest network bandwidth and device usage."""
    hours = min(hours, 720)
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.models.database import Device, DeviceConnection
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

            # Guest device connections
            guest_conns = (
                db.query(
                    func.count(DeviceConnection.id).label("readings"),
                    func.count(func.nullif(DeviceConnection.is_connected, False)).label("connected"),
                    func.sum(func.coalesce(DeviceConnection.bandwidth_down_mbps, 0)).label("down"),
                    func.sum(func.coalesce(DeviceConnection.bandwidth_up_mbps, 0)).label("up"),
                )
                .filter(
                    DeviceConnection.network_name == network_name,
                    DeviceConnection.timestamp >= cutoff,
                    DeviceConnection.is_guest == True,
                )
                .first()
            )

            # Total (all) connections for comparison
            total_conns = (
                db.query(
                    func.sum(func.coalesce(DeviceConnection.bandwidth_down_mbps, 0)).label("down"),
                    func.sum(func.coalesce(DeviceConnection.bandwidth_up_mbps, 0)).label("up"),
                )
                .filter(
                    DeviceConnection.network_name == network_name,
                    DeviceConnection.timestamp >= cutoff,
                )
                .first()
            )

            # Distinct guest devices currently connected
            guest_devices = (
                db.query(Device)
                .join(DeviceConnection, Device.id == DeviceConnection.device_id)
                .filter(
                    DeviceConnection.network_name == network_name,
                    DeviceConnection.timestamp >= cutoff,
                    DeviceConnection.is_guest == True,
                    DeviceConnection.is_connected == True,
                )
                .distinct()
                .all()
            )

            guest_down = float(guest_conns.down or 0)
            guest_up = float(guest_conns.up or 0)
            total_down = float(total_conns.down or 0)
            total_up = float(total_conns.up or 0)
            total_bw = total_down + total_up

            return {
                "hours": hours,
                "guest_device_count": len(guest_devices),
                "guest_devices": [
                    {"hostname": d.hostname, "mac": d.mac_address, "type": d.device_type}
                    for d in guest_devices
                ],
                "guest_bandwidth_down_mbps": round(guest_down, 2),
                "guest_bandwidth_up_mbps": round(guest_up, 2),
                "guest_pct_of_total": round(
                    (guest_down + guest_up) / total_bw * 100, 1
                ) if total_bw > 0 else 0,
                "non_guest_pct_of_total": round(
                    (total_bw - guest_down - guest_up) / total_bw * 100, 1
                ) if total_bw > 0 else 100,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get guest usage: {e}")
        return {"error": str(e)}


@router.get("/reports/bandwidth-summary")
async def get_bandwidth_summary_report(
    period: str = "week",
    offset: int = 0,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
) -> Dict[str, Any]:
    """Get bandwidth summary report for a week or month.

    Args:
        period: 'week' or 'month'.
        offset: How many periods back (0=current, 1=previous, etc).
        network: Optional network name filter.
    """
    offset = max(0, min(offset, 52))  # Cap at 52 periods back
    if period not in ("week", "month"):
        raise HTTPException(status_code=400, detail="Period must be 'week' or 'month'")

    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network found")

        with get_db_context() as db:
            from src.services.bandwidth_report_service import get_bandwidth_summary

            return get_bandwidth_summary(db, network_name, period, offset)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate bandwidth report: {e}")
        return {"error": str(e)}


@router.get("/devices/{mac_address}/bandwidth-total")
async def get_device_bandwidth_total(
    mac_address: str,
    days: int = 7,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Get accumulated bandwidth totals for a device over multiple days in a specific network.

    Args:
        mac_address: Device MAC address
        days: Number of days to include (default: 7, max: 90)
        network: Optional network name to filter by. Defaults to first network.

    Raises:
        HTTPException: If days is not between 1 and 90
    """
    # Validate days parameter
    if days < 1 or days > 90:
        raise HTTPException(
            status_code=400,
            detail="days parameter must be between 1 and 90"
        )

    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network available")

        from datetime import timedelta, date
        from src.config import get_settings
        from zoneinfo import ZoneInfo

        with get_db_context() as db:
            from src.models.database import Device, DailyBandwidth

            # Find device in this network
            device = db.query(Device).filter(
                Device.mac_address == mac_address,
                Device.network_name == network_name
            ).first()
            if not device:
                raise HTTPException(status_code=404, detail="Device not found in this network")

            # Get daily bandwidth records
            # Use local timezone to match how data collection stores dates
            settings = get_settings()
            tz = settings.get_timezone()
            now_local = datetime.now(tz)
            today_local = now_local.date()
            since_date = today_local - timedelta(days=days - 1)

            # Generate complete date range
            all_dates = [since_date + timedelta(days=i) for i in range(days)]

            # Fetch records from database
            daily_records = (
                db.query(DailyBandwidth)
                .filter(
                    DailyBandwidth.device_id == device.id,
                    DailyBandwidth.date >= since_date
                )
                .order_by(DailyBandwidth.date)
                .all()
            )

            # Create a lookup map for existing records
            records_by_date = {record.date: record for record in daily_records}

            # Calculate totals
            total_download = sum(record.download_mb for record in daily_records)
            total_upload = sum(record.upload_mb for record in daily_records)

            # Format daily breakdown with complete date range (fill zeros for missing days)
            daily_breakdown = []
            for date_obj in all_dates:
                is_today = date_obj == today_local
                if date_obj in records_by_date:
                    record = records_by_date[date_obj]
                    daily_breakdown.append({
                        "date": date_obj.isoformat(),
                        "download_mb": round(record.download_mb, 2),
                        "upload_mb": round(record.upload_mb, 2),
                        "is_incomplete": is_today,  # Today's data is still being collected
                    })
                else:
                    # No data for this date - fill with zeros
                    daily_breakdown.append({
                        "date": date_obj.isoformat(),
                        "download_mb": 0.0,
                        "upload_mb": 0.0,
                        "is_incomplete": False,
                    })

            return {
                "device": {
                    "mac_address": device.mac_address,
                    "name": device.nickname or device.hostname or device.manufacturer or device.mac_address,
                },
                "period": {
                    "days": days,
                    "start_date": since_date.isoformat(),
                    "end_date": today_local.isoformat(),
                },
                "totals": {
                    "download_mb": round(total_download, 2),
                    "upload_mb": round(total_upload, 2),
                    "total_mb": round(total_download + total_upload, 2),
                },
                "daily_breakdown": daily_breakdown,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get device bandwidth total: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/network/bandwidth-total")
async def get_network_bandwidth_total(
    days: int = 7,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Get network-wide accumulated bandwidth totals over multiple days for a specific network.

    Args:
        days: Number of days to include (default: 7, max: 90)
        network: Optional network name to filter by. Defaults to first network.

    Raises:
        HTTPException: If days is not between 1 and 90
    """
    # Validate days parameter
    if days < 1 or days > 90:
        raise HTTPException(
            status_code=400,
            detail="days parameter must be between 1 and 90"
        )

    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {
                "period": {"days": days, "start_date": None, "end_date": None},
                "totals": {"download_mb": 0, "upload_mb": 0, "total_mb": 0},
                "daily_breakdown": []
            }

        from datetime import timedelta, date
        from src.config import get_settings
        from zoneinfo import ZoneInfo

        with get_db_context() as db:
            from src.models.database import DailyBandwidth

            # Get daily bandwidth records for network-wide (device_id = NULL) in this network
            # Use local timezone to match how data collection stores dates
            settings = get_settings()
            tz = settings.get_timezone()
            now_local = datetime.now(tz)
            today_local = now_local.date()
            since_date = today_local - timedelta(days=days - 1)

            # Generate complete date range
            all_dates = [since_date + timedelta(days=i) for i in range(days)]

            # Fetch and aggregate records from database for this network
            # Sum up all device bandwidth by date (includes both per-device and network-wide totals)
            from sqlalchemy import func as sql_func
            daily_aggregates = (
                db.query(
                    DailyBandwidth.date,
                    sql_func.sum(DailyBandwidth.download_mb).label('download_mb'),
                    sql_func.sum(DailyBandwidth.upload_mb).label('upload_mb')
                )
                .filter(
                    DailyBandwidth.network_name == network_name,
                    DailyBandwidth.date >= since_date
                )
                .group_by(DailyBandwidth.date)
                .order_by(DailyBandwidth.date)
                .all()
            )

            # Create a lookup map for existing records
            records_by_date = {row.date: row for row in daily_aggregates}

            # Calculate totals
            total_download = sum(row.download_mb for row in daily_aggregates)
            total_upload = sum(row.upload_mb for row in daily_aggregates)

            # Format daily breakdown with complete date range (fill zeros for missing days)
            daily_breakdown = []
            for date_obj in all_dates:
                is_today = date_obj == today_local
                if date_obj in records_by_date:
                    record = records_by_date[date_obj]
                    daily_breakdown.append({
                        "date": date_obj.isoformat(),
                        "download_mb": round(record.download_mb, 2),
                        "upload_mb": round(record.upload_mb, 2),
                        "is_incomplete": is_today,  # Today's data is still being collected
                    })
                else:
                    # No data for this date - fill with zeros
                    daily_breakdown.append({
                        "date": date_obj.isoformat(),
                        "download_mb": 0.0,
                        "upload_mb": 0.0,
                        "is_incomplete": False,
                    })

            return {
                "period": {
                    "days": days,
                    "start_date": since_date.isoformat(),
                    "end_date": today_local.isoformat(),
                },
                "totals": {
                    "download_mb": round(total_download, 2),
                    "upload_mb": round(total_upload, 2),
                    "total_mb": round(total_download + total_upload, 2),
                },
                "daily_breakdown": daily_breakdown,
            }

    except Exception as e:
        logger.error(f"Failed to get network bandwidth total: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/network/bandwidth-top-devices")
async def get_network_bandwidth_top_devices(
    days: int = 7,
    limit: int = 5,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Get top bandwidth consuming devices with daily breakdown for stacked graph for a specific network.

    Returns the top N devices by total bandwidth (download + upload) over the
    specified period, plus an "Other" category for all remaining devices.

    Args:
        days: Number of days to include (default: 7, max: 90)
        limit: Number of top devices to return (default: 5, max: 20)
        network: Optional network name to filter by. Defaults to first network.

    Returns:
        {
            "period": {"days": 7, "start_date": "...", "end_date": "..."},
            "dates": ["2025-10-14", "2025-10-15", ...],
            "devices": [
                {
                    "name": "Device 1",
                    "mac_address": "AA:BB:CC:DD:EE:FF",
                    "type": "mobile",
                    "total_mb": 1234.56,
                    "daily_download": [100.5, 150.2, ...],
                    "daily_upload": [50.1, 75.3, ...]
                },
                ...
            ],
            "other": {
                "name": "Other Devices",
                "device_count": 15,
                "total_mb": 567.89,
                "daily_download": [20.1, 30.2, ...],
                "daily_upload": [10.5, 15.3, ...]
            }
        }
    """
    # Validate parameters
    if days < 1 or days > 90:
        raise HTTPException(
            status_code=400,
            detail="days parameter must be between 1 and 90"
        )
    if limit < 1 or limit > 20:
        raise HTTPException(
            status_code=400,
            detail="limit parameter must be between 1 and 20"
        )

    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {
                "period": {"days": days, "start_date": None, "end_date": None},
                "dates": [],
                "devices": [],
                "other": {"name": "Other Devices", "device_count": 0, "total_mb": 0, "daily_download": [], "daily_upload": []}
            }

        from datetime import timedelta
        from sqlalchemy import func
        from src.config import get_settings
        from zoneinfo import ZoneInfo

        with get_db_context() as db:
            from src.models.database import DailyBandwidth, Device, DeviceGroup, DeviceGroupMember

            # Use local timezone
            settings = get_settings()
            tz = settings.get_timezone()
            now_local = datetime.now(tz)
            today_local = now_local.date()
            since_date = today_local - timedelta(days=days - 1)

            # Generate complete date range
            all_dates = [since_date + timedelta(days=i) for i in range(days)]
            date_strings = [d.isoformat() for d in all_dates]

            # Build group membership map: device_id -> group
            group_members = (
                db.query(DeviceGroupMember, DeviceGroup)
                .join(DeviceGroup, DeviceGroup.id == DeviceGroupMember.group_id)
                .filter(DeviceGroup.network_name == network_name)
                .all()
            )
            device_to_group = {}  # device_id -> group
            group_device_ids = {}  # group_id -> [device_ids]
            for member, group in group_members:
                device_to_group[member.device_id] = group
                group_device_ids.setdefault(group.id, []).append(member.device_id)

            # Get per-device bandwidth totals for ranking
            all_device_totals = (
                db.query(
                    DailyBandwidth.device_id,
                    func.sum(DailyBandwidth.download_mb + DailyBandwidth.upload_mb).label('total_mb')
                )
                .join(Device, Device.id == DailyBandwidth.device_id)
                .filter(
                    Device.network_name == network_name,
                    DailyBandwidth.date >= since_date,
                    DailyBandwidth.device_id.isnot(None),
                )
                .group_by(DailyBandwidth.device_id)
                .all()
            )

            # Aggregate by entity (group or individual device)
            # entity_key: "group_{id}" or "device_{id}"
            entity_totals = {}  # key -> total_mb
            entity_device_ids = {}  # key -> [device_ids]
            for device_id, total_mb in all_device_totals:
                if device_id in device_to_group:
                    grp = device_to_group[device_id]
                    key = f"group_{grp.id}"
                    entity_totals[key] = entity_totals.get(key, 0) + total_mb
                    entity_device_ids.setdefault(key, []).append(device_id)
                else:
                    key = f"device_{device_id}"
                    entity_totals[key] = total_mb
                    entity_device_ids[key] = [device_id]

            # Rank and pick top N
            sorted_entities = sorted(entity_totals.items(), key=lambda x: x[1], reverse=True)
            top_entities = sorted_entities[:limit]
            top_entity_keys = {k for k, _ in top_entities}

            # Collect all device_ids that are in top entities
            top_device_ids = []
            for key in top_entity_keys:
                top_device_ids.extend(entity_device_ids[key])

            # Get daily breakdown for top devices
            daily_data = (
                db.query(DailyBandwidth)
                .filter(
                    DailyBandwidth.device_id.in_(top_device_ids),
                    DailyBandwidth.date >= since_date
                )
                .all()
            ) if top_device_ids else []

            # Build a device info lookup
            top_devices = db.query(Device).filter(Device.id.in_(top_device_ids)).all() if top_device_ids else []
            device_info = {d.id: d for d in top_devices}

            # Organize data by entity
            entity_data_map = {}
            for key, total_mb in top_entities:
                if key.startswith("group_"):
                    group_id = int(key.split("_")[1])
                    grp = device_to_group[entity_device_ids[key][0]]
                    entity_data_map[key] = {
                        "name": grp.name,
                        "mac_address": None,
                        "type": "group",
                        "total_mb": round(total_mb, 2),
                        "daily_download": [0.0] * days,
                        "daily_upload": [0.0] * days,
                    }
                else:
                    device_id = int(key.split("_")[1])
                    device = device_info.get(device_id)
                    if device:
                        device_name = device.nickname or device.hostname or device.manufacturer or device.mac_address
                        entity_data_map[key] = {
                            "name": device_name,
                            "mac_address": device.mac_address,
                            "type": device.device_type or "unknown",
                            "total_mb": round(total_mb, 2),
                            "daily_download": [0.0] * days,
                            "daily_upload": [0.0] * days,
                        }

            # Fill in daily values, aggregating grouped devices
            for record in daily_data:
                if record.device_id in device_to_group:
                    key = f"group_{device_to_group[record.device_id].id}"
                else:
                    key = f"device_{record.device_id}"
                if key in entity_data_map:
                    date_index = (record.date - since_date).days
                    if 0 <= date_index < days:
                        entity_data_map[key]["daily_download"][date_index] = round(
                            entity_data_map[key]["daily_download"][date_index] + record.download_mb, 2)
                        entity_data_map[key]["daily_upload"][date_index] = round(
                            entity_data_map[key]["daily_upload"][date_index] + record.upload_mb, 2)

            # Get "Other" devices data
            other_daily_data = (
                db.query(
                    DailyBandwidth.date,
                    func.sum(DailyBandwidth.download_mb).label('download'),
                    func.sum(DailyBandwidth.upload_mb).label('upload')
                )
                .filter(
                    DailyBandwidth.device_id.notin_(top_device_ids) if top_device_ids else True,
                    DailyBandwidth.device_id.isnot(None),  # Exclude network-wide totals
                    DailyBandwidth.date >= since_date
                )
                .group_by(DailyBandwidth.date)
                .all()
            )

            other_download = [0.0] * days
            other_upload = [0.0] * days
            other_total = 0.0

            for record_date, download, upload in other_daily_data:
                date_index = (record_date - since_date).days
                if 0 <= date_index < days:
                    other_download[date_index] = round(download, 2)
                    other_upload[date_index] = round(upload, 2)
                    other_total += download + upload

            # Count other devices/groups
            all_entity_count = len(entity_totals)
            top_entity_count = len(top_entities)
            other_entity_count = all_entity_count - top_entity_count

            return {
                "period": {
                    "days": days,
                    "start_date": since_date.isoformat(),
                    "end_date": today_local.isoformat(),
                },
                "dates": date_strings,
                "devices": list(entity_data_map.values()),
                "other": {
                    "name": "Other Devices",
                    "device_count": other_entity_count,
                    "total_mb": round(other_total, 2),
                    "daily_download": other_download,
                    "daily_upload": other_upload,
                }
            }

    except Exception as e:
        logger.error(f"Failed to get top bandwidth devices: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve bandwidth data")


@router.get("/network/bandwidth-hourly")
async def get_network_bandwidth_hourly(
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Get network-wide bandwidth usage aggregated by hour for the current day (in local timezone) for a specific network.

    Returns hourly bandwidth totals for today based on the configured timezone.
    Includes caching with 5-minute TTL to improve performance for repeat requests.

    Args:
        network: Optional network name to filter by. Defaults to first network.
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {
                "period": {"date": None, "timezone": None, "start_time": None, "end_time": None},
                "totals": {"download_mb": 0, "upload_mb": 0, "total_mb": 0},
                "hourly_breakdown": []
            }

        from datetime import timedelta
        from sqlalchemy import func, extract, Integer
        from src.config import get_settings
        from zoneinfo import ZoneInfo

        settings = get_settings()
        tz = settings.get_timezone()

        # Check cache first (cache key includes network name)
        now_local = datetime.now(tz)
        cache_key = f"{network_name}_{now_local.date().isoformat()}"
        current_time = time.time()

        # Clean up expired cache entries
        expired_keys = [
            key for key, (_, expiry) in _bandwidth_cache.items()
            if expiry < current_time
        ]
        for key in expired_keys:
            del _bandwidth_cache[key]

        # Return cached data if available and not expired
        if cache_key in _bandwidth_cache:
            cached_data, expiry = _bandwidth_cache[cache_key]
            if expiry > current_time:
                logger.debug(f"Returning cached bandwidth data for {cache_key}")
                return cached_data

        logger.debug(f"Cache miss for {cache_key}, querying database...")

        with get_db_context() as db:
            from src.models.database import Device, DeviceConnection

            # Get start of today in local timezone, convert to UTC for database query
            today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            today_start_utc = today_start_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

            # Get end of today in local timezone, convert to UTC
            today_end_local = today_start_local + timedelta(days=1)
            today_end_utc = today_end_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

            # Calculate conversion factor for rate to bytes
            # Mbps * seconds / 8 bits per byte = MB
            interval_seconds = settings.collection_interval_devices
            rate_to_mb = interval_seconds / 8.0

            # Calculate timezone offset in hours for SQL
            # We need to adjust the hour extraction by the timezone offset
            offset_seconds = today_start_local.utcoffset().total_seconds()
            offset_hours = int(offset_seconds / 3600)

            # Query and aggregate in SQL using timezone-adjusted hour extraction
            # This is MUCH faster than fetching all rows and aggregating in Python
            # Filter by network
            hourly_query = (
                db.query(
                    # Extract hour with timezone offset adjustment
                    # Cast strftime result to integer BEFORE doing math
                    # Use ((x % 24) + 24) % 24 to handle negative results correctly in SQLite
                    func.cast(
                        ((func.cast(func.strftime('%H', DeviceConnection.timestamp), Integer) + offset_hours) % 24 + 24) % 24,
                        Integer
                    ).label('hour'),
                    func.sum(
                        func.coalesce(DeviceConnection.bandwidth_down_mbps, 0.0) * rate_to_mb
                    ).label('download_mb'),
                    func.sum(
                        func.coalesce(DeviceConnection.bandwidth_up_mbps, 0.0) * rate_to_mb
                    ).label('upload_mb'),
                    func.count(DeviceConnection.id).label('count')
                )
                .join(Device, DeviceConnection.device_id == Device.id)
                .filter(
                    Device.network_name == network_name,
                    DeviceConnection.timestamp >= today_start_utc,
                    DeviceConnection.timestamp < today_end_utc
                )
                .group_by('hour')
                .all()
            )

            # Convert query results to dictionary for easy lookup
            hourly_data = {
                row.hour: {
                    "download_mb": row.download_mb,
                    "upload_mb": row.upload_mb,
                    "count": row.count
                }
                for row in hourly_query
            }

            # Format hourly breakdown (0-23 hours)
            hourly_breakdown = []
            for hour in range(24):
                if hour in hourly_data:
                    hourly_breakdown.append({
                        "hour": hour,
                        "hour_label": f"{hour:02d}:00",
                        "download_mb": round(hourly_data[hour]["download_mb"], 2),
                        "upload_mb": round(hourly_data[hour]["upload_mb"], 2),
                        "data_points": hourly_data[hour]["count"]
                    })
                else:
                    # No data for this hour
                    hourly_breakdown.append({
                        "hour": hour,
                        "hour_label": f"{hour:02d}:00",
                        "download_mb": 0.0,
                        "upload_mb": 0.0,
                        "data_points": 0
                    })

            # Calculate totals
            total_download = sum(h["download_mb"] for h in hourly_breakdown)
            total_upload = sum(h["upload_mb"] for h in hourly_breakdown)

            result = {
                "period": {
                    "date": now_local.date().isoformat(),
                    "timezone": str(tz),
                    "start_time": today_start_local.isoformat(),
                    "end_time": today_end_local.isoformat(),
                },
                "totals": {
                    "download_mb": round(total_download, 2),
                    "upload_mb": round(total_upload, 2),
                    "total_mb": round(total_download + total_upload, 2),
                },
                "hourly_breakdown": hourly_breakdown,
            }

            # Cache the result with TTL
            _bandwidth_cache[cache_key] = (result, current_time + CACHE_TTL_SECONDS)
            logger.debug(f"Cached bandwidth data for {cache_key} (expires in {CACHE_TTL_SECONDS}s)")

            return result

    except Exception as e:
        logger.error(f"Failed to get hourly network bandwidth: {e}")
        raise HTTPException(status_code=500, detail=str(e))
