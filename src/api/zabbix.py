"""Zabbix integration endpoints for eeroVista."""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from src.eero_client import EeroClientWrapper
from src.utils.database import get_db, get_db_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/zabbix", tags=["zabbix"])


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


@router.get("/discovery/devices")
async def discover_devices(
    network: Optional[str] = Query(None, description="Network name to filter by. Defaults to first network."),
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, List[Dict[str, str]]]:
    """
    Zabbix Low-Level Discovery (LLD) for devices.

    Returns a list of all known devices in Zabbix LLD format.
    This endpoint should be configured as a discovery rule in Zabbix.

    **Multi-Network Support**: Use the `network` query parameter to filter devices by network.
    If not specified, defaults to the first available network for backwards compatibility.

    **Update Interval**: Recommended 5-10 minutes

    **LLD Macros**:
    - `{#MAC}` - Device MAC address
    - `{#HOSTNAME}` - Device hostname
    - `{#NICKNAME}` - Device nickname (or hostname if no nickname)
    - `{#TYPE}` - Device type (mobile, computer, iot, etc.)
    - `{#IP}` - Last known IP address
    - `{#CONNECTION_TYPE}` - Connection type (wireless/wired)
    - `{#NETWORK}` - Network name

    **Example Response**:
    ```json
    {
      "data": [
        {
          "{#MAC}": "AA:BB:CC:DD:EE:FF",
          "{#HOSTNAME}": "Johns-iPhone",
          "{#NICKNAME}": "John's Phone",
          "{#TYPE}": "mobile",
          "{#NETWORK}": "Home"
        }
      ]
    }
    ```
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {"data": []}

        with get_db_context() as db:
            from src.models.database import Device, DeviceConnection
            from sqlalchemy import func

            # Use optimized JOIN query to avoid N+1 query problem
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
            devices_query = (
                db.query(Device, DeviceConnection)
                .outerjoin(
                    latest_conn_subq,
                    Device.id == latest_conn_subq.c.device_id
                )
                .outerjoin(
                    DeviceConnection,
                    (DeviceConnection.device_id == Device.id) &
                    (DeviceConnection.timestamp == latest_conn_subq.c.max_timestamp)
                )
                .filter(Device.network_name == network_name)
                .all()
            )

            # Build discovery data from query results
            discovery_data = []
            for device, connection in devices_query:
                hostname = device.hostname or "Unknown"
                nickname = device.nickname or hostname
                device_type = device.device_type or "unknown"

                ip_address = connection.ip_address if connection and connection.ip_address else "Unknown"
                connection_type = connection.connection_type if connection and connection.connection_type else "unknown"

                discovery_data.append({
                    "{#MAC}": device.mac_address,
                    "{#HOSTNAME}": hostname,
                    "{#NICKNAME}": nickname,
                    "{#TYPE}": device_type,
                    "{#IP}": ip_address,
                    "{#CONNECTION_TYPE}": connection_type,
                    "{#NETWORK}": network_name,
                })

            return {"data": discovery_data}

    except Exception as e:
        logger.error(f"Failed to discover devices for Zabbix: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/discovery/nodes")
async def discover_nodes(
    network: Optional[str] = Query(None, description="Network name to filter by. Defaults to first network."),
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, List[Dict[str, str]]]:
    """
    Zabbix Low-Level Discovery (LLD) for Eero nodes.

    Returns a list of all Eero mesh nodes in Zabbix LLD format.
    This endpoint should be configured as a discovery rule in Zabbix.

    **Multi-Network Support**: Use the `network` query parameter to filter nodes by network.
    If not specified, defaults to the first available network for backwards compatibility.

    **Update Interval**: Recommended 10 minutes (nodes change infrequently)

    **LLD Macros**:
    - `{#NODE_ID}` - Node unique ID
    - `{#NODE_NAME}` - Node location/name
    - `{#NODE_MODEL}` - Node model (e.g., "eero Pro 6E")
    - `{#IS_GATEWAY}` - Gateway flag ("1" or "0")
    - `{#MAC}` - Node MAC address
    - `{#FIRMWARE}` - Firmware/OS version
    - `{#NETWORK}` - Network name

    **Example Response**:
    ```json
    {
      "data": [
        {
          "{#NODE_ID}": "node_abc123",
          "{#NODE_NAME}": "Living Room",
          "{#NODE_MODEL}": "eero Pro 6E",
          "{#IS_GATEWAY}": "1",
          "{#NETWORK}": "Home"
        }
      ]
    }
    ```
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            return {"data": []}

        with get_db_context() as db:
            from src.models.database import EeroNode

            nodes = db.query(EeroNode).filter(EeroNode.network_name == network_name).all()

            discovery_data = []
            for node in nodes:
                location = node.location or f"Node {node.eero_id}"
                model = node.model or "Unknown"
                is_gateway = "1" if node.is_gateway else "0"
                mac_address = node.mac_address or "Unknown"
                firmware = node.os_version or "Unknown"

                discovery_data.append({
                    "{#NODE_ID}": node.eero_id,
                    "{#NODE_NAME}": location,
                    "{#NODE_MODEL}": model,
                    "{#IS_GATEWAY}": is_gateway,
                    "{#MAC}": mac_address,
                    "{#FIRMWARE}": firmware,
                    "{#NETWORK}": network_name,
                })

            return {"data": discovery_data}

    except Exception as e:
        logger.error(f"Failed to discover nodes for Zabbix: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def parse_item_key(item: str) -> tuple[str, Optional[str]]:
    """
    Parse Zabbix item key into metric name and identifier.

    Examples:
        "network.devices.total" -> ("network.devices.total", None)
        "device.connected[AA:BB:CC:DD:EE:FF]" -> ("device.connected", "AA:BB:CC:DD:EE:FF")
        "node.status[node_123]" -> ("node.status", "node_123")

    Args:
        item: Zabbix item key

    Returns:
        Tuple of (metric_name, identifier)
    """
    match = re.match(r"^([^[]+)(?:\[([^\]]+)\])?$", item)
    if match:
        metric_name = match.group(1)
        identifier = match.group(2)
        return metric_name, identifier
    return item, None


@router.get("/data")
async def get_metric_data(
    item: str = Query(..., description="Zabbix item key (e.g., 'device.connected[MAC]')"),
    network: Optional[str] = Query(None, description="Network name to filter by. Defaults to first network."),
    client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """
    Get metric data for a specific Zabbix item.

    This endpoint returns the current value for the requested metric.
    Item keys follow the format: `metric_name` or `metric_name[identifier]`

    **Multi-Network Support**: Use the `network` query parameter to filter metrics by network.
    If not specified, defaults to the first available network for backwards compatibility.

    **Supported Metrics**:

    **Network Metrics** (no identifier):
    - `network.devices.total` - Total number of devices
    - `network.devices.online` - Number of online devices
    - `network.status` - WAN status (1=online, 0=offline)
    - `network.bridge_mode` - Bridge mode status (1=bridge mode, 0=router mode)

    **Speedtest Metrics** (no identifier):
    - `speedtest.download` - Latest download speed (Mbps)
    - `speedtest.upload` - Latest upload speed (Mbps)
    - `speedtest.latency` - Latest latency (ms)

    **Device Metrics** (identifier = MAC address):
    - `device.connected[MAC]` - Connection status (1=online, 0=offline)
    - `device.signal[MAC]` - Signal strength (dBm)
    - `device.bandwidth.down[MAC]` - Current download rate (Mbps)
    - `device.bandwidth.up[MAC]` - Current upload rate (Mbps)

    **Node Metrics** (identifier = NODE_ID):
    - `node.status[NODE_ID]` - Node status (1=online, 0=offline)
    - `node.devices[NODE_ID]` - Number of connected devices
    - `node.mesh_quality[NODE_ID]` - Mesh quality (1-5)

    **Response Format**:
    ```json
    {
      "value": 123.45,
      "timestamp": "2025-10-20T13:45:00Z"
    }
    ```

    **Error Response** (404):
    ```json
    {
      "detail": "Item not found or not supported: invalid_item"
    }
    ```
    """
    try:
        network_name = get_network_name_filter(network, client)
        if not network_name:
            raise HTTPException(
                status_code=404,
                detail="No network available"
            )

        metric_name, identifier = parse_item_key(item)

        with get_db_context() as db:
            from src.models.database import (
                Device,
                DeviceConnection,
                EeroNode,
                EeroNodeMetric,
                NetworkMetric,
                Speedtest,
            )

            # Network metrics
            if metric_name == "network.devices.total":
                metric = (
                    db.query(NetworkMetric)
                    .filter(NetworkMetric.network_name == network_name)
                    .order_by(NetworkMetric.timestamp.desc())
                    .first()
                )
                if metric:
                    return {
                        "value": metric.total_devices or 0,
                        "timestamp": metric.timestamp.isoformat()
                    }

            elif metric_name == "network.devices.online":
                metric = (
                    db.query(NetworkMetric)
                    .filter(NetworkMetric.network_name == network_name)
                    .order_by(NetworkMetric.timestamp.desc())
                    .first()
                )
                if metric:
                    return {
                        "value": metric.total_devices_online or 0,
                        "timestamp": metric.timestamp.isoformat()
                    }

            elif metric_name == "network.status":
                metric = (
                    db.query(NetworkMetric)
                    .filter(NetworkMetric.network_name == network_name)
                    .order_by(NetworkMetric.timestamp.desc())
                    .first()
                )
                if metric:
                    status_val = 1 if metric.wan_status == "online" else 0
                    return {
                        "value": status_val,
                        "timestamp": metric.timestamp.isoformat()
                    }

            elif metric_name == "network.bridge_mode":
                metric = (
                    db.query(NetworkMetric)
                    .filter(NetworkMetric.network_name == network_name)
                    .order_by(NetworkMetric.timestamp.desc())
                    .first()
                )
                if metric:
                    is_bridge = metric.connection_mode and metric.connection_mode.lower() == 'bridge'
                    bridge_val = 1 if is_bridge else 0
                    return {
                        "value": bridge_val,
                        "timestamp": metric.timestamp.isoformat()
                    }

            # Speedtest metrics
            elif metric_name == "speedtest.download":
                speedtest = (
                    db.query(Speedtest)
                    .filter(Speedtest.network_name == network_name)
                    .order_by(Speedtest.timestamp.desc())
                    .first()
                )
                if speedtest and speedtest.download_mbps is not None:
                    return {
                        "value": speedtest.download_mbps,
                        "timestamp": speedtest.timestamp.isoformat()
                    }

            elif metric_name == "speedtest.upload":
                speedtest = (
                    db.query(Speedtest)
                    .filter(Speedtest.network_name == network_name)
                    .order_by(Speedtest.timestamp.desc())
                    .first()
                )
                if speedtest and speedtest.upload_mbps is not None:
                    return {
                        "value": speedtest.upload_mbps,
                        "timestamp": speedtest.timestamp.isoformat()
                    }

            elif metric_name == "speedtest.latency":
                speedtest = (
                    db.query(Speedtest)
                    .filter(Speedtest.network_name == network_name)
                    .order_by(Speedtest.timestamp.desc())
                    .first()
                )
                if speedtest and speedtest.latency_ms is not None:
                    return {
                        "value": speedtest.latency_ms,
                        "timestamp": speedtest.timestamp.isoformat()
                    }

            # Device metrics (require MAC address identifier)
            elif metric_name.startswith("device."):
                if not identifier:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Device metric requires MAC address: {metric_name}[MAC]"
                    )

                device = (
                    db.query(Device)
                    .filter(
                        Device.network_name == network_name,
                        Device.mac_address == identifier
                    )
                    .first()
                )
                if not device:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Device not found: {identifier}"
                    )

                # Get latest connection
                latest_conn = (
                    db.query(DeviceConnection)
                    .filter(DeviceConnection.device_id == device.id)
                    .order_by(DeviceConnection.timestamp.desc())
                    .first()
                )

                if not latest_conn:
                    raise HTTPException(
                        status_code=404,
                        detail=f"No connection data for device: {identifier}"
                    )

                if metric_name == "device.connected":
                    value = 1 if latest_conn.is_connected else 0
                    return {
                        "value": value,
                        "timestamp": latest_conn.timestamp.isoformat()
                    }

                elif metric_name == "device.signal":
                    if latest_conn.signal_strength is not None:
                        return {
                            "value": latest_conn.signal_strength,
                            "timestamp": latest_conn.timestamp.isoformat()
                        }
                    raise HTTPException(
                        status_code=404,
                        detail=f"No signal strength data for device: {identifier}"
                    )

                elif metric_name == "device.bandwidth.down":
                    if latest_conn.bandwidth_down_mbps is not None:
                        return {
                            "value": latest_conn.bandwidth_down_mbps,
                            "timestamp": latest_conn.timestamp.isoformat()
                        }
                    return {"value": 0.0, "timestamp": latest_conn.timestamp.isoformat()}

                elif metric_name == "device.bandwidth.up":
                    if latest_conn.bandwidth_up_mbps is not None:
                        return {
                            "value": latest_conn.bandwidth_up_mbps,
                            "timestamp": latest_conn.timestamp.isoformat()
                        }
                    return {"value": 0.0, "timestamp": latest_conn.timestamp.isoformat()}

            # Node metrics (require NODE_ID identifier)
            elif metric_name.startswith("node."):
                if not identifier:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Node metric requires node ID: {metric_name}[NODE_ID]"
                    )

                node = (
                    db.query(EeroNode)
                    .filter(
                        EeroNode.network_name == network_name,
                        EeroNode.eero_id == identifier
                    )
                    .first()
                )
                if not node:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Node not found: {identifier}"
                    )

                # Get latest node metrics
                latest_metric = (
                    db.query(EeroNodeMetric)
                    .filter(EeroNodeMetric.eero_node_id == node.id)
                    .order_by(EeroNodeMetric.timestamp.desc())
                    .first()
                )

                if not latest_metric:
                    raise HTTPException(
                        status_code=404,
                        detail=f"No metrics data for node: {identifier}"
                    )

                if metric_name == "node.status":
                    value = 1 if latest_metric.status == "online" else 0
                    return {
                        "value": value,
                        "timestamp": latest_metric.timestamp.isoformat()
                    }

                elif metric_name == "node.devices":
                    return {
                        "value": latest_metric.connected_device_count or 0,
                        "timestamp": latest_metric.timestamp.isoformat()
                    }

                elif metric_name == "node.mesh_quality":
                    if latest_metric.mesh_quality_bars is not None:
                        return {
                            "value": latest_metric.mesh_quality_bars,
                            "timestamp": latest_metric.timestamp.isoformat()
                        }
                    raise HTTPException(
                        status_code=404,
                        detail=f"No mesh quality data for node: {identifier}"
                    )

            # Unknown metric
            raise HTTPException(
                status_code=404,
                detail=f"Item not found or not supported: {item}"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get Zabbix data for item '{item}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
