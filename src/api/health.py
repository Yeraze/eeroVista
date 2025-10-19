"""Health check and status API endpoints."""

import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import __version__
from src.eero_client import EeroClientWrapper
from src.utils.database import get_db, get_db_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])

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
                "collection_interval_seconds": 300,  # 5 minutes
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

            if latest_metric:
                return {
                    "devices_online": latest_metric.total_devices_online or 0,
                    "devices_total": latest_metric.total_devices or 0,
                    "eero_nodes": eero_count,
                    "wan_status": latest_metric.wan_status or "unknown",
                    "guest_network_enabled": latest_metric.guest_network_enabled or False,
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

                if latest_connection:
                    if latest_connection.eero_node_id:
                        node = db.query(EeroNode).filter(EeroNode.id == latest_connection.eero_node_id).first()
                        if node:
                            node_name = node.location

                    ip_address = latest_connection.ip_address or "N/A"
                    is_online = latest_connection.is_connected or False
                    connection_type = latest_connection.connection_type or "unknown"
                    signal_strength = latest_connection.signal_strength

                device_name = device.nickname or device.hostname or device.mac_address

                devices_list.append({
                    "name": device_name,
                    "type": device.device_type or "unknown",
                    "ip_address": ip_address,
                    "is_online": is_online,
                    "connection_type": connection_type,
                    "signal_strength": signal_strength,
                    "node": node_name or "N/A",
                    "mac_address": device.mac_address,
                    "last_seen": device.last_seen.isoformat() if device.last_seen else None,
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
