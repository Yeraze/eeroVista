# API Reference

Complete reference for eeroVista API endpoints.

## Base URL

All API endpoints are relative to your eeroVista instance:
```
http://localhost:8080
```

## Authentication

Currently, all endpoints are unauthenticated. Future versions may add API key authentication.

---

## Web UI Routes

### Dashboard
```
GET /
```

Returns the main dashboard HTML page with network overview, graphs, and statistics.

### Devices List
```
GET /devices
```

Returns HTML page with table of all connected and historical devices.

### Network Topology
```
GET /network
```

Returns HTML page visualizing the mesh network topology.

### Speedtest History
```
GET /speedtest
```

Returns HTML page with historical speedtest results and graphs.

### Settings
```
GET /settings
```

Returns HTML page displaying current configuration (read-only).

---

## JSON API Endpoints

### Health Check
```
GET /api/health
```

**Response** (200 OK):
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 86400,
  "database": "connected",
  "eero_api": "authenticated",
  "last_collection": "2025-10-19T14:30:00Z"
}
```

### List Devices
```
GET /api/devices
```

**Query Parameters**:
- `online` (boolean): Filter by connection status
- `limit` (int): Limit number of results (default: 100)
- `offset` (int): Pagination offset (default: 0)

**Response** (200 OK):
```json
{
  "total": 15,
  "devices": [
    {
      "mac_address": "AA:BB:CC:DD:EE:FF",
      "hostname": "Johns-iPhone",
      "nickname": "John's Phone",
      "device_type": "mobile",
      "is_connected": true,
      "connection_type": "wireless",
      "connected_to_node": "Living Room",
      "signal_strength": -45,
      "ip_address": "192.168.1.100",
      "bandwidth_down_mbps": 125.3,
      "bandwidth_up_mbps": 12.8,
      "first_seen": "2025-10-01T10:00:00Z",
      "last_seen": "2025-10-19T14:30:15Z"
    }
  ]
}
```

### Device Details
```
GET /api/devices/{mac_address}
```

**Path Parameters**:
- `mac_address`: MAC address (URL-encoded, e.g., `AA:BB:CC:DD:EE:FF`)

**Query Parameters**:
- `history_hours` (int): Hours of history to return (default: 24)

**Response** (200 OK):
```json
{
  "device": {
    "mac_address": "AA:BB:CC:DD:EE:FF",
    "hostname": "Johns-iPhone",
    "nickname": "John's Phone",
    "device_type": "mobile",
    "first_seen": "2025-10-01T10:00:00Z",
    "last_seen": "2025-10-19T14:30:15Z"
  },
  "current_connection": {
    "is_connected": true,
    "connection_type": "wireless",
    "connected_to_node": "Living Room",
    "signal_strength": -45,
    "ip_address": "192.168.1.100",
    "bandwidth_down_mbps": 125.3,
    "bandwidth_up_mbps": 12.8
  },
  "history": [
    {
      "timestamp": "2025-10-19T14:30:00Z",
      "is_connected": true,
      "signal_strength": -45,
      "bandwidth_down_mbps": 125.3,
      "bandwidth_up_mbps": 12.8
    }
  ]
}
```

### Network Summary
```
GET /api/network/summary
```

**Response** (200 OK):
```json
{
  "timestamp": "2025-10-19T14:30:00Z",
  "total_devices": 15,
  "devices_online": 12,
  "guest_network_enabled": false,
  "wan_status": "connected",
  "nodes": [
    {
      "eero_id": "12345",
      "location": "Living Room",
      "model": "eero Pro 6E",
      "is_gateway": true,
      "status": "online",
      "connected_devices": 5,
      "uptime_seconds": 604800
    }
  ]
}
```

---

## Prometheus Metrics

### Metrics Endpoint
```
GET /metrics
```

Returns Prometheus-formatted metrics for scraping.

**Response** (200 OK, `text/plain`):
```
# HELP eero_device_connected Device connection status (1=connected, 0=disconnected)
# TYPE eero_device_connected gauge
eero_device_connected{mac="AA:BB:CC:DD:EE:FF",hostname="Johns-iPhone",node="Living Room"} 1

# HELP eero_device_signal_strength WiFi signal strength in dBm
# TYPE eero_device_signal_strength gauge
eero_device_signal_strength{mac="AA:BB:CC:DD:EE:FF",hostname="Johns-iPhone",node="Living Room"} -45

