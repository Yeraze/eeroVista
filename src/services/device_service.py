"""Device list building and group aggregation service."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from src.models.database import Device, DeviceConnection, DeviceGroup, DeviceGroupMember, EeroNode

logger = logging.getLogger(__name__)


def _aggregate_group(group, member_entries):
    """Aggregate stats for a group of devices into a single entry."""
    bandwidth_down = sum(m.get("bandwidth_down_mbps") or 0 for m in member_entries)
    bandwidth_up = sum(m.get("bandwidth_up_mbps") or 0 for m in member_entries)

    signals = [m["signal_strength"] for m in member_entries if m.get("signal_strength") is not None]
    best_signal = max(signals) if signals else None

    is_online = any(m.get("is_online") for m in member_entries)

    conn_types = sorted({(m.get("connection_type") or "").capitalize() for m in member_entries if m.get("connection_type")})
    connection_type = " + ".join(conn_types) if conn_types else "Unknown"

    ips = [m["ip_address"] for m in member_entries if m.get("ip_address") and m["ip_address"] != "N/A"]
    ip_address = ", ".join(ips) if ips else None

    is_guest = any(m.get("is_guest") for m in member_entries)

    return {
        "name": group.name,
        "nickname": None,
        "hostname": None,
        "manufacturer": None,
        "type": "group",
        "ip_address": ip_address,
        "is_online": is_online,
        "is_guest": is_guest,
        "connection_type": connection_type,
        "signal_strength": best_signal,
        "bandwidth_down_mbps": bandwidth_down,
        "bandwidth_up_mbps": bandwidth_up,
        "node": ", ".join(sorted({m["node"] for m in member_entries if m.get("node") and m["node"] != "N/A"})) or "N/A",
        "mac_address": None,
        "last_seen": max((m["last_seen"] for m in member_entries if m.get("last_seen")), default=None),
        "aliases": None,
        "group_id": group.id,
        "group_name": group.name,
        "group_members": member_entries,
    }


def build_devices_list(db: Session, network_name: str) -> List[Dict]:
    """Build list of devices with their latest connection status, aggregating grouped devices.

    Args:
        db: Database session.
        network_name: Network name to filter devices by.

    Returns:
        List of device dicts, with grouped devices aggregated into single entries.
    """
    # Get all devices for this network
    devices = db.query(Device).filter(Device.network_name == network_name).all()
    device_ids = [d.id for d in devices]

    if not device_ids:
        return []

    # Get latest connection for each device
    latest_subq = db.query(
        DeviceConnection.device_id,
        func.max(DeviceConnection.timestamp).label('max_timestamp')
    ).filter(
        DeviceConnection.device_id.in_(device_ids)
    ).group_by(DeviceConnection.device_id).subquery()

    connections = db.query(DeviceConnection, EeroNode).join(
        latest_subq,
        and_(
            DeviceConnection.device_id == latest_subq.c.device_id,
            DeviceConnection.timestamp == latest_subq.c.max_timestamp
        )
    ).outerjoin(
        EeroNode,
        EeroNode.id == DeviceConnection.eero_node_id
    ).all()

    connection_map = {}
    for conn, node in connections:
        connection_map[conn.device_id] = (conn, node)

    # Get bandwidth fallback data for devices missing it
    devices_needing_bandwidth = [
        d_id for d_id, (conn, _) in connection_map.items()
        if conn and conn.bandwidth_down_mbps is None and conn.bandwidth_up_mbps is None
    ]

    bandwidth_map = {}
    if devices_needing_bandwidth:
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=2)

        bandwidth_subq = db.query(
            DeviceConnection.device_id,
            func.max(DeviceConnection.timestamp).label('max_timestamp')
        ).filter(
            DeviceConnection.device_id.in_(devices_needing_bandwidth),
            DeviceConnection.timestamp >= cutoff_time,
            (DeviceConnection.bandwidth_down_mbps.isnot(None)) | (DeviceConnection.bandwidth_up_mbps.isnot(None))
        ).group_by(DeviceConnection.device_id).subquery()

        bandwidth_connections = db.query(DeviceConnection).join(
            bandwidth_subq,
            and_(
                DeviceConnection.device_id == bandwidth_subq.c.device_id,
                DeviceConnection.timestamp == bandwidth_subq.c.max_timestamp
            )
        ).all()

        for conn in bandwidth_connections:
            bandwidth_map[conn.device_id] = (conn.bandwidth_down_mbps, conn.bandwidth_up_mbps)

    # Build devices list
    devices_list = []
    for device in devices:
        conn, node = connection_map.get(device.id, (None, None))
        node_name = node.location if node else None
        connection_type = "unknown"
        ip_address = "N/A"
        is_online = False
        is_guest = False
        signal_strength = None
        bandwidth_down = None
        bandwidth_up = None

        if conn:
            ip_address = conn.ip_address or "N/A"
            is_online = conn.is_connected or False
            connection_type = conn.connection_type or "unknown"
            is_guest = conn.is_guest or False
            signal_strength = conn.signal_strength
            bandwidth_down = conn.bandwidth_down_mbps
            bandwidth_up = conn.bandwidth_up_mbps

            if bandwidth_down is None and bandwidth_up is None and device.id in bandwidth_map:
                bandwidth_down, bandwidth_up = bandwidth_map[device.id]

        device_name = device.nickname or device.hostname or device.manufacturer or device.mac_address

        aliases = []
        if device.aliases:
            try:
                aliases = json.loads(device.aliases)
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON in aliases for device {device.mac_address}")

        devices_list.append({
            "device_id": device.id,
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

    # Aggregate grouped devices
    groups = db.query(DeviceGroup).filter(DeviceGroup.network_name == network_name).all()
    if groups:
        device_id_map = {d["device_id"]: d for d in devices_list if d.get("device_id")}
        grouped_device_ids = set()
        group_entries = []
        for group in groups:
            member_device_ids = {m.device_id for m in group.members}
            member_entries = [device_id_map[did] for did in member_device_ids if did in device_id_map]
            if not member_entries:
                continue
            grouped_device_ids.update(member_device_ids)
            group_entries.append(_aggregate_group(group, member_entries))

        devices_list = [d for d in devices_list if d.get("device_id") not in grouped_device_ids]
        devices_list.extend(group_entries)

    return devices_list
