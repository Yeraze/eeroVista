"""Home Assistant MQTT auto-discovery payload builders."""

from typing import Any


def _device_info(network: str) -> dict[str, Any]:
    """Base device info for the eeroVista integration."""
    return {
        "identifiers": [f"eerovista_{network}"],
        "name": f"eeroVista ({network})",
        "manufacturer": "eeroVista",
        "model": "Network Monitor",
        "sw_version": None,  # Filled by caller
    }


def _node_device_info(network: str, node_id: str, location: str, model: str) -> dict[str, Any]:
    """Device info for an individual eero node."""
    return {
        "identifiers": [f"eerovista_node_{node_id}"],
        "name": f"Eero {location}",
        "manufacturer": "eero",
        "model": model or "Eero",
        "via_device": f"eerovista_{network}",
    }


def _client_device_info(network: str, mac: str, name: str) -> dict[str, Any]:
    """Device info for a connected client device."""
    return {
        "identifiers": [f"eerovista_device_{mac}"],
        "name": name,
        "via_device": f"eerovista_{network}",
    }


def network_discovery_payloads(
    prefix: str,
    discovery_prefix: str,
    network: str,
    version: str,
) -> list[tuple[str, dict]]:
    """Build HA discovery payloads for network-wide sensors.

    Returns list of (topic, payload) tuples.
    """
    dev = _device_info(network)
    dev["sw_version"] = version
    base_topic = f"{prefix}/{network}"
    uid_prefix = f"eerovista_{network}"
    results = []

    sensors = [
        ("devices_total", "Total Devices", "total_devices", None, "mdi:devices"),
        ("devices_online", "Devices Online", "devices_online", None, "mdi:wifi"),
        ("wan_status", "WAN Status", "wan_status", None, "mdi:web"),
    ]

    for sensor_id, name, value_key, device_class, icon in sensors:
        uid = f"{uid_prefix}_{sensor_id}"
        topic = f"{discovery_prefix}/sensor/{uid}/config"
        payload = {
            "unique_id": uid,
            "name": name,
            "state_topic": f"{base_topic}/network",
            "value_template": f"{{{{ value_json.{value_key} }}}}",
            "device": dev,
            "availability_topic": f"{prefix}/status",
            "icon": icon,
        }
        if device_class:
            payload["device_class"] = device_class
        results.append((topic, payload))

    return results


def speedtest_discovery_payloads(
    prefix: str,
    discovery_prefix: str,
    network: str,
    version: str,
) -> list[tuple[str, dict]]:
    """Build HA discovery payloads for speedtest sensors."""
    dev = _device_info(network)
    dev["sw_version"] = version
    base_topic = f"{prefix}/{network}"
    uid_prefix = f"eerovista_{network}"
    results = []

    sensors = [
        ("speedtest_download", "Speedtest Download", "download_mbps", "data_rate", "Mbps", "mdi:download"),
        ("speedtest_upload", "Speedtest Upload", "upload_mbps", "data_rate", "Mbps", "mdi:upload"),
        ("speedtest_latency", "Speedtest Latency", "latency_ms", "duration", "ms", "mdi:timer"),
    ]

    for sensor_id, name, value_key, device_class, unit, icon in sensors:
        uid = f"{uid_prefix}_{sensor_id}"
        topic = f"{discovery_prefix}/sensor/{uid}/config"
        payload = {
            "unique_id": uid,
            "name": name,
            "state_topic": f"{base_topic}/speedtest",
            "value_template": f"{{{{ value_json.{value_key} }}}}",
            "unit_of_measurement": unit,
            "device": dev,
            "availability_topic": f"{prefix}/status",
            "icon": icon,
        }
        if device_class:
            payload["device_class"] = device_class
        results.append((topic, payload))

    return results