# HELP eero_device_bandwidth_mbps Device bandwidth in Mbps
# TYPE eero_device_bandwidth_mbps gauge
eero_device_bandwidth_mbps{mac="AA:BB:CC:DD:EE:FF",hostname="Johns-iPhone",direction="download"} 125.3
eero_device_bandwidth_mbps{mac="AA:BB:CC:DD:EE:FF",hostname="Johns-iPhone",direction="upload"} 12.8

# HELP eero_network_devices_total Total number of known devices
# TYPE eero_network_devices_total gauge
eero_network_devices_total 15

# HELP eero_network_devices_online Number of currently connected devices
# TYPE eero_network_devices_online gauge
eero_network_devices_online 12

# HELP eero_node_status Eero node status (1=online, 0=offline)
# TYPE eero_node_status gauge
eero_node_status{node="Living Room",location="Living Room",gateway="true"} 1

# HELP eero_node_connected_devices Number of devices connected to this node
# TYPE eero_node_connected_devices gauge
eero_node_connected_devices{node="Living Room"} 5

# HELP eero_speedtest_download_mbps Latest speedtest download speed
# TYPE eero_speedtest_download_mbps gauge
eero_speedtest_download_mbps 950.2

# HELP eero_speedtest_upload_mbps Latest speedtest upload speed
# TYPE eero_speedtest_upload_mbps gauge
eero_speedtest_upload_mbps 45.8

# HELP eero_speedtest_latency_ms Latest speedtest latency
# TYPE eero_speedtest_latency_ms gauge
eero_speedtest_latency_ms 12.4
```

See [Prometheus Integration](prometheus.md) for scrape configuration.

---

## Zabbix Integration

### Device Discovery (LLD)
```
GET /api/zabbix/discovery/devices
```

**Response** (200 OK):
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

### Node Discovery (LLD)
```
GET /api/zabbix/discovery/nodes
```

**Response** (200 OK):
```json
{
  "data": [
    {
      "{#NODE_ID}": "12345",
      "{#NODE_NAME}": "Living Room",
      "{#NODE_MODEL}": "eero Pro 6E",
      "{#IS_GATEWAY}": "true"
    }
  ]
}
```

### Zabbix Data
```
GET /api/zabbix/data
```

**Query Parameters** (one required):
- `item=device.connected[MAC]` - Device connection status (0 or 1)
- `item=device.signal[MAC]` - Signal strength in dBm
- `item=device.bandwidth.down[MAC]` - Download bandwidth in Mbps
- `item=device.bandwidth.up[MAC]` - Upload bandwidth in Mbps
- `item=network.devices.total` - Total devices
- `item=network.devices.online` - Online devices
- `item=speedtest.download` - Latest speedtest download (Mbps)
- `item=speedtest.upload` - Latest speedtest upload (Mbps)
- `item=speedtest.latency` - Latest speedtest latency (ms)

**Example**:
```
GET /api/zabbix/data?item=device.connected[AA:BB:CC:DD:EE:FF]
```

**Response** (200 OK):
```json
{
  "value": 1,
  "timestamp": "2025-10-19T14:30:00Z"
}
```

See [Zabbix Integration](zabbix.md) for template setup.

---

## Error Responses

All endpoints may return the following error responses:

### 400 Bad Request
```json
{
  "error": "Invalid parameter",
  "message": "MAC address must be in format AA:BB:CC:DD:EE:FF"
}
```

### 404 Not Found
```json
{
  "error": "Device not found",
  "message": "No device with MAC address AA:BB:CC:DD:EE:FF"
}
```

### 500 Internal Server Error
```json
{
  "error": "Database error",
  "message": "Failed to query database"
}
```

### 503 Service Unavailable
```json
{
  "error": "Eero API unavailable",
  "message": "Authentication failed or API rate limited"
}
```

---

## Rate Limiting

eeroVista does not currently implement rate limiting on its API endpoints. However, the underlying Eero API has rate limits that may affect data collection frequency.

**Recommendations**:
- Prometheus scrape interval: 30-60 seconds
- Zabbix polling interval: 60 seconds
- Custom API polling: 30-60 seconds

---

## Future Endpoints

Planned for future releases:

### CSV Export
```
GET /api/export/devices.csv
GET /api/export/speedtests.csv
```

### Webhook Notifications
```
POST /api/webhooks
```

### Advanced Filtering
```
GET /api/devices?node=Living+Room&type=mobile&since=2025-10-01
```
