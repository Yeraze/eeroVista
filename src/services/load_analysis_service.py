"""Node load balancing analysis service.

Analyzes device distribution across nodes and detects roaming events.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.database import Device, DeviceConnection, EeroNode, EeroNodeMetric

logger = logging.getLogger(__name__)


def get_load_analysis(
    db: Session,
    network_name: str,
    hours: int = 24,
) -> Dict[str, Any]:
    """Analyze device load distribution across nodes.

    Args:
        db: Database session.
        network_name: Network name.
        hours: Hours to analyze.

    Returns:
        Dict with per-node stats, imbalance score, and roaming events.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    nodes = (
        db.query(EeroNode)
        .filter(EeroNode.network_name == network_name)
        .all()
    )

    if not nodes:
        return {
            "imbalance_score": 0,
            "nodes": [],
            "roaming_events": [],
            "roaming_summary": {"total_events": 0},
        }

    # Per-node device count stats from EeroNodeMetric
    node_stats = []
    device_counts = []

    for node in nodes:
        metrics = (
            db.query(EeroNodeMetric.connected_device_count)
            .filter(
                EeroNodeMetric.eero_node_id == node.id,
                EeroNodeMetric.timestamp >= cutoff,
                EeroNodeMetric.connected_device_count.isnot(None),
            )
            .all()
        )

        counts = [m.connected_device_count for m in metrics]
        avg_devices = round(sum(counts) / len(counts), 1) if counts else 0
        max_devices = max(counts) if counts else 0
        device_counts.append(avg_devices)

        node_stats.append({
            "node_id": node.id,
            "eero_id": node.eero_id,
            "location": node.location,
            "avg_devices": avg_devices,
            "max_devices": max_devices,
            "is_gateway": node.is_gateway or False,
        })

    # Calculate percentage of total and imbalance score
    total_avg = sum(device_counts)
    for stat in node_stats:
        stat["pct_of_total"] = round(
            stat["avg_devices"] / total_avg * 100, 1
        ) if total_avg > 0 else 0

    # Imbalance: coefficient of variation (stddev / mean)
    if len(device_counts) > 1 and total_avg > 0:
        mean = total_avg / len(device_counts)
        variance = sum((c - mean) ** 2 for c in device_counts) / len(device_counts)
        stddev = variance ** 0.5
        imbalance = round(stddev / mean, 2) if mean > 0 else 0
    else:
        imbalance = 0

    # Roaming detection
    roaming = _detect_roaming(db, network_name, nodes, cutoff)

    # Roaming summary
    roaming_by_device = {}
    for event in roaming:
        mac = event["device_mac"]
        roaming_by_device[mac] = roaming_by_device.get(mac, 0) + 1

    most_roaming = None
    if roaming_by_device:
        top_mac = max(roaming_by_device, key=roaming_by_device.get)
        most_roaming = {
            "mac": top_mac,
            "hostname": next(
                (e["hostname"] for e in roaming if e["device_mac"] == top_mac),
                "Unknown",
            ),
            "events": roaming_by_device[top_mac],
        }

    return {
        "imbalance_score": imbalance,
        "nodes": node_stats,
        "roaming_events": roaming[:100],  # Cap at 100 events
        "roaming_summary": {
            "total_events": len(roaming),
            "unique_devices": len(roaming_by_device),
            "most_roaming_device": most_roaming,
        },
    }


def _detect_roaming(
    db: Session,
    network_name: str,
    nodes: List[EeroNode],
    cutoff: datetime,
) -> List[Dict[str, Any]]:
    """Detect device roaming between nodes.

    A roaming event is when a device's connected node changes between
    consecutive DeviceConnection records.
    """
    node_map = {n.id: n for n in nodes}

    # Get all devices on this network
    devices = (
        db.query(Device)
        .filter(Device.network_name == network_name)
        .all()
    )

    roaming_events = []

    for device in devices:
        connections = (
            db.query(
                DeviceConnection.timestamp,
                DeviceConnection.eero_node_id,
            )
            .filter(
                DeviceConnection.device_id == device.id,
                DeviceConnection.timestamp >= cutoff,
                DeviceConnection.eero_node_id.isnot(None),
                DeviceConnection.is_connected == True,
            )
            .order_by(DeviceConnection.timestamp.asc())
            .all()
        )

        prev_node_id = None
        for conn in connections:
            if prev_node_id is not None and conn.eero_node_id != prev_node_id:
                from_node = node_map.get(prev_node_id)
                to_node = node_map.get(conn.eero_node_id)

                roaming_events.append({
                    "device_mac": device.mac_address,
                    "hostname": device.hostname,
                    "from_node": from_node.location if from_node else f"Node {prev_node_id}",
                    "to_node": to_node.location if to_node else f"Node {conn.eero_node_id}",
                    "at": conn.timestamp.isoformat(),
                })
            prev_node_id = conn.eero_node_id

    # Sort by time
    roaming_events.sort(key=lambda e: e["at"], reverse=True)
    return roaming_events
