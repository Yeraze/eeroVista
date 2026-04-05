"""MQTT publisher that reads DB state and publishes to MQTT topics."""

import logging
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src import __version__
from src.config import Settings
from src.models.database import (
    Device,
    DeviceConnection,
    EeroNode,
    EeroNodeMetric,
    NetworkMetric,
    Speedtest,
)
from src.mqtt.client import MQTTClient
from src.mqtt.discovery import (
    device_discovery_payloads,
    network_discovery_payloads,
    node_discovery_payloads,
    speedtest_discovery_payloads,
)

logger = logging.getLogger(__name__)


class MQTTPublisher:
    """Publishes eeroVista data to MQTT for Home Assistant integration."""

    def __init__(self, client: MQTTClient, settings: Settings):
        self._client = client
        self._settings = settings
        self._discovery_sent = False
        self._prefix = settings.mqtt_topic_prefix
        self._discovery_prefix = settings.mqtt_discovery_prefix

    def stop(self) -> None:
        """Stop the MQTT publisher and disconnect the client."""
        self._client.stop()

    def publish(self, db: Session) -> dict:
        """Publish all current data to MQTT.

        Args:
            db: Database session

        Returns:
            dict with publish results
        """
        if not self._client.is_connected:
            if not self._client.connect():
                return {"success": False, "error": "Not connected to MQTT broker"}

        published = 0
        errors = 0

        try:
            # Get all networks
            networks = self._get_networks(db)

            for network in networks:
                # Send discovery payloads on first publish
                if not self._discovery_sent:
                    self._send_discovery(db, network)

                # Publish network state
                published += self._publish_network(db, network)
                published += self._publish_speedtest(db, network)
                published += self._publish_nodes(db, network)
                published += self._publish_devices(db, network)

            if not self._discovery_sent and networks:
                self._discovery_sent = True

        except Exception as e:
            logger.error(f"MQTT publish error: {e}", exc_info=True)
            errors += 1

        return {
            "success": errors == 0,
            "items_published": published,
            "errors": errors,
        }

    def _get_networks(self, db: Session) -> list[str]:
        """Get distinct network names from the database."""
        rows = db.query(NetworkMetric.network_name).distinct().all()
        return [r[0] for r in rows]

    def _send_discovery(self, db: Session, network: str) -> None:
        """Send Home Assistant MQTT auto-discovery payloads."""
        # Network sensors
        for topic, payload in network_discovery_payloads(
            self._prefix, self._discovery_prefix, network, __version__
        ):
            self._client.publish(topic, payload)

        # Speedtest sensors
        for topic, payload in speedtest_discovery_payloads(
            self._prefix, self._discovery_prefix, network, __version__
        ):
            self._client.publish(topic, payload)

        # Node sensors
        nodes = db.query(EeroNode).filter(EeroNode.network_name == network).all()
        for node in nodes:
            location = node.location or f"Node {node.eero_id}"
            for topic, payload in node_discovery_payloads(
                self._prefix, self._discovery_prefix, network,
                node.eero_id, location, node.model or "Eero",
            ):
                self._client.publish(topic, payload)

        # Device sensors
        devices = db.query(Device).filter(Device.network_name == network).all()
        for device in devices:
            name = device.nickname or device.hostname or device.mac_address
            for topic, payload in device_discovery_payloads(
                self._prefix, self._discovery_prefix, network,
                device.mac_address, name,
            ):
                self._client.publish(topic, payload)

        logger.info(
            f"Sent HA discovery for network '{network}': "
            f"{len(nodes)} nodes, {len(devices)} devices"
        )

    def _publish_network(self, db: Session, network: str) -> int:
        """Publish latest network metrics."""
        latest = (
            db.query(NetworkMetric)
            .filter(NetworkMetric.network_name == network)
            .order_by(NetworkMetric.timestamp.desc())
            .first()
        )
        if not latest:
            return 0

        payload = {
            "total_devices": latest.total_devices or 0,
            "devices_online": latest.total_devices_online or 0,
            "wan_status": "online" if latest.wan_status in ("online", "connected") else "offline",
            "guest_network": latest.guest_network_enabled or False,
            "connection_mode": latest.connection_mode or "unknown",
        }
        topic = f"{self._prefix}/{network}/network"
        return 1 if self._client.publish(topic, payload) else 0

    def _publish_speedtest(self, db: Session, network: str) -> int:
        """Publish latest speedtest results."""
        latest = (
            db.query(Speedtest)
            .filter(Speedtest.network_name == network)
            .order_by(Speedtest.timestamp.desc())
            .first()
        )
        if not latest:
            return 0

        payload = {
            "download_mbps": latest.download_mbps,
            "upload_mbps": latest.upload_mbps,
            "latency_ms": latest.latency_ms,
            "jitter_ms": latest.jitter_ms,
            "server": latest.server_location,
            "isp": latest.isp,
            "timestamp": latest.timestamp.isoformat() if latest.timestamp else None,
        }
        topic = f"{self._prefix}/{network}/speedtest"
        return 1 if self._client.publish(topic, payload) else 0

    def _publish_nodes(self, db: Session, network: str) -> int:
        """Publish eero node metrics."""
        nodes = db.query(EeroNode).filter(EeroNode.network_name == network).all()
        if not nodes:
            return 0

        # Pre-fetch latest metrics for all nodes
        node_ids = [n.id for n in nodes]
        latest_subquery = (
            db.query(
                EeroNodeMetric.eero_node_id,
                func.max(EeroNodeMetric.timestamp).label("max_ts"),
            )
            .filter(EeroNodeMetric.eero_node_id.in_(node_ids))
            .group_by(EeroNodeMetric.eero_node_id)
            .subquery()
        )
        latest_metrics = (
            db.query(EeroNodeMetric)
            .join(
                latest_subquery,
                (EeroNodeMetric.eero_node_id == latest_subquery.c.eero_node_id)
                & (EeroNodeMetric.timestamp == latest_subquery.c.max_ts),
            )
            .all()
        )
        metrics_by_node = {m.eero_node_id: m for m in latest_metrics}

        count = 0
        for node in nodes:
            metric = metrics_by_node.get(node.id)
            payload = {
                "status": metric.status if metric else "unknown",
                "connected_devices": metric.connected_device_count if metric else 0,
                "connected_wired": metric.connected_wired_count if metric else 0,
                "connected_wireless": metric.connected_wireless_count if metric else 0,
                "mesh_quality": metric.mesh_quality_bars if metric else None,
                "uptime_seconds": metric.uptime_seconds if metric else None,
                "update_available": str(bool(node.update_available)).lower(),
                "location": node.location or f"Node {node.eero_id}",
                "model": node.model or "Unknown",
                "is_gateway": node.is_gateway or False,
                "firmware": node.os_version,
            }
            topic = f"{self._prefix}/{network}/node/{node.eero_id}"
            if self._client.publish(topic, payload):
                count += 1

        return count

    def _publish_devices(self, db: Session, network: str) -> int:
        """Publish connected device metrics."""
        devices = db.query(Device).filter(Device.network_name == network).all()
        if not devices:
            return 0

        # Pre-fetch latest connections
        device_ids = [d.id for d in devices]
        latest_subquery = (
            db.query(
                DeviceConnection.device_id,
                func.max(DeviceConnection.timestamp).label("max_ts"),
            )
            .filter(DeviceConnection.device_id.in_(device_ids))
            .group_by(DeviceConnection.device_id)
            .subquery()
        )
        latest_connections = (
            db.query(DeviceConnection)
            .join(
                latest_subquery,
                (DeviceConnection.device_id == latest_subquery.c.device_id)
                & (DeviceConnection.timestamp == latest_subquery.c.max_ts),
            )
            .all()
        )
        conns_by_device = {c.device_id: c for c in latest_connections}

        # Pre-fetch nodes for location names
        all_nodes = db.query(EeroNode).filter(EeroNode.network_name == network).all()
        nodes_by_id = {n.id: n for n in all_nodes}

        count = 0
        for device in devices:
            conn = conns_by_device.get(device.id)
            safe_mac = device.mac_address.replace(":", "_")

            node_name = None
            if conn and conn.eero_node_id:
                node = nodes_by_id.get(conn.eero_node_id)
                if node:
                    node_name = node.location or f"Node {node.eero_id}"

            payload = {
                "connected": str(bool(conn and conn.is_connected)).lower(),
                "connection_type": conn.connection_type if conn else None,
                "signal_strength": conn.signal_strength if conn else None,
                "ip_address": conn.ip_address if conn else None,
                "bandwidth_down_mbps": conn.bandwidth_down_mbps if conn else 0,
                "bandwidth_up_mbps": conn.bandwidth_up_mbps if conn else 0,
                "node": node_name,
                "hostname": device.hostname,
                "nickname": device.nickname,
                "mac": device.mac_address,
            }
            topic = f"{self._prefix}/{network}/device/{safe_mac}"
            if self._client.publish(topic, payload):
                count += 1

        return count
