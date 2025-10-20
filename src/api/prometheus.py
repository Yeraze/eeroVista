"""Prometheus metrics exporter for eeroVista."""

import logging
from typing import Any

from fastapi import APIRouter, Response
from prometheus_client import CollectorRegistry, Gauge, generate_latest
from prometheus_client.core import REGISTRY

from src.utils.database import get_db_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["prometheus"])

# Create a custom registry for eeroVista metrics
# This avoids conflicts with default Python process metrics
registry = CollectorRegistry()

# Network-wide metrics
network_devices_total = Gauge(
    "eero_network_devices_total",
    "Total number of devices known to the network",
    registry=registry
)

network_devices_online = Gauge(
    "eero_network_devices_online",
    "Number of currently online devices",
    registry=registry
)

network_status = Gauge(
    "eero_network_status",
    "Network WAN status (1=online, 0=offline)",
    registry=registry
)

# Speedtest metrics
speedtest_download_mbps = Gauge(
    "eero_speedtest_download_mbps",
    "Latest speedtest download speed in Mbps",
    registry=registry
)

speedtest_upload_mbps = Gauge(
    "eero_speedtest_upload_mbps",
    "Latest speedtest upload speed in Mbps",
    registry=registry
)

speedtest_latency_ms = Gauge(
    "eero_speedtest_latency_ms",
    "Latest speedtest latency in milliseconds",
    registry=registry
)

# Per-device metrics (with labels)
device_connected = Gauge(
    "eero_device_connected",
    "Device connection status (1=online, 0=offline)",
    ["mac", "hostname", "nickname", "type", "node"],
    registry=registry
)

device_signal_strength_dbm = Gauge(
    "eero_device_signal_strength_dbm",
    "Device WiFi signal strength in dBm",
    ["mac", "hostname", "nickname", "type", "node"],
    registry=registry
)

device_bandwidth_down_mbps = Gauge(
    "eero_device_bandwidth_down_mbps",
    "Device current download rate in Mbps",
    ["mac", "hostname", "nickname", "type", "node"],
    registry=registry
)

device_bandwidth_up_mbps = Gauge(
    "eero_device_bandwidth_up_mbps",
    "Device current upload rate in Mbps",
    ["mac", "hostname", "nickname", "type", "node"],
    registry=registry
)

device_daily_download_mb = Gauge(
    "eero_device_daily_download_mb",
    "Device total download for today in MB",
    ["mac", "hostname", "nickname", "type"],
    registry=registry
)

device_daily_upload_mb = Gauge(
    "eero_device_daily_upload_mb",
    "Device total upload for today in MB",
    ["mac", "hostname", "nickname", "type"],
    registry=registry
)

# Per-node metrics (with labels)
node_status = Gauge(
    "eero_node_status",
    "Eero node status (1=online, 0=offline)",
    ["node_id", "location", "model", "is_gateway"],
    registry=registry
)

node_connected_devices = Gauge(
    "eero_node_connected_devices",
    "Number of devices connected to this node",
    ["node_id", "location", "model", "is_gateway"],
    registry=registry
)

node_connected_wired = Gauge(
    "eero_node_connected_wired",
    "Number of wired devices connected to this node",
    ["node_id", "location", "model", "is_gateway"],
    registry=registry
)

node_connected_wireless = Gauge(
    "eero_node_connected_wireless",
    "Number of wireless devices connected to this node",
    ["node_id", "location", "model", "is_gateway"],
    registry=registry
)

node_mesh_quality = Gauge(
    "eero_node_mesh_quality",
    "Node mesh quality (1-5 bars)",
    ["node_id", "location", "model", "is_gateway"],
    registry=registry
)

node_uptime_seconds = Gauge(
    "eero_node_uptime_seconds",
    "Node uptime in seconds",
    ["node_id", "location", "model", "is_gateway"],
    registry=registry
)

node_update_available = Gauge(
    "eero_node_update_available",
    "Firmware update available for node (1=yes, 0=no)",
    ["node_id", "location", "model", "is_gateway"],
    registry=registry
)


