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


def get_network_name_filter(network: Optional[str], client: EeroClientWrapper) -> Optional[str]:
    """
    Get the network name to filter by.

    If network is specified, use it.
    If not specified, use the first available network for backwards compatibility.
    Returns None only if no networks are available.
    """
    if network:
        return network

    # Default to first network for backwards compatibility
    networks = client.get_networks()
    if not networks:
        return None

    first_network = networks[0]
    if isinstance(first_network, dict):
        return first_network.get('name')
    else:
        return first_network.name


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


@router.get("/networks")
async def get_networks(client: EeroClientWrapper = Depends(get_eero_client)) -> Dict[str, Any]:
    """Get list of all networks available to the authenticated user."""
    try:
        if not client.is_authenticated():
            raise HTTPException(status_code=401, detail="Not authenticated")

        networks = client.get_networks()
        if not networks:
            return {"networks": [], "count": 0}

        # Format network data
        networks_list = []
        for network in networks:
            # Handle both dict and Pydantic model types
            if isinstance(network, dict):
                networks_list.append({
                    "url": network.get('url'),
                    "name": network.get('name'),
                    "nickname_label": network.get('nickname_label'),
                    "created": network.get('created'),
                })
            else:
                networks_list.append({
                    "url": network.url,
                    "name": network.name,
                    "nickname_label": network.nickname_label,
                    "created": network.created,
                })

        return {
            "networks": networks_list,
            "count": len(networks_list),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get networks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
async def dashboard_stats(
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Get current dashboard statistics for a specific network.

    Args:
        network: Optional network name to filter by. Defaults to first network.
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {
                "devices_online": 0,
                "devices_total": 0,
                "eero_nodes": 0,
                "wan_status": "unknown",
                "guest_network_enabled": False,
                "updates_available": False,
                "last_update": None,
            }

        with get_db_context() as db:
            from src.models.database import EeroNode, NetworkMetric

            # Get latest network metric for this network
            latest_metric = (
                db.query(NetworkMetric)
                .filter(NetworkMetric.network_name == network_name)
                .order_by(NetworkMetric.timestamp.desc())
                .first()
            )

            # Count eero nodes in this network
            eero_count = db.query(EeroNode).filter(
                EeroNode.network_name == network_name
            ).count()

            # Check if any node in this network has updates available
            updates_available = db.query(EeroNode).filter(
                EeroNode.network_name == network_name,
                EeroNode.update_available == True
            ).count() > 0

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
async def get_network_topology(
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Get network topology showing nodes and connected devices for a specific network.

    Args:
        network: Optional network name to filter by. Defaults to first network.
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {
                "nodes": [],
                "devices": [],
                "mesh_links": [],
                "total_nodes": 0,
                "total_devices": 0,
            }

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

            # Get all eero nodes for this network
            eero_nodes = db.query(EeroNode).filter(
                EeroNode.network_name == network_name
            ).all()
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

            # Get all online devices with their connections for this network
            # Use optimized JOIN query to avoid N+1 query problem
            # Subquery to get latest connection timestamp for each device
            from sqlalchemy import func
            latest_conn_subq = (
                db.query(
                    DeviceConnection.device_id,
                    func.max(DeviceConnection.timestamp).label('max_timestamp')
                )
                .group_by(DeviceConnection.device_id)
                .subquery()
            )

            # Main query with JOINs to get all data in one query
            devices_query = (
                db.query(Device, DeviceConnection, EeroNode)
                .join(
                    latest_conn_subq,
                    Device.id == latest_conn_subq.c.device_id
                )
                .join(
                    DeviceConnection,
                    (DeviceConnection.device_id == Device.id) &
                    (DeviceConnection.timestamp == latest_conn_subq.c.max_timestamp)
                )
                .outerjoin(  # LEFT JOIN since device might not be connected to a node
                    EeroNode,
                    EeroNode.id == DeviceConnection.eero_node_id
                )
                .filter(
                    Device.network_name == network_name,
                    DeviceConnection.is_connected.is_(True)  # Only online devices, explicit NULL handling
                )
                .all()
            )

            # Build devices list from query results
            devices_list = []
            for device, connection, node in devices_query:
                device_name = device.nickname or device.hostname or device.manufacturer or device.mac_address
                node_name = node.location if node else None

                devices_list.append({
                    "id": f"device_{device.id}",
                    "name": device_name,
                    "type": device.device_type or "unknown",
                    "connection_type": connection.connection_type or "unknown",
                    "ip_address": connection.ip_address,
                    "node_id": f"node_{connection.eero_node_id}" if connection.eero_node_id else None,
                    "node_name": node_name or "N/A",
                    "mac_address": device.mac_address,
                    "signal_strength": connection.signal_strength,
                    "last_seen": device.last_seen.isoformat() if device.last_seen else None,
                    "is_online": connection.is_connected or False,
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
async def get_devices(
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Get list of all devices with their latest connection status for a specific network.

    Args:
        network: Optional network name to filter by. Defaults to first network.
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {"devices": [], "total": 0}

        with get_db_context() as db:
            from src.models.database import Device, DeviceConnection, EeroNode

            # Get all devices with their most recent connection for this network
            # Use optimized JOIN query to avoid N+1 query problem
            from sqlalchemy import func

            # Subquery to get latest connection timestamp for each device
            latest_conn_subq = (
                db.query(
                    DeviceConnection.device_id,
                    func.max(DeviceConnection.timestamp).label('max_timestamp')
                )
                .group_by(DeviceConnection.device_id)
                .subquery()
            )

            # Main query with JOINs to get all data in one query
            # Use outerjoin for connections and nodes since some devices may not have recent connections
            devices_query = (
                db.query(Device, DeviceConnection, EeroNode)
                .outerjoin(
                    latest_conn_subq,
                    Device.id == latest_conn_subq.c.device_id
                )
                .outerjoin(
                    DeviceConnection,
                    (DeviceConnection.device_id == Device.id) &
                    (DeviceConnection.timestamp == latest_conn_subq.c.max_timestamp)
                )
                .outerjoin(
                    EeroNode,
                    EeroNode.id == DeviceConnection.eero_node_id
                )
                .filter(Device.network_name == network_name)
                .all()
            )

            # Build devices list from query results
            devices_list = []
            for device, connection, node in devices_query:
                # Get eero node name if connected to one
                node_name = node.location if node else None
                connection_type = "unknown"
                ip_address = "N/A"
                is_online = False
                is_guest = False
                signal_strength = None
                bandwidth_down = None
                bandwidth_up = None

                if connection:
                    ip_address = connection.ip_address or "N/A"
                    is_online = connection.is_connected or False
                    connection_type = connection.connection_type or "unknown"
                    is_guest = connection.is_guest or False
                    signal_strength = connection.signal_strength
                    bandwidth_down = connection.bandwidth_down_mbps
                    bandwidth_up = connection.bandwidth_up_mbps

                device_name = device.nickname or device.hostname or device.manufacturer or device.mac_address

                # Parse aliases
                aliases = []
                if device.aliases:
                    try:
                        aliases = json.loads(device.aliases)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON in aliases for device {device.mac_address}")

                devices_list.append({
                    "name": device_name,
                    "nickname": device.nickname,
                    "hostname": device.hostname,
                    "manufacturer": device.manufacturer,
                    "type": device.device_type or "unknown",
                    "ip_address": ip_address,
                    "is_online": is_online,
                    "is_guest": is_guest,
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
async def get_nodes(
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Get list of all eero nodes (mesh network devices) for a specific network.

    Args:
        network: Optional network name to filter by. Defaults to first network.
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {"nodes": [], "total": 0}

        with get_db_context() as db:
            from src.models.database import EeroNode, EeroNodeMetric
            from sqlalchemy import func

            # Use optimized JOIN query to avoid N+1 query problem
            # Subquery to get latest metric timestamp for each node
            latest_metric_subq = (
                db.query(
                    EeroNodeMetric.eero_node_id,
                    func.max(EeroNodeMetric.timestamp).label('max_timestamp')
                )
                .group_by(EeroNodeMetric.eero_node_id)
                .subquery()
            )

            # Main query with JOINs to get all data in one query
            nodes_query = (
                db.query(EeroNode, EeroNodeMetric)
                .outerjoin(
                    latest_metric_subq,
                    EeroNode.id == latest_metric_subq.c.eero_node_id
                )
                .outerjoin(
                    EeroNodeMetric,
                    (EeroNodeMetric.eero_node_id == EeroNode.id) &
                    (EeroNodeMetric.timestamp == latest_metric_subq.c.max_timestamp)
                )
                .filter(EeroNode.network_name == network_name)
                .all()
            )

            # Build nodes list from query results
            nodes_list = []
            for node, metric in nodes_query:
                status = "unknown"
                connected_devices = 0
                connected_wired = 0
                connected_wireless = 0
                uptime = None
                mesh_quality = None

                if metric:
                    status = metric.status or "unknown"
                    # Use wired + wireless for total, fallback to connected_device_count
                    connected_wired = metric.connected_wired_count or 0
                    connected_wireless = metric.connected_wireless_count or 0
                    connected_devices = connected_wired + connected_wireless
                    # Fallback to total count if breakdown not available
                    if connected_devices == 0:
                        connected_devices = metric.connected_device_count or 0
                    uptime = metric.uptime_seconds
                    mesh_quality = metric.mesh_quality_bars

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
    request: DeviceAliasesRequest,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Update aliases for a specific device in a specific network.

    Args:
        mac_address: Device MAC address
        request: Aliases request body
        network: Optional network name to filter by. Defaults to first network.
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network available")

        with get_db_context() as db:
            from src.models.database import Device

            # Find device by MAC address in this network
            device = db.query(Device).filter(
                Device.mac_address == mac_address,
                Device.network_name == network_name
            ).first()

            if not device:
                raise HTTPException(status_code=404, detail="Device not found in this network")

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
async def get_device_aliases(
    mac_address: str,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Get aliases for a specific device in a specific network.

    Args:
        mac_address: Device MAC address
        network: Optional network name to filter by. Defaults to first network.
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network available")

        with get_db_context() as db:
            from src.models.database import Device

            device = db.query(Device).filter(
                Device.mac_address == mac_address,
                Device.network_name == network_name
            ).first()

            if not device:
                raise HTTPException(status_code=404, detail="Device not found in this network")

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
    mac_address: str,
    hours: int = 24,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Get bandwidth usage history for a specific device in a specific network.

    Args:
        mac_address: Device MAC address
        hours: Number of hours of history to return (default: 24, max: 168)
        network: Optional network name to filter by. Defaults to first network.

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
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(status_code=404, detail="No network available")

        with get_db_context() as db:
            from src.models.database import Device, DeviceConnection

            # Find device in this network
            device = db.query(Device).filter(
                Device.mac_address == mac_address,
                Device.network_name == network_name
            ).first()
            if not device:
                raise HTTPException(status_code=404, detail="Device not found in this network")

            # Calculate time range (timezone-aware)
            from datetime import timedelta
            from src.config import get_settings
            from zoneinfo import ZoneInfo

            settings = get_settings()
            tz = settings.get_timezone()

            # Get current time in local timezone, then convert to UTC for database query
            now_local = datetime.now(tz)
            cutoff_local = now_local - timedelta(hours=hours)
            cutoff_time = cutoff_local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

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

            # Format data for graphing (convert timestamps to local timezone)
            history = []
            for conn in connections:
                # Database stores UTC naive datetime, convert to local timezone
                timestamp_utc = conn.timestamp.replace(tzinfo=ZoneInfo("UTC"))
                timestamp_local = timestamp_utc.astimezone(tz)

                history.append({
                    "timestamp": timestamp_local.isoformat(),
                    "download_mbps": conn.bandwidth_down_mbps,
                    "upload_mbps": conn.bandwidth_up_mbps,
                    "is_connected": conn.is_connected,
                })

            return {
                "mac_address": mac_address,
                "device_name": device.nickname or device.hostname or device.manufacturer or mac_address,
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
async def get_network_bandwidth_history(
    hours: int = 24,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Get cumulative network-wide bandwidth usage history for a specific network.

    Args:
        hours: Number of hours of history to return (default: 24, max: 168)
        network: Optional network name to filter by. Defaults to first network.

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
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {"hours": hours, "data_points": 0, "history": []}

        from datetime import timedelta
        from sqlalchemy import func

        with get_db_context() as db:
            from src.models.database import Device, DeviceConnection

            # Calculate time range
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)

            # Get all connections in time range for devices in this network
            # Group by timestamp and sum bandwidth across all devices
            connections = (
                db.query(
                    DeviceConnection.timestamp,
                    func.sum(DeviceConnection.bandwidth_down_mbps).label('total_download'),
                    func.sum(DeviceConnection.bandwidth_up_mbps).label('total_upload'),
                )
                .join(Device, DeviceConnection.device_id == Device.id)
                .filter(
                    Device.network_name == network_name,
                    DeviceConnection.timestamp >= cutoff_time
                )
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

            # Get top N devices by total bandwidth in this network
            top_devices_query = (
                db.query(
                    Device,
                    func.sum(DailyBandwidth.download_mb + DailyBandwidth.upload_mb).label('total_mb')
                )
                .join(DailyBandwidth, Device.id == DailyBandwidth.device_id)
                .filter(
                    Device.network_name == network_name,
                    DailyBandwidth.date >= since_date
                )
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
                device_name = device.nickname or device.hostname or device.manufacturer or device.mac_address
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


@router.get("/routing/reservations")
async def get_ip_reservations(
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Get all IP address reservations for a specific network.

    Args:
        network: Optional network name to filter by. Defaults to first network.
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {"count": 0, "reservations": []}

        from src.models.database import IpReservation

        reservations = db.query(IpReservation).filter(
            IpReservation.network_name == network_name
        ).order_by(IpReservation.ip_address).all()

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
async def get_port_forwards(
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Get all port forwarding rules for a specific network.

    Args:
        network: Optional network name to filter by. Defaults to first network.
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {"count": 0, "forwards": []}

        from src.models.database import PortForward

        forwards = db.query(PortForward).filter(
            PortForward.network_name == network_name,
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
async def get_reservation_by_mac(
    mac_address: str,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Get IP reservation for a specific MAC address in a specific network.

    Args:
        mac_address: Device MAC address
        network: Optional network name to filter by. Defaults to first network.
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {"reserved": False, "mac_address": mac_address}

        from src.models.database import IpReservation

        # Normalize MAC address (remove colons, convert to uppercase)
        mac_normalized = mac_address.replace(":", "").replace("-", "").upper()

        # Try to find with various formats (original or normalized) in this network
        reservation = db.query(IpReservation).filter(
            IpReservation.network_name == network_name,
            (IpReservation.mac_address == mac_address) |
            (IpReservation.mac_address == mac_normalized)
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
async def get_forwards_by_ip(
    ip_address: str,
    network: Optional[str] = None,
    client: EeroClientWrapper = Depends(get_eero_client),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Get port forwards for a specific IP address in a specific network.

    Args:
        ip_address: IP address to query
        network: Optional network name to filter by. Defaults to first network.
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {"ip_address": ip_address, "count": 0, "forwards": []}

        from src.models.database import PortForward

        forwards = db.query(PortForward).filter(
            PortForward.network_name == network_name,
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


@router.post("/database/cleanup")
async def cleanup_unauthorized_networks(
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Clean up database records for networks the user is no longer authorized for.

    This endpoint identifies and removes all data (devices, nodes, connections, metrics, etc.)
    for networks that exist in the database but are not in the user's current authorized networks list.

    **Use Case**: Useful after testing with multiple networks, changing Eero accounts, or losing
    access to networks. Removes orphaned data to keep the database clean.

    **What Gets Deleted**:
    - Devices and all their connection history
    - Eero nodes and their metrics
    - Network metrics
    - Speedtest results
    - Daily bandwidth records
    - IP reservations
    - Port forwarding rules

    **Safety**: Only deletes networks not in the current authorized list.
    Current networks are never touched.

    **Returns**:
    ```json
    {
        "success": true,
        "authorized_networks": ["Home", "Office"],
        "removed_networks": ["OldNetwork", "TestNetwork"],
        "deleted_counts": {
            "devices": 45,
            "device_connections": 12340,
            "eero_nodes": 3,
            ...
        }
    }
    ```
    """
    try:
        if not client.is_authenticated():
            raise HTTPException(status_code=401, detail="Not authenticated")

        # Get currently authorized networks
        networks = client.get_networks()
        if not networks:
            raise HTTPException(
                status_code=400,
                detail="No networks available. Cannot determine what to clean up."
            )

        authorized_networks = set()
        for network in networks:
            if isinstance(network, dict):
                name = network.get('name')
            else:
                name = network.name
            if name:
                authorized_networks.add(name)

        logger.info(f"Authorized networks: {authorized_networks}")

        with get_db_context() as db:
            from src.models.database import (
                DailyBandwidth,
                Device,
                DeviceConnection,
                EeroNode,
                EeroNodeMetric,
                IpReservation,
                NetworkMetric,
                PortForward,
                Speedtest,
            )

            # Find all network names in database
            all_db_networks = set()

            # Check each table for network_name values
            for model in [Device, EeroNode, NetworkMetric, Speedtest]:
                result = db.query(model.network_name).distinct().all()
                all_db_networks.update(row[0] for row in result if row[0])

            # Find networks to remove (in database but not authorized)
            networks_to_remove = all_db_networks - authorized_networks

            if not networks_to_remove:
                return {
                    "success": True,
                    "message": "No unauthorized networks found. Database is clean.",
                    "authorized_networks": sorted(list(authorized_networks)),
                    "removed_networks": [],
                    "deleted_counts": {},
                }

            logger.info(f"Networks to remove: {networks_to_remove}")

            # Track deletion counts
            deleted_counts = {}

            # Delete data for unauthorized networks
            # Order matters due to foreign key relationships

            # 1. DeviceConnection (child of Device)
            count = db.query(DeviceConnection).filter(
                DeviceConnection.network_name.in_(networks_to_remove)
            ).delete(synchronize_session=False)
            deleted_counts["device_connections"] = count
            logger.info(f"Deleted {count} DeviceConnection records")

            # 2. DailyBandwidth (child of Device)
            count = db.query(DailyBandwidth).filter(
                DailyBandwidth.network_name.in_(networks_to_remove)
            ).delete(synchronize_session=False)
            deleted_counts["daily_bandwidth"] = count
            logger.info(f"Deleted {count} DailyBandwidth records")

            # 3. Device
            count = db.query(Device).filter(
                Device.network_name.in_(networks_to_remove)
            ).delete(synchronize_session=False)
            deleted_counts["devices"] = count
            logger.info(f"Deleted {count} Device records")

            # 4. EeroNodeMetric (child of EeroNode)
            # First get node IDs to delete
            node_ids_to_delete = [
                node.id for node in db.query(EeroNode.id).filter(
                    EeroNode.network_name.in_(networks_to_remove)
                ).all()
            ]
            if node_ids_to_delete:
                count = db.query(EeroNodeMetric).filter(
                    EeroNodeMetric.eero_node_id.in_(node_ids_to_delete)
                ).delete(synchronize_session=False)
                deleted_counts["eero_node_metrics"] = count
                logger.info(f"Deleted {count} EeroNodeMetric records")

            # 5. EeroNode
            count = db.query(EeroNode).filter(
                EeroNode.network_name.in_(networks_to_remove)
            ).delete(synchronize_session=False)
            deleted_counts["eero_nodes"] = count
            logger.info(f"Deleted {count} EeroNode records")

            # 6. NetworkMetric
            count = db.query(NetworkMetric).filter(
                NetworkMetric.network_name.in_(networks_to_remove)
            ).delete(synchronize_session=False)
            deleted_counts["network_metrics"] = count
            logger.info(f"Deleted {count} NetworkMetric records")

            # 7. Speedtest
            count = db.query(Speedtest).filter(
                Speedtest.network_name.in_(networks_to_remove)
            ).delete(synchronize_session=False)
            deleted_counts["speedtests"] = count
            logger.info(f"Deleted {count} Speedtest records")

            # 8. IpReservation
            count = db.query(IpReservation).filter(
                IpReservation.network_name.in_(networks_to_remove)
            ).delete(synchronize_session=False)
            deleted_counts["ip_reservations"] = count
            logger.info(f"Deleted {count} IpReservation records")

            # 9. PortForward
            count = db.query(PortForward).filter(
                PortForward.network_name.in_(networks_to_remove)
            ).delete(synchronize_session=False)
            deleted_counts["port_forwards"] = count
            logger.info(f"Deleted {count} PortForward records")

            # Commit all deletions
            db.commit()

            total_deleted = sum(deleted_counts.values())
            logger.info(f"Database cleanup complete. Total records deleted: {total_deleted}")

            return {
                "success": True,
                "message": f"Cleaned up {len(networks_to_remove)} unauthorized network(s)",
                "authorized_networks": sorted(list(authorized_networks)),
                "removed_networks": sorted(list(networks_to_remove)),
                "deleted_counts": deleted_counts,
                "total_deleted": total_deleted,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cleanup unauthorized networks: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
