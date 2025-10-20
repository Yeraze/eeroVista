"""Health check and status API endpoints."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

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
                uptime = None

                if latest_metric:
                    status = latest_metric.status or "unknown"
                    connected_devices = latest_metric.connected_device_count or 0
                    uptime = latest_metric.uptime_seconds

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

        with get_db_context() as db:
            from src.models.database import DailyBandwidth

            # Get daily bandwidth records for network-wide (device_id = NULL)
            # Use UTC date to match UTC timestamps in database
            today_utc = datetime.utcnow().date()
            since_date = today_utc - timedelta(days=days - 1)
            daily_records = (
                db.query(DailyBandwidth)
                .filter(
                    DailyBandwidth.device_id == None,
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

    except Exception as e:
        logger.error(f"Failed to get network bandwidth total: {e}")
        raise HTTPException(status_code=500, detail=str(e))
