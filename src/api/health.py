"""Health check and status API endpoints."""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src import __version__
from src.eero_client import EeroClientWrapper
from src.utils.database import get_db, get_db_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])


# Request models
class DeviceAliasesRequest(BaseModel):
    """Request model for updating device aliases."""
    aliases: List[str]

# Track when the app started
APP_START_TIME = datetime.utcnow()

# Simple in-memory cache for expensive queries
# Cache structure: {cache_key: (data, expiry_time)}
_bandwidth_cache: Dict[str, tuple[Dict[str, Any], float]] = {}
CACHE_TTL_SECONDS = 300  # 5 minutes


def get_eero_client(db: Session = Depends(get_db)) -> EeroClientWrapper:
    """Dependency to get Eero client."""
    return EeroClientWrapper(db)


@router.get("/health")
async def health_check(client: EeroClientWrapper = Depends(get_eero_client)) -> Dict[str, Any]:
    """Health check endpoint."""
    uptime = (datetime.utcnow() - APP_START_TIME).total_seconds()

    # Check database
    db_status = "connected"
    try:
        # Try a simple query
        with get_db_context() as db:
            from src.models.database import Config
            db.query(Config).first()
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "error"

    # Check Eero API auth
    eero_status = "authenticated" if client.is_authenticated() else "not_authenticated"

    overall_status = "healthy" if db_status == "connected" else "degraded"

    return {
        "status": overall_status,
        "version": __version__,
        "uptime_seconds": int(uptime),
        "database": db_status,
        "eero_api": eero_status,
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/collection-status")
async def collection_status() -> Dict[str, Any]:
    """Get data collection status and timestamps."""
    try:
        from src.config import get_settings

        settings = get_settings()

        with get_db_context() as db:
            from src.models.database import Config

            # Get last collection timestamps
            collectors = ["device", "network", "speedtest"]
            last_collections = {}

            for collector_type in collectors:
                config_key = f"last_collection_{collector_type}"
                config = db.query(Config).filter(Config.key == config_key).first()

                if config and config.value:
                    try:
                        timestamp = datetime.fromisoformat(config.value)
                        last_collections[collector_type] = {
                            "timestamp": config.value,
                            "seconds_ago": int(
                                (datetime.utcnow() - timestamp).total_seconds()
                            ),
                        }
                    except Exception:
                        last_collections[collector_type] = None
                else:
                    last_collections[collector_type] = None

            return {
                "collections": last_collections,
                "collection_intervals": {
                    "device": settings.collection_interval_devices,
                    "network": settings.collection_interval_network,
                    "speedtest": settings.collection_interval_network,
                },
            }

    except Exception as e:
        logger.error(f"Failed to get collection status: {e}")
        return {"collections": {}, "error": str(e)}


@router.get("/dashboard-stats")
async def dashboard_stats() -> Dict[str, Any]:
    """Get current dashboard statistics."""
    try:
        with get_db_context() as db:
            from src.models.database import EeroNode, NetworkMetric

            # Get latest network metric
            latest_metric = (
                db.query(NetworkMetric)
                .order_by(NetworkMetric.timestamp.desc())
                .first()
            )

            # Count eero nodes
            eero_count = db.query(EeroNode).count()

            # Check if any node has updates available
            updates_available = db.query(EeroNode).filter(EeroNode.update_available == True).count() > 0

            if latest_metric:
                return {
                    "devices_online": latest_metric.total_devices_online or 0,
                    "devices_total": latest_metric.total_devices or 0,
                    "eero_nodes": eero_count,
                    "wan_status": latest_metric.wan_status or "unknown",
                    "guest_network_enabled": latest_metric.guest_network_enabled or False,
                    "updates_available": updates_available,
                    "last_update": latest_metric.timestamp.isoformat(),
                }
            else:
                # No data collected yet
                return {
                    "devices_online": 0,
                    "devices_total": 0,
                    "eero_nodes": eero_count,
                    "wan_status": "unknown",
                    "guest_network_enabled": False,
                    "updates_available": updates_available,
                    "last_update": None,
                }

    except Exception as e:
        logger.error(f"Failed to get dashboard stats: {e}")
        return {
            "devices_online": 0,
            "devices_total": 0,
            "eero_nodes": 0,
            "wan_status": "error",
            "guest_network_enabled": False,
            "error": str(e),
        }


@router.get("/network-topology")
async def get_network_topology() -> Dict[str, Any]:
    """Get network topology showing nodes and connected devices."""
    try:
        with get_db_context() as db:
            from src.models.database import Device, DeviceConnection, EeroNode

            # Add Internet node
            nodes = [{
                "id": "internet",
                "name": "Internet",
                "type": "internet",
                "model": None,
                "is_gateway": False,
            }]

            # Get all eero nodes
            eero_nodes = db.query(EeroNode).all()
            gateway_node_id = None

            for node in eero_nodes:
                node_id = f"node_{node.id}"
                nodes.append({
                    "id": node_id,
                    "name": node.location or f"Eero {node.id}",
                    "type": "eero_node",
                    "model": node.model,
                    "is_gateway": node.is_gateway or False,
                    "eero_id": node.eero_id,
                    "mac_address": node.mac_address,
                    "last_seen": node.last_seen.isoformat() if node.last_seen else None,
                })

                if node.is_gateway:
                    gateway_node_id = node_id

            # Create mesh connections between eero nodes
            # In a mesh network, nodes connect to each other
            mesh_links = []
            node_ids = [f"node_{n.id}" for n in eero_nodes]

            # Connect gateway to Internet
            if gateway_node_id:
                mesh_links.append({
                    "source": "internet",
                    "target": gateway_node_id,
                    "connection_type": "mesh",
                })

            # Create mesh connections between nodes
            # For simplicity, connect each non-gateway node to the gateway
            for i, node in enumerate(eero_nodes):
                if not node.is_gateway and gateway_node_id:
                    mesh_links.append({
                        "source": gateway_node_id,
                        "target": f"node_{node.id}",
                        "connection_type": "mesh",
                    })

            # Get all online devices with their connections
            devices_list = []
            devices = db.query(Device).all()

            for device in devices:
                # Get most recent connection
                latest_connection = (
                    db.query(DeviceConnection)
                    .filter(DeviceConnection.device_id == device.id)
                    .order_by(DeviceConnection.timestamp.desc())
                    .first()
                )

                # Only include online devices
                if latest_connection and latest_connection.is_connected:
                    device_name = device.nickname or device.hostname or device.mac_address

                    # Get node name
                    node_name = None
                    if latest_connection.eero_node_id:
                        node = db.query(EeroNode).filter(EeroNode.id == latest_connection.eero_node_id).first()
                        if node:
                            node_name = node.location

                    devices_list.append({
                        "id": f"device_{device.id}",
                        "name": device_name,
                        "type": device.device_type or "unknown",
                        "connection_type": latest_connection.connection_type or "unknown",
                        "ip_address": latest_connection.ip_address,
                        "node_id": f"node_{latest_connection.eero_node_id}" if latest_connection.eero_node_id else None,
                        "node_name": node_name or "N/A",
                        "mac_address": device.mac_address,
                        "signal_strength": latest_connection.signal_strength,
                        "last_seen": device.last_seen.isoformat() if device.last_seen else None,
                        "is_online": latest_connection.is_connected or False,
                    })

            return {
                "nodes": nodes,
                "devices": devices_list,
                "mesh_links": mesh_links,
                "total_nodes": len(nodes),
                "total_devices": len(devices_list),
            }

    except Exception as e:
        logger.error(f"Failed to get network topology: {e}")
        return {
            "nodes": [],
            "devices": [],
            "total_nodes": 0,
            "total_devices": 0,
            "error": str(e),
        }


@router.get("/devices")
async def get_devices() -> Dict[str, Any]:
    """Get list of all devices with their latest connection status."""
    try:
        with get_db_context() as db:
            from src.models.database import Device, DeviceConnection, EeroNode

            # Get all devices with their most recent connection
            devices_list = []

            devices = db.query(Device).all()

            for device in devices:
                # Get most recent connection record
                latest_connection = (
                    db.query(DeviceConnection)
                    .filter(DeviceConnection.device_id == device.id)
                    .order_by(DeviceConnection.timestamp.desc())
                    .first()
                )

                # Get eero node name if connected to one
                node_name = None
                connection_type = "unknown"
                ip_address = "N/A"
                is_online = False
                signal_strength = None
                bandwidth_down = None
                bandwidth_up = None

                if latest_connection:
                    if latest_connection.eero_node_id:
                        node = db.query(EeroNode).filter(EeroNode.id == latest_connection.eero_node_id).first()
                        if node:
                            node_name = node.location

                    ip_address = latest_connection.ip_address or "N/A"
                    is_online = latest_connection.is_connected or False
                    connection_type = latest_connection.connection_type or "unknown"
                    signal_strength = latest_connection.signal_strength
                    bandwidth_down = latest_connection.bandwidth_down_mbps
                    bandwidth_up = latest_connection.bandwidth_up_mbps

                device_name = device.nickname or device.hostname or device.mac_address

                # Parse aliases
                aliases = []
                if device.aliases:
                    try:
                        aliases = json.loads(device.aliases)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON in aliases for device {device.mac_address}")

                devices_list.append({
                    "name": device_name,
                    "type": device.device_type or "unknown",
                    "ip_address": ip_address,
                    "is_online": is_online,
                    "connection_type": connection_type,
                    "signal_strength": signal_strength,
                    "bandwidth_down_mbps": bandwidth_down,
                    "bandwidth_up_mbps": bandwidth_up,
                    "node": node_name or "N/A",
                    "mac_address": device.mac_address,
                    "last_seen": device.last_seen.isoformat() if device.last_seen else None,
                    "aliases": aliases,
                })

            return {
                "devices": devices_list,
                "total": len(devices_list),
            }

    except Exception as e:
        logger.error(f"Failed to get devices: {e}")
        return {
            "devices": [],
            "total": 0,
            "error": str(e),
        }


@router.get("/nodes")
async def get_nodes() -> Dict[str, Any]:
    """Get list of all eero nodes (mesh network devices)."""
    try:
        with get_db_context() as db:
            from src.models.database import EeroNode, EeroNodeMetric

            nodes_list = []
            nodes = db.query(EeroNode).all()

            for node in nodes:
                # Get most recent metrics
                latest_metric = (
                    db.query(EeroNodeMetric)
                    .filter(EeroNodeMetric.eero_node_id == node.id)
                    .order_by(EeroNodeMetric.timestamp.desc())
                    .first()
                )

                status = "unknown"
                connected_devices = 0
                connected_wired = 0
                connected_wireless = 0
                uptime = None
                mesh_quality = None

                if latest_metric:
                    status = latest_metric.status or "unknown"
                    # Use wired + wireless for total, fallback to connected_device_count
                    connected_wired = latest_metric.connected_wired_count or 0
                    connected_wireless = latest_metric.connected_wireless_count or 0
                    connected_devices = connected_wired + connected_wireless
                    # Fallback to total count if breakdown not available
                    if connected_devices == 0:
                        connected_devices = latest_metric.connected_device_count or 0
                    uptime = latest_metric.uptime_seconds
                    mesh_quality = latest_metric.mesh_quality_bars

                nodes_list.append({
                    "eero_id": node.eero_id,
                    "location": node.location,
                    "model": node.model,
                    "os_version": node.os_version,
                    "update_available": node.update_available or False,
                    "mac_address": node.mac_address,
                    "is_gateway": node.is_gateway or False,
                    "status": status,
                    "connected_devices": connected_devices,
                    "connected_wired": connected_wired,
                    "connected_wireless": connected_wireless,
                    "mesh_quality_bars": mesh_quality,
                    "uptime": uptime,
                    "last_seen": node.last_seen.isoformat() if node.last_seen else None,
                    "created_at": node.created_at.isoformat() if node.created_at else None,
                })

            return {
                "nodes": nodes_list,
                "total": len(nodes_list),
            }

    except Exception as e:
        logger.error(f"Failed to get nodes: {e}")
        return {
            "nodes": [],
            "total": 0,
            "error": str(e),
        }


@router.put("/devices/{mac_address}/aliases")
async def update_device_aliases(
    mac_address: str,
    request: DeviceAliasesRequest
) -> Dict[str, Any]:
    """Update aliases for a specific device."""
    try:
        with get_db_context() as db:
            from src.models.database import Device

            # Find device by MAC address
            device = db.query(Device).filter(Device.mac_address == mac_address).first()

            if not device:
                raise HTTPException(status_code=404, detail="Device not found")

            # Validate and clean aliases
            cleaned_aliases = []
            for alias in request.aliases:
                alias = alias.strip()
                # Basic validation: alphanumeric, hyphens, underscores
                if alias and alias.replace('-', '').replace('_', '').replace('.', '').isalnum():
                    cleaned_aliases.append(alias)
                elif alias:
                    logger.warning(f"Skipping invalid alias: {alias}")

            # Store aliases as JSON
            device.aliases = json.dumps(cleaned_aliases) if cleaned_aliases else None
            db.commit()

            logger.info(f"Updated aliases for device {mac_address}: {cleaned_aliases}")

            # Trigger DNS update
            from src.services.dns_service import update_dns_hosts
            update_dns_hosts(db)

            return {
                "success": True,
                "mac_address": mac_address,
                "aliases": cleaned_aliases,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update device aliases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devices/{mac_address}/aliases")
async def get_device_aliases(mac_address: str) -> Dict[str, Any]:
    """Get aliases for a specific device."""
    try:
        with get_db_context() as db:
            from src.models.database import Device

            device = db.query(Device).filter(Device.mac_address == mac_address).first()

            if not device:
                raise HTTPException(status_code=404, detail="Device not found")

            aliases = []
            if device.aliases:
                try:
                    aliases = json.loads(device.aliases)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in aliases for device {mac_address}")

            return {
                "mac_address": mac_address,
                "aliases": aliases,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get device aliases: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devices/{mac_address}/bandwidth-history")
async def get_device_bandwidth_history(
    mac_address: str, hours: int = 24
) -> Dict[str, Any]:
    """Get bandwidth usage history for a specific device.

    Args:
        mac_address: Device MAC address
        hours: Number of hours of history to return (default: 24, max: 168)

    Raises:
        HTTPException: If hours is not between 1 and 168
    """
    # Validate hours parameter
    if hours < 1 or hours > 168:
        raise HTTPException(
            status_code=400,
            detail="hours parameter must be between 1 and 168 (7 days)"
        )

    try:
        with get_db_context() as db:
            from src.models.database import Device, DeviceConnection

            # Find device
            device = db.query(Device).filter(Device.mac_address == mac_address).first()
            if not device:
                raise HTTPException(status_code=404, detail="Device not found")

            # Calculate time range
            from datetime import timedelta
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)

            # Get bandwidth history
            connections = (
                db.query(DeviceConnection)
                .filter(
                    DeviceConnection.device_id == device.id,
                    DeviceConnection.timestamp >= cutoff_time,
                )
                .order_by(DeviceConnection.timestamp.asc())
                .all()
            )

            # Format data for graphing
            history = []
            for conn in connections:
                history.append({
                    "timestamp": conn.timestamp.isoformat(),
                    "download_mbps": conn.bandwidth_down_mbps,
                    "upload_mbps": conn.bandwidth_up_mbps,
                    "is_connected": conn.is_connected,
                })

            return {
                "mac_address": mac_address,
                "device_name": device.nickname or device.hostname or mac_address,
                "hours": hours,
                "data_points": len(history),
                "history": history,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get bandwidth history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/network/bandwidth-history")
async def get_network_bandwidth_history(hours: int = 24) -> Dict[str, Any]:
    """Get cumulative network-wide bandwidth usage history.

    Args:
        hours: Number of hours of history to return (default: 24, max: 168)

    Raises:
        HTTPException: If hours is not between 1 and 168
    """
    # Validate hours parameter
    if hours < 1 or hours > 168:
        raise HTTPException(
            status_code=400,
            detail="hours parameter must be between 1 and 168 (7 days)"
        )

    try:
        from datetime import timedelta
        from sqlalchemy import func

        with get_db_context() as db:
            from src.models.database import DeviceConnection

            # Calculate time range
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)

            # Get all connections in time range, aggregated by timestamp
            # Group by timestamp and sum bandwidth across all devices
            connections = (
                db.query(
                    DeviceConnection.timestamp,
                    func.sum(DeviceConnection.bandwidth_down_mbps).label('total_download'),
                    func.sum(DeviceConnection.bandwidth_up_mbps).label('total_upload'),
                )
                .filter(DeviceConnection.timestamp >= cutoff_time)
                .group_by(DeviceConnection.timestamp)
                .order_by(DeviceConnection.timestamp.asc())
                .all()
            )

            # Format data for graphing
            history = []
            for conn in connections:
                history.append({
                    "timestamp": conn.timestamp.isoformat(),
                    "download_mbps": float(conn.total_download) if conn.total_download else 0,
                    "upload_mbps": float(conn.total_upload) if conn.total_upload else 0,
                })

            return {
                "hours": hours,
                "data_points": len(history),
                "history": history,
            }

    except Exception as e:
        logger.error(f"Failed to get network bandwidth history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/devices/{mac_address}/bandwidth-total")
async def get_device_bandwidth_total(
    mac_address: str, days: int = 7
) -> Dict[str, Any]:
    """Get accumulated bandwidth totals for a device over multiple days.

    Args:
        mac_address: Device MAC address
        days: Number of days to include (default: 7, max: 90)

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
        from datetime import timedelta, date

        with get_db_context() as db:
            from src.models.database import Device, DailyBandwidth

            # Find device
            device = db.query(Device).filter(Device.mac_address == mac_address).first()
            if not device:
                raise HTTPException(status_code=404, detail="Device not found")

            # Get daily bandwidth records
            # Use UTC date to match UTC timestamps in database
            today_utc = datetime.utcnow().date()
            since_date = today_utc - timedelta(days=days - 1)
            daily_records = (
                db.query(DailyBandwidth)
                .filter(
                    DailyBandwidth.device_id == device.id,
                    DailyBandwidth.date >= since_date
                )
                .order_by(DailyBandwidth.date)
                .all()
            )

            # Calculate totals
            total_download = sum(record.download_mb for record in daily_records)
            total_upload = sum(record.upload_mb for record in daily_records)

            # Format daily breakdown
            daily_breakdown = []
            for record in daily_records:
                daily_breakdown.append({
                    "date": record.date.isoformat(),
                    "download_mb": round(record.download_mb, 2),
                    "upload_mb": round(record.upload_mb, 2),
                })

            return {
                "device": {
                    "mac_address": device.mac_address,
                    "name": device.nickname or device.hostname or device.mac_address,
                },
                "period": {
                    "days": days,
                    "start_date": since_date.isoformat(),
                    "end_date": today_utc.isoformat(),
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
async def get_network_bandwidth_total(days: int = 7) -> Dict[str, Any]:
    """Get network-wide accumulated bandwidth totals over multiple days.

    Args:
        days: Number of days to include (default: 7, max: 90)

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
        from datetime import timedelta, date
        from src.config import get_settings
        from zoneinfo import ZoneInfo

        with get_db_context() as db:
            from src.models.database import DailyBandwidth

            # Get daily bandwidth records for network-wide (device_id = NULL)
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
                    DailyBandwidth.device_id.is_(None),
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
async def get_network_bandwidth_top_devices(days: int = 7, limit: int = 5) -> Dict[str, Any]:
    """Get top bandwidth consuming devices with daily breakdown for stacked graph.

    Returns the top N devices by total bandwidth (download + upload) over the
    specified period, plus an "Other" category for all remaining devices.

    Args:
        days: Number of days to include (default: 7, max: 90)
        limit: Number of top devices to return (default: 5, max: 20)

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
        from datetime import timedelta
        from sqlalchemy import func
        from src.config import get_settings
        from zoneinfo import ZoneInfo

        with get_db_context() as db:
            from src.models.database import DailyBandwidth, Device

            # Use local timezone
            settings = get_settings()
            tz = settings.get_timezone()
            now_local = datetime.now(tz)
            today_local = now_local.date()
            since_date = today_local - timedelta(days=days - 1)

            # Generate complete date range
            all_dates = [since_date + timedelta(days=i) for i in range(days)]
            date_strings = [d.isoformat() for d in all_dates]

            # Get top N devices by total bandwidth
            top_devices_query = (
                db.query(
                    Device,
                    func.sum(DailyBandwidth.download_mb + DailyBandwidth.upload_mb).label('total_mb')
                )
                .join(DailyBandwidth, Device.id == DailyBandwidth.device_id)
                .filter(DailyBandwidth.date >= since_date)
                .group_by(Device.id)
                .order_by(func.sum(DailyBandwidth.download_mb + DailyBandwidth.upload_mb).desc())
                .limit(limit)
                .all()
            )

            top_device_ids = [device.id for device, _ in top_devices_query]

            # Get daily breakdown for top devices
            daily_data = (
                db.query(DailyBandwidth)
                .filter(
                    DailyBandwidth.device_id.in_(top_device_ids),
                    DailyBandwidth.date >= since_date
                )
                .all()
            )

            # Organize data by device
            device_data_map = {}
            for device, total_mb in top_devices_query:
                device_name = device.nickname or device.hostname or device.mac_address
                device_data_map[device.id] = {
                    "name": device_name,
                    "mac_address": device.mac_address,
                    "type": device.device_type or "unknown",
                    "total_mb": round(total_mb, 2),
                    "daily_download": [0.0] * days,
                    "daily_upload": [0.0] * days,
                }

            # Fill in daily values
            for record in daily_data:
                if record.device_id in device_data_map:
                    date_index = (record.date - since_date).days
                    if 0 <= date_index < days:
                        device_data_map[record.device_id]["daily_download"][date_index] = round(record.download_mb, 2)
                        device_data_map[record.device_id]["daily_upload"][date_index] = round(record.upload_mb, 2)

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

            # Count other devices
            other_device_count = (
                db.query(func.count(func.distinct(DailyBandwidth.device_id)))
                .filter(
                    DailyBandwidth.device_id.notin_(top_device_ids) if top_device_ids else True,
                    DailyBandwidth.device_id.isnot(None),
                    DailyBandwidth.date >= since_date
                )
                .scalar() or 0
            )

            return {
                "period": {
                    "days": days,
                    "start_date": since_date.isoformat(),
                    "end_date": today_local.isoformat(),
                },
                "dates": date_strings,
                "devices": list(device_data_map.values()),
                "other": {
                    "name": "Other Devices",
                    "device_count": other_device_count,
                    "total_mb": round(other_total, 2),
                    "daily_download": other_download,
                    "daily_upload": other_upload,
                }
            }

    except Exception as e:
        logger.error(f"Failed to get top bandwidth devices: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve bandwidth data")


@router.get("/network/bandwidth-hourly")
async def get_network_bandwidth_hourly() -> Dict[str, Any]:
    """Get network-wide bandwidth usage aggregated by hour for the current day (in local timezone).

    Returns hourly bandwidth totals for today based on the configured timezone.
    Includes caching with 5-minute TTL to improve performance for repeat requests.
    """
    try:
        from datetime import timedelta
        from sqlalchemy import func, extract, Integer
        from src.config import get_settings
        from zoneinfo import ZoneInfo

        settings = get_settings()
        tz = settings.get_timezone()

        # Check cache first
        now_local = datetime.now(tz)
        cache_key = now_local.date().isoformat()
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
            from src.models.database import DeviceConnection

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
            hourly_query = (
                db.query(
                    # Extract hour with timezone offset adjustment
                    func.cast(
                        (func.strftime('%H', DeviceConnection.timestamp) + offset_hours) % 24,
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
                .filter(
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


@router.get("/routing/reservations")
async def get_ip_reservations(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get all IP address reservations."""
    try:
        from src.models.database import IpReservation

        reservations = db.query(IpReservation).order_by(IpReservation.ip_address).all()

        return {
            "count": len(reservations),
            "reservations": [
                {
                    "mac_address": res.mac_address,
                    "ip_address": res.ip_address,
                    "description": res.description,
                    "last_seen": res.last_seen.isoformat() if res.last_seen else None,
                }
                for res in reservations
            ],
        }

    except Exception as e:
        logger.error(f"Failed to get IP reservations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/routing/port-forwards")
async def get_port_forwards(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get all port forwarding rules."""
    try:
        from src.models.database import PortForward

        forwards = db.query(PortForward).filter(
            PortForward.enabled == True
        ).order_by(PortForward.ip_address, PortForward.gateway_port).all()

        return {
            "count": len(forwards),
            "forwards": [
                {
                    "ip_address": fwd.ip_address,
                    "gateway_port": fwd.gateway_port,
                    "client_port": fwd.client_port,
                    "protocol": fwd.protocol,
                    "description": fwd.description,
                    "enabled": fwd.enabled,
                    "last_seen": fwd.last_seen.isoformat() if fwd.last_seen else None,
                }
                for fwd in forwards
            ],
        }

    except Exception as e:
        logger.error(f"Failed to get port forwards: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/routing/reservation/{mac_address}")
async def get_reservation_by_mac(mac_address: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get IP reservation for a specific MAC address."""
    try:
        from src.models.database import IpReservation

        # Normalize MAC address (remove colons, convert to uppercase)
        mac_normalized = mac_address.replace(":", "").replace("-", "").upper()

        # Try to find with various formats
        reservation = db.query(IpReservation).filter(
            IpReservation.mac_address == mac_address
        ).first()

        if not reservation:
            return {"reserved": False, "mac_address": mac_address}

        return {
            "reserved": True,
            "mac_address": reservation.mac_address,
            "ip_address": reservation.ip_address,
            "description": reservation.description,
            "last_seen": reservation.last_seen.isoformat() if reservation.last_seen else None,
        }

    except Exception as e:
        logger.error(f"Failed to get reservation for {mac_address}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/routing/forwards/{ip_address}")
async def get_forwards_by_ip(ip_address: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Get port forwards for a specific IP address."""
    try:
        from src.models.database import PortForward

        forwards = db.query(PortForward).filter(
            PortForward.ip_address == ip_address
        ).all()

        return {
            "ip_address": ip_address,
            "count": len(forwards),
            "forwards": [
                {
                    "gateway_port": fwd.gateway_port,
                    "client_port": fwd.client_port,
                    "protocol": fwd.protocol,
                    "description": fwd.description,
                    "enabled": fwd.enabled,
                    "last_seen": fwd.last_seen.isoformat() if fwd.last_seen else None,
                }
                for fwd in forwards
            ],
        }

    except Exception as e:
        logger.error(f"Failed to get forwards for {ip_address}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