def node_discovery_payloads(
    prefix: str,
    discovery_prefix: str,
    network: str,
    node_id: str,
    location: str,
    model: str,
) -> list[tuple[str, dict]]:
    """Build HA discovery payloads for an eero node."""
    dev = _node_device_info(network, node_id, location, model)
    state_topic = f"{prefix}/{network}/node/{node_id}"
    uid_prefix = f"eerovista_node_{node_id}"
    results = []

    # Binary sensor for online/offline
    uid = f"{uid_prefix}_status"
    topic = f"{discovery_prefix}/binary_sensor/{uid}/config"
    results.append((topic, {
        "unique_id": uid,
        "name": "Status",
        "state_topic": state_topic,
        "value_template": "{{ value_json.status }}",
        "payload_on": "online",
        "payload_off": "offline",
        "device_class": "connectivity",
        "device": dev,
        "availability_topic": f"{prefix}/status",
    }))

    sensors = [
        ("connected_devices", "Connected Devices", "connected_devices", None, None, "mdi:devices"),
        ("mesh_quality", "Mesh Quality", "mesh_quality", None, "bars", "mdi:signal"),
        ("uptime", "Uptime", "uptime_seconds", "duration", "s", "mdi:clock-outline"),
    ]

    for sensor_id, name, value_key, device_class, unit, icon in sensors:
        uid = f"{uid_prefix}_{sensor_id}"
        topic = f"{discovery_prefix}/sensor/{uid}/config"
        payload = {
            "unique_id": uid,
            "name": name,
            "state_topic": state_topic,
            "value_template": f"{{{{ value_json.{value_key} }}}}",
            "device": dev,
            "availability_topic": f"{prefix}/status",
            "icon": icon,
        }
        if device_class:
            payload["device_class"] = device_class
        if unit:
            payload["unit_of_measurement"] = unit
        results.append((topic, payload))

    # Update available binary sensor
    uid = f"{uid_prefix}_update"
    topic = f"{discovery_prefix}/binary_sensor/{uid}/config"
    results.append((topic, {
        "unique_id": uid,
        "name": "Update Available",
        "state_topic": state_topic,
        "value_template": "{{ value_json.update_available }}",
        "payload_on": "true",
        "payload_off": "false",
        "device_class": "update",
        "device": dev,
        "availability_topic": f"{prefix}/status",
    }))

    return results


def device_discovery_payloads(
    prefix: str,
    discovery_prefix: str,
    network: str,
    mac: str,
    name: str,
) -> list[tuple[str, dict]]:
    """Build HA discovery payloads for a connected client device."""
    safe_mac = mac.replace(":", "_")
    dev = _client_device_info(network, mac, name)
    state_topic = f"{prefix}/{network}/device/{safe_mac}"
    uid_prefix = f"eerovista_device_{safe_mac}"
    results = []

    # Connected binary sensor
    uid = f"{uid_prefix}_connected"
    topic = f"{discovery_prefix}/binary_sensor/{uid}/config"
    results.append((topic, {
        "unique_id": uid,
        "name": "Connected",
        "state_topic": state_topic,
        "value_template": "{{ value_json.connected }}",
        "payload_on": "true",
        "payload_off": "false",
        "device_class": "connectivity",
        "device": dev,
        "availability_topic": f"{prefix}/status",
    }))

    sensors = [
        ("signal", "Signal Strength", "signal_strength", "signal_strength", "dBm", "mdi:wifi"),
        ("bandwidth_down", "Download Rate", "bandwidth_down_mbps", "data_rate", "Mbps", "mdi:download"),
        ("bandwidth_up", "Upload Rate", "bandwidth_up_mbps", "data_rate", "Mbps", "mdi:upload"),
        ("ip", "IP Address", "ip_address", None, None, "mdi:ip-network"),
    ]

    for sensor_id, sensor_name, value_key, device_class, unit, icon in sensors:
        uid = f"{uid_prefix}_{sensor_id}"
        topic = f"{discovery_prefix}/sensor/{uid}/config"
        payload = {
            "unique_id": uid,
            "name": sensor_name,
            "state_topic": state_topic,
            "value_template": f"{{{{ value_json.{value_key} }}}}",
            "device": dev,
            "availability_topic": f"{prefix}/status",
            "icon": icon,
        }
        if device_class:
            payload["device_class"] = device_class
        if unit:
            payload["unit_of_measurement"] = unit
        results.append((topic, payload))

    return results
