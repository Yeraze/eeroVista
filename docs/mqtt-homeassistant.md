---
layout: default
title: MQTT / Home Assistant
nav_order: 6
---

# MQTT / Home Assistant Integration

eeroVista can publish network data to an MQTT broker, enabling automatic discovery in Home Assistant and other MQTT-compatible platforms.

## Prerequisites

- An MQTT broker (e.g., [Mosquitto](https://mosquitto.org/))
- Home Assistant with MQTT integration configured (pointing to the same broker)

## Configuration

MQTT is **disabled by default**. Enable it by setting environment variables in your `docker-compose.yml`:

```yaml
environment:
  - MQTT_ENABLED=true
  - MQTT_BROKER=192.168.1.100     # Your MQTT broker IP/hostname
  - MQTT_PORT=1883                 # Broker port (default: 1883)
  - MQTT_USERNAME=                 # Optional: broker username
  - MQTT_PASSWORD=                 # Optional: broker password
  - MQTT_TOPIC_PREFIX=eerovista    # Topic prefix (default: eerovista)
  - MQTT_DISCOVERY_PREFIX=homeassistant  # HA discovery prefix (default: homeassistant)
  - MQTT_PUBLISH_INTERVAL=60      # Publish interval in seconds (default: 60)
  - MQTT_QOS=1                    # MQTT QoS level: 0, 1, or 2 (default: 1)
  - MQTT_RETAIN=true              # Retain messages (default: true)
  - MQTT_CLIENT_ID=eerovista      # Client ID (default: eerovista)
```

## Home Assistant Auto-Discovery

When MQTT is enabled, eeroVista automatically publishes [Home Assistant MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery) payloads. Entities appear automatically in HA without manual configuration.

### Entities Created

#### Network Sensors
- **Total Devices** — Total number of known devices
- **Devices Online** — Currently connected devices
- **WAN Status** — Internet connection status

#### Speedtest Sensors
- **Speedtest Download** — Latest download speed (Mbps)
- **Speedtest Upload** — Latest upload speed (Mbps)
- **Speedtest Latency** — Latest latency (ms)

#### Per Eero Node
Each eero node in your mesh creates:
- **Status** — Online/offline (binary sensor)
- **Connected Devices** — Number of connected clients
- **Mesh Quality** — Signal quality (1-5 bars)
- **Uptime** — Node uptime in seconds
- **Update Available** — Firmware update available (binary sensor)

#### Per Client Device
Each connected device creates:
- **Connected** — Online/offline (binary sensor)
- **Signal Strength** — WiFi signal in dBm
- **Download Rate** — Current download rate (Mbps)
- **Upload Rate** — Current upload rate (Mbps)
- **IP Address** — Current IP address

## MQTT Topic Structure

```
eerovista/status                              # "online" or "offline"
eerovista/{network}/network                   # Network-wide metrics (JSON)
eerovista/{network}/speedtest                 # Latest speedtest results (JSON)
eerovista/{network}/node/{node_id}            # Per-node metrics (JSON)
eerovista/{network}/device/{mac_address}      # Per-device metrics (JSON)
```

MAC addresses in topics use underscores instead of colons (e.g., `AA_BB_CC_DD_EE_FF`).

## Example Payloads

### Network State
```json
{
  "total_devices": 15,
  "devices_online": 12,
  "wan_status": "online",
  "guest_network": false,
  "connection_mode": "automatic"
}
```

### Node State
```json
{
  "status": "online",
  "connected_devices": 5,
  "connected_wired": 2,
  "connected_wireless": 3,
  "mesh_quality": 5,
  "uptime_seconds": 86400,
  "update_available": "false",
  "location": "Living Room",
  "model": "eero Pro 6E",
  "is_gateway": true,
  "firmware": "7.2.0"
}
```

### Device State
```json
{
  "connected": "true",
  "connection_type": "wireless",
  "signal_strength": -45,
  "ip_address": "192.168.1.100",
  "bandwidth_down_mbps": 25.5,
  "bandwidth_up_mbps": 10.2,
  "node": "Living Room",
  "hostname": "my-laptop",
  "nickname": "My Laptop",
  "mac": "AA:BB:CC:DD:EE:FF"
}
```

## Availability

eeroVista publishes an availability topic at `{prefix}/status`. When eeroVista starts, it publishes `online`. On graceful shutdown (or if the broker detects a disconnect via the MQTT last-will), it publishes `offline`. Home Assistant uses this to show entity availability.

## Troubleshooting

### Entities not appearing in Home Assistant
1. Verify MQTT broker is reachable from the eeroVista container
2. Check that `MQTT_DISCOVERY_PREFIX` matches your HA MQTT config (default: `homeassistant`)
3. Look for MQTT connection errors in eeroVista logs (`LOG_LEVEL=DEBUG`)
4. Verify the broker allows the configured username/password

### Stale data
- eeroVista publishes at the configured `MQTT_PUBLISH_INTERVAL` (default: 60s)
- Data is read from the local database, which is updated by collectors at their own intervals
- Retained messages ensure HA has the last known state even after restart

### Multiple eeroVista instances
Use unique `MQTT_CLIENT_ID` and `MQTT_TOPIC_PREFIX` values for each instance to avoid conflicts.
