"""Zabbix integration endpoints for eeroVista."""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from src.utils.database import get_db_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/zabbix", tags=["zabbix"])


@router.get("/discovery/devices")
async def discover_devices() -> Dict[str, List[Dict[str, str]]]:
    """
    Zabbix Low-Level Discovery (LLD) for devices.

    Returns a list of all known devices in Zabbix LLD format.
    This endpoint should be configured as a discovery rule in Zabbix.

    **Update Interval**: Recommended 5-10 minutes

    **LLD Macros**:
    - `{#MAC}` - Device MAC address
    - `{#HOSTNAME}` - Device hostname
    - `{#NICKNAME}` - Device nickname (or hostname if no nickname)
    - `{#TYPE}` - Device type (mobile, computer, iot, etc.)

    **Example Response**:
    ```json
    {
      "data": [
        {
          "{#MAC}": "AA:BB:CC:DD:EE:FF",
          "{#HOSTNAME}": "Johns-iPhone",
          "{#NICKNAME}": "John's Phone",
          "{#TYPE}": "mobile"
        }
      ]
    }
    ```
    """
    try:
        with get_db_context() as db:
            from src.models.database import Device

            devices = db.query(Device).all()

            discovery_data = []
            for device in devices:
                hostname = device.hostname or "Unknown"
                nickname = device.nickname or hostname
                device_type = device.device_type or "unknown"

                discovery_data.append({
                    "{#MAC}": device.mac_address,
                    "{#HOSTNAME}": hostname,
                    "{#NICKNAME}": nickname,
                    "{#TYPE}": device_type,
                })

            return {"data": discovery_data}

    except Exception as e:
        logger.error(f"Failed to discover devices for Zabbix: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/discovery/nodes")
async def discover_nodes() -> Dict[str, List[Dict[str, str]]]:
    """
    Zabbix Low-Level Discovery (LLD) for Eero nodes.

    Returns a list of all Eero mesh nodes in Zabbix LLD format.
    This endpoint should be configured as a discovery rule in Zabbix.

    **Update Interval**: Recommended 10 minutes (nodes change infrequently)

    **LLD Macros**:
    - `{#NODE_ID}` - Node unique ID
    - `{#NODE_NAME}` - Node location/name
    - `{#NODE_MODEL}` - Node model (e.g., "eero Pro 6E")
    - `{#IS_GATEWAY}` - Gateway flag ("1" or "0")

    **Example Response**:
    ```json
    {
      "data": [
        {
          "{#NODE_ID}": "node_abc123",
          "{#NODE_NAME}": "Living Room",
          "{#NODE_MODEL}": "eero Pro 6E",
          "{#IS_GATEWAY}": "1"
        }
      ]
    }
    ```
    """
    try:
        with get_db_context() as db:
            from src.models.database import EeroNode

            nodes = db.query(EeroNode).all()

            discovery_data = []
            for node in nodes:
                location = node.location or f"Node {node.eero_id}"
                model = node.model or "Unknown"
                is_gateway = "1" if node.is_gateway else "0"

                discovery_data.append({
                    "{#NODE_ID}": node.eero_id,
                    "{#NODE_NAME}": location,
                    "{#NODE_MODEL}": model,
                    "{#IS_GATEWAY}": is_gateway,
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
    item: str = Query(..., description="Zabbix item key (e.g., 'device.connected[MAC]')")
) -> Dict[str, Any]:
    """
    Get metric data for a specific Zabbix item.

    This endpoint returns the current value for the requested metric.
    Item keys follow the format: `metric_name` or `metric_name[identifier]`

    **Supported Metrics**:

    **Network Metrics** (no identifier):
    - `network.devices.total` - Total number of devices
    - `network.devices.online` - Number of online devices
    - `network.status` - WAN status (1=online, 0=offline)

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
                metric = db.query(NetworkMetric).order_by(NetworkMetric.timestamp.desc()).first()
                if metric:
                    return {
                        "value": metric.total_devices or 0,
                        "timestamp": metric.timestamp.isoformat()
                    }

            elif metric_name == "network.devices.online":
                metric = db.query(NetworkMetric).order_by(NetworkMetric.timestamp.desc()).first()
                if metric:
                    return {
                        "value": metric.total_devices_online or 0,
                        "timestamp": metric.timestamp.isoformat()
                    }

            elif metric_name == "network.status":
                metric = db.query(NetworkMetric).order_by(NetworkMetric.timestamp.desc()).first()
                if metric:
                    status_val = 1 if metric.wan_status == "online" else 0
                    return {
                        "value": status_val,
                        "timestamp": metric.timestamp.isoformat()
                    }

            # Speedtest metrics
            elif metric_name == "speedtest.download":
                speedtest = db.query(Speedtest).order_by(Speedtest.timestamp.desc()).first()
                if speedtest and speedtest.download_mbps is not None:
                    return {
                        "value": speedtest.download_mbps,
                        "timestamp": speedtest.timestamp.isoformat()
                    }

            elif metric_name == "speedtest.upload":
                speedtest = db.query(Speedtest).order_by(Speedtest.timestamp.desc()).first()
                if speedtest and speedtest.upload_mbps is not None:
                    return {
                        "value": speedtest.upload_mbps,
                        "timestamp": speedtest.timestamp.isoformat()
                    }

            elif metric_name == "speedtest.latency":
                speedtest = db.query(Speedtest).order_by(Speedtest.timestamp.desc()).first()
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

                device = db.query(Device).filter(Device.mac_address == identifier).first()
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

                node = db.query(EeroNode).filter(EeroNode.eero_id == identifier).first()
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