def update_metrics() -> None:
    """Update all Prometheus metrics from database."""
    try:
        with get_db_context() as db:
            from datetime import datetime
            from src.models.database import (
                DailyBandwidth,
                Device,
                DeviceConnection,
                EeroNode,
                EeroNodeMetric,
                NetworkMetric,
                Speedtest,
            )

            # Get latest network metrics
            latest_network = (
                db.query(NetworkMetric)
                .order_by(NetworkMetric.timestamp.desc())
                .first()
            )

            if latest_network:
                network_devices_total.set(latest_network.total_devices or 0)
                network_devices_online.set(latest_network.total_devices_online or 0)
                network_status.set(1 if latest_network.wan_status == "online" else 0)

            # Get latest speedtest
            latest_speedtest = (
                db.query(Speedtest)
                .order_by(Speedtest.timestamp.desc())
                .first()
            )

            if latest_speedtest:
                if latest_speedtest.download_mbps is not None:
                    speedtest_download_mbps.set(latest_speedtest.download_mbps)
                if latest_speedtest.upload_mbps is not None:
                    speedtest_upload_mbps.set(latest_speedtest.upload_mbps)
                if latest_speedtest.latency_ms is not None:
                    speedtest_latency_ms.set(latest_speedtest.latency_ms)

            # Get all devices with their latest connections
            devices = db.query(Device).all()

            for device in devices:
                # Get most recent connection
                latest_conn = (
                    db.query(DeviceConnection)
                    .filter(DeviceConnection.device_id == device.id)
                    .order_by(DeviceConnection.timestamp.desc())
                    .first()
                )

                if latest_conn:
                    # Get node name if connected to one
                    node_name = "N/A"
                    if latest_conn.eero_node_id:
                        node = db.query(EeroNode).filter(EeroNode.id == latest_conn.eero_node_id).first()
                        if node:
                            node_name = node.location or f"Node {node.eero_id}"

                    # Device labels
                    hostname = device.hostname or "Unknown"
                    nickname = device.nickname or hostname
                    device_type = device.device_type or "unknown"
                    mac = device.mac_address

                    # Connection status
                    is_connected = 1 if latest_conn.is_connected else 0
                    device_connected.labels(
                        mac=mac,
                        hostname=hostname,
                        nickname=nickname,
                        type=device_type,
                        node=node_name
                    ).set(is_connected)

                    # Signal strength (only for wireless devices)
                    if latest_conn.signal_strength is not None:
                        device_signal_strength_dbm.labels(
                            mac=mac,
                            hostname=hostname,
                            nickname=nickname,
                            type=device_type,
                            node=node_name
                        ).set(latest_conn.signal_strength)

                    # Current bandwidth
                    if latest_conn.bandwidth_down_mbps is not None:
                        device_bandwidth_down_mbps.labels(
                            mac=mac,
                            hostname=hostname,
                            nickname=nickname,
                            type=device_type,
                            node=node_name
                        ).set(latest_conn.bandwidth_down_mbps)

                    if latest_conn.bandwidth_up_mbps is not None:
                        device_bandwidth_up_mbps.labels(
                            mac=mac,
                            hostname=hostname,
                            nickname=nickname,
                            type=device_type,
                            node=node_name
                        ).set(latest_conn.bandwidth_up_mbps)

                # Get daily bandwidth totals for today
                today = datetime.utcnow().date()
                daily_bw = (
                    db.query(DailyBandwidth)
                    .filter(
                        DailyBandwidth.device_id == device.id,
                        DailyBandwidth.date == today
                    )
                    .first()
                )

                if daily_bw:
                    hostname = device.hostname or "Unknown"
                    nickname = device.nickname or hostname
                    device_type = device.device_type or "unknown"
                    mac = device.mac_address

                    device_daily_download_mb.labels(
                        mac=mac,
                        hostname=hostname,
                        nickname=nickname,
                        type=device_type
                    ).set(daily_bw.download_mb)

                    device_daily_upload_mb.labels(
                        mac=mac,
                        hostname=hostname,
                        nickname=nickname,
                        type=device_type
                    ).set(daily_bw.upload_mb)

            # Get all eero nodes with their latest metrics
            nodes = db.query(EeroNode).all()

            for node in nodes:
                # Get most recent node metrics
                latest_metric = (
                    db.query(EeroNodeMetric)
                    .filter(EeroNodeMetric.eero_node_id == node.id)
                    .order_by(EeroNodeMetric.timestamp.desc())
                    .first()
                )

                # Node labels
                node_id = node.eero_id
                location = node.location or f"Node {node_id}"
                model = node.model or "Unknown"
                is_gateway = "1" if node.is_gateway else "0"

                if latest_metric:
                    # Node status
                    status_val = 1 if latest_metric.status == "online" else 0
                    node_status.labels(
                        node_id=node_id,
                        location=location,
                        model=model,
                        is_gateway=is_gateway
                    ).set(status_val)

                    # Connected devices
                    if latest_metric.connected_device_count is not None:
                        node_connected_devices.labels(
                            node_id=node_id,
                            location=location,
                            model=model,
                            is_gateway=is_gateway
                        ).set(latest_metric.connected_device_count)

                    # Wired/Wireless breakdown
                    if latest_metric.connected_wired_count is not None:
                        node_connected_wired.labels(
                            node_id=node_id,
                            location=location,
                            model=model,
                            is_gateway=is_gateway
                        ).set(latest_metric.connected_wired_count)

                    if latest_metric.connected_wireless_count is not None:
                        node_connected_wireless.labels(
                            node_id=node_id,
                            location=location,
                            model=model,
                            is_gateway=is_gateway
                        ).set(latest_metric.connected_wireless_count)

                    # Mesh quality
                    if latest_metric.mesh_quality_bars is not None:
                        node_mesh_quality.labels(
                            node_id=node_id,
                            location=location,
                            model=model,
                            is_gateway=is_gateway
                        ).set(latest_metric.mesh_quality_bars)

                    # Uptime
                    if latest_metric.uptime_seconds is not None:
                        node_uptime_seconds.labels(
                            node_id=node_id,
                            location=location,
                            model=model,
                            is_gateway=is_gateway
                        ).set(latest_metric.uptime_seconds)

                # Update available
                update_val = 1 if node.update_available else 0
                node_update_available.labels(
                    node_id=node_id,
                    location=location,
                    model=model,
                    is_gateway=is_gateway
                ).set(update_val)

    except Exception as e:
        logger.error(f"Failed to update Prometheus metrics: {e}", exc_info=True)


@router.get("/metrics")
async def metrics() -> Response:
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text exposition format for scraping.
    This endpoint is designed to be scraped by Prometheus at regular intervals.

    **Update Frequency**: Metrics reflect the latest collected data from the database.

    **Recommended Scrape Interval**: 60 seconds
    """
    try:
        # Update metrics from database
        update_metrics()

        # Generate Prometheus formatted output
        metrics_output = generate_latest(registry)

        return Response(
            content=metrics_output,
            media_type="text/plain; version=0.0.4; charset=utf-8"
        )
    except Exception as e:
        logger.error(f"Failed to generate Prometheus metrics: {e}", exc_info=True)
        return Response(
            content=f"# Error generating metrics: {e}\n",
            media_type="text/plain",
            status_code=500
        )
