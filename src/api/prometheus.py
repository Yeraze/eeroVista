"""Prometheus metrics exporter for eeroVista."""

import logging
from typing import Any

from fastapi import APIRouter, Response
from prometheus_client import CollectorRegistry, Gauge, generate_latest

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

network_bridge_mode = Gauge(
    "eero_network_bridge_mode",
    "Network is in bridge mode (1=bridge mode, 0=router mode)",
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
            from datetime import datetime, timezone
            from sqlalchemy import func
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
                # Set bridge mode metric (1 if bridge mode, 0 otherwise)
                is_bridge = latest_network.connection_mode and latest_network.connection_mode.lower() == 'bridge'
                network_bridge_mode.set(1 if is_bridge else 0)

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

            # Pre-fetch all nodes to avoid N+1 queries
            all_nodes = db.query(EeroNode).all()
            nodes_by_id = {node.id: node for node in all_nodes}

            # Get all devices
            devices = db.query(Device).all()

            # Skip device processing if no devices exist
            if devices:
                # Pre-fetch latest connections for all devices (avoid N+1)
                device_ids = [d.id for d in devices]
                latest_conn_subquery = (
                    db.query(
                        DeviceConnection.device_id,
                        func.max(DeviceConnection.timestamp).label('max_timestamp')
                    )
                    .filter(DeviceConnection.device_id.in_(device_ids))
                    .group_by(DeviceConnection.device_id)
                    .subquery()
                )

                latest_connections = (
                    db.query(DeviceConnection)
                    .join(
                        latest_conn_subquery,
                        (DeviceConnection.device_id == latest_conn_subquery.c.device_id) &
                        (DeviceConnection.timestamp == latest_conn_subquery.c.max_timestamp)
                    )
                    .all()
                )
                connections_by_device = {conn.device_id: conn for conn in latest_connections}

                # Pre-fetch today's bandwidth data for all devices (avoid N+1)
                today = datetime.now(timezone.utc).date()
                daily_bandwidths = (
                    db.query(DailyBandwidth)
                    .filter(
                        DailyBandwidth.device_id.in_(device_ids),
                        DailyBandwidth.date == today
                    )
                    .all()
                )
                bandwidth_by_device = {bw.device_id: bw for bw in daily_bandwidths}

                # Process all devices
                for device in devices:
                    # Calculate device labels once
                    hostname = device.hostname or "Unknown"
                    nickname = device.nickname or hostname
                    device_type = device.device_type or "unknown"
                    mac = device.mac_address

                    latest_conn = connections_by_device.get(device.id)

                    if latest_conn:
                        # Get node name using pre-fetched nodes dict
                        node_name = "N/A"
                        if latest_conn.eero_node_id:
                            node = nodes_by_id.get(latest_conn.eero_node_id)
                            if node:
                                node_name = node.location or f"Node {node.eero_id}"

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

                    # Get daily bandwidth using pre-fetched data
                    daily_bw = bandwidth_by_device.get(device.id)
                    if daily_bw:
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

            # Skip node processing if no nodes exist
            if all_nodes:
                # Pre-fetch latest metrics for all nodes (avoid N+1)
                node_ids = [n.id for n in all_nodes]
                latest_metric_subquery = (
                    db.query(
                        EeroNodeMetric.eero_node_id,
                        func.max(EeroNodeMetric.timestamp).label('max_timestamp')
                    )
                    .filter(EeroNodeMetric.eero_node_id.in_(node_ids))
                    .group_by(EeroNodeMetric.eero_node_id)
                    .subquery()
                )

                latest_node_metrics = (
                    db.query(EeroNodeMetric)
                    .join(
                        latest_metric_subquery,
                        (EeroNodeMetric.eero_node_id == latest_metric_subquery.c.eero_node_id) &
                        (EeroNodeMetric.timestamp == latest_metric_subquery.c.max_timestamp)
                    )
                    .all()
                )
                metrics_by_node = {metric.eero_node_id: metric for metric in latest_node_metrics}

                # Process all eero nodes
                for node in all_nodes:
                    # Get most recent node metrics using pre-fetched data
                    latest_metric = metrics_by_node.get(node.id)

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
