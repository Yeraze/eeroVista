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

### Device Groups

#### List Device Groups
```
GET /api/device-groups
```

**Query Parameters**:
- `network` (string): Network name (defaults to first available network)

**Response** (200 OK):
```json
[
  {
    "id": 1,
    "network_name": "My Network",
    "name": "Desktop PC",
    "device_ids": [42, 43]
  }
]
```

#### Create Device Group
```
POST /api/device-groups
```

**Request Body**:
```json
{
  "network_name": "My Network",
  "name": "Desktop PC",
  "mac_addresses": ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]
}
```

**Response** (201 Created):
```json
{
  "id": 1,
  "network_name": "My Network",
  "name": "Desktop PC",
  "device_ids": [42, 43]
}
```

**Errors**:
- `400` if any MAC address is not found on the specified network
- `400` if a device is already in another group

#### Update Device Group
```
PUT /api/device-groups/{group_id}
```

**Request Body** (all fields optional):
```json
{
  "name": "New Name",
  "mac_addresses": ["AA:BB:CC:DD:EE:FF", "11:22:33:44:55:66"]
}
```

**Response** (200 OK): Same format as create response.

#### Delete Device Group
```
DELETE /api/device-groups/{group_id}
```

**Response** (204 No Content): Group is deleted, member devices become ungrouped.

---

## Notification Endpoints

### Notification Settings

#### Get Notification Settings
```
GET /api/notification-settings
```

**Response** (200 OK):
```json
{
  "apprise_urls": "slack://token discord://webhook",
  "configured": true
}
```

#### Update Notification Settings
```
PUT /api/notification-settings
```

**Request Body**:
```json
{
  "apprise_urls": "slack://tokenA/tokenB/tokenC discord://webhook email://user:pass@smtp.example.com"
}
```

Apprise URLs are space-separated. See [Apprise documentation](https://github.com/caronc/apprise/wiki) for supported services (100+ including email, Slack, Discord, Telegram, Microsoft Teams, webhooks, and more).

**Response** (200 OK): Same format as GET response.

### Notification Rules

#### List Notification Rules
```
GET /api/notification-rules
```

**Query Parameters**:
- `network` (string): Filter by network name

**Response** (200 OK):
```json
[
  {
    "id": 1,
    "network_name": "My Network",
    "rule_type": "node_offline",
    "enabled": true,
    "config_json": "{\"node_ids\": [1, 2]}",
    "cooldown_minutes": 60,
    "created_at": "2025-10-19T14:00:00",
    "updated_at": null
  }
]
```

#### Create Notification Rule
```
POST /api/notification-rules
```

**Request Body**:
```json
{
  "network_name": "My Network",
  "rule_type": "node_offline",
  "config_json": "{\"node_ids\": [1, 2]}",
  "cooldown_minutes": 60,
  "enabled": true
}
```

**Rule Types**:
| Type | Description | Config Fields |
|------|-------------|---------------|
| `node_offline` | Alert when mesh nodes go offline | `node_ids` (list of node IDs) |
| `device_offline` | Alert when specific devices go offline | `device_ids` (list of device IDs) |
| `new_device` | Alert when a new device connects | (none) |
| `high_bandwidth` | Alert when bandwidth exceeds threshold | `threshold_down_mbps`, `threshold_up_mbps` |
| `firmware_update` | Alert when firmware updates are available | (none) |

**Response** (201 Created): Same format as list item.

**Errors**:
- `400` if rule_type is invalid
- `400` if config_json is not valid JSON

#### Update Notification Rule
```
PUT /api/notification-rules/{rule_id}
```

**Request Body** (all fields optional):
```json
{
  "enabled": false,
  "config_json": "{\"node_ids\": [1]}",
  "cooldown_minutes": 120
}
```

**Response** (200 OK): Same format as list item.

#### Delete Notification Rule
```
DELETE /api/notification-rules/{rule_id}
```

**Response** (204 No Content): Rule and its history are deleted.

### Test Notification
```
POST /api/notifications/test
```

**Request Body**:
```json
{
  "message": "This is a test notification from eeroVista"
}
```

**Response** (200 OK):
```json
{
  "success": true,
  "message": "Test notification sent successfully"
}
```

**Errors**:
- `400` if no Apprise URLs are configured
- `500` if notification delivery fails

### Notification Configuration Helpers

#### List Available Networks
```
GET /api/notification-config/networks
```

Returns network names for populating rule configuration dropdowns.

#### List Nodes
```
GET /api/notification-config/nodes
```

**Query Parameters**:
- `network` (string): Filter by network name

Returns node list with IDs for configuring `node_offline` rules.

#### List Devices
```
GET /api/notification-config/devices
```

**Query Parameters**:
- `network` (string): Filter by network name

Returns device list with IDs for configuring `device_offline` rules.

### Notification History
```
GET /api/notification-history
```

**Query Parameters**:
- `limit` (int): Number of entries (default: 50, max: 200)

**Response** (200 OK):
```json
[
  {
    "id": 1,
    "rule_id": 3,
    "event_key": "node_offline:12345",
    "message": "Node 'Living Room' is offline",
    "sent_at": "2025-10-19T14:30:00",
    "resolved_at": "2025-10-19T14:35:00"
  }
]
```

---

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

## Analytics & Reports Endpoints

### Network Health Score
```
GET /api/network/health-score
```

**Query Parameters**:
- `network` (string): Network name (defaults to first available)

**Response** (200 OK):
```json
{
  "score": 92.6,
  "color": "green",
  "components": {
    "wan_uptime": {"score": 100.0, "weight": 0.3},
    "node_availability": {"score": 100.0, "weight": 0.25},
    "mesh_quality": {"score": 99.7, "weight": 0.25},
    "signal_quality": {"score": 63.2, "weight": 0.2}
  },
  "window_minutes": 60
}
```

Score color thresholds: green (>=80), yellow (50-80), red (<50).

### Health Score History
```
GET /api/network/health-history
```

**Query Parameters**:
- `hours` (int): Hours to look back (default: 168, max: 720)
- `network` (string): Network name

**Response** (200 OK):
```json
{
  "history": [
    {"timestamp": "2025-10-19T14:00:00", "score": 95.2}
  ]
}
```

### WAN Uptime
```
GET /api/network/uptime
```

**Query Parameters**:
- `network` (string): Network name

**Response** (200 OK):
```json
{
  "uptime_24h_pct": 99.8,
  "uptime_7d_pct": 99.2,
  "uptime_30d_pct": 98.5,
  "total_outages_30d": 4,
  "total_downtime_minutes_30d": 65.0,
  "longest_outage_minutes": 25.0
}
```

### Outage Events
```
GET /api/network/outages
```

**Query Parameters**:
- `days` (int): Days to look back (default: 30, max: 365)
- `network` (string): Network name

**Response** (200 OK):
```json
{
  "outages": [
    {"start": "2025-10-14T02:15:00", "end": "2025-10-14T02:40:00", "duration_minutes": 25.0}
  ],
  "daily_uptime": [
    {"date": "2025-10-14", "uptime_pct": 98.3, "outage_count": 1}
  ],
  "period_days": 30
}
```

### Bandwidth Summary Report
```
GET /api/reports/bandwidth-summary
```

**Query Parameters**:
- `period` (string): `week` or `month` (required)
- `offset` (int): Periods back, 0=current (default: 0)
- `network` (string): Network name

**Response** (200 OK):
```json
{
  "period": "2025-10-13 to 2025-10-19",
  "previous_period": "2025-10-06 to 2025-10-12",
  "total_download_gb": 145.2,
  "total_upload_gb": 23.8,
  "total_gb": 169.0,
  "change_vs_previous": {"download_pct": 12.3, "upload_pct": -5.1, "total_pct": 8.2},
  "top_devices": [
    {"hostname": "Gaming-PC", "nickname": "Gaming PC", "mac_address": "AA:BB:CC:DD:EE:FF", "download_gb": 45.2, "upload_gb": 8.1, "total_gb": 53.3, "pct_of_total": 31.1}
  ],
  "daily_breakdown": [
    {"date": "2025-10-13", "day": "Monday", "download_gb": 20.1, "upload_gb": 3.2, "total_gb": 23.3}
  ],
  "peak_day": {"date": "2025-10-15", "day": "Wednesday", "total_gb": 28.5}
}
```

### Node Restart History
```
GET /api/nodes/{eero_id}/restart-history
```

**Query Parameters**:
- `days` (int): Days to look back (default: 30, max: 365)
- `network` (string): Network name

**Response** (200 OK):
```json
{
  "node_id": 1,
  "node_name": "Living Room",
  "restarts": [
    {"detected_at": "2025-10-15T03:22:00", "estimated_restart_at": "2025-10-15T03:20:00", "previous_uptime_seconds": 604800}
  ],
  "total_restarts": 3,
  "mean_time_between_restarts_hours": 168.5,
  "period_days": 30
}
```

### Node Restart Summary
```
GET /api/nodes/restart-summary
```

Returns restart counts for all nodes in a network.

### Signal Strength History
```
GET /api/devices/{mac_address}/signal-history
```

**Query Parameters**:
- `hours` (int): Hours to look back (default: 168, max: 720)
- `network` (string): Network name

**Response** (200 OK):
```json
{
  "mac": "AA:BB:CC:DD:EE:FF",
  "hostname": "iPhone",
  "stats": {"mean": -52.3, "min": -71, "max": -38, "stddev": 8.2, "count": 500},
  "quality_band": "good",
  "trend": "stable",
  "history": [
    {"timestamp": "2025-10-19T10:00:00", "signal_strength": -48}
  ]
}
```

**Quality Bands**: excellent (> -50 dBm), good (-50 to -65), fair (-65 to -75), poor (< -75)

**Trend Values**: `stable`, `degrading`, `improving`, `unknown`

### Signal Quality Summary
```
GET /api/devices/signal-summary
```

Returns network-wide signal quality: device counts per quality band and list of devices with degrading signal.

### Speedtest Analysis
```
GET /api/speedtest/analysis
```

**Query Parameters**:
- `days` (int): Days to analyze (default: 30, max: 365)
- `network` (string): Network name

**Response** (200 OK):
```json
{
  "period_days": 30,
  "test_count": 45,
  "avg_download_mbps": 285.3,
  "avg_upload_mbps": 22.1,
  "avg_latency_ms": 12.5,
  "time_of_day_pattern": [
    {"hour": 0, "avg_download": 310.2, "test_count": 3}
  ],
  "day_of_week_pattern": [
    {"day": "Monday", "avg_download": 295.0, "test_count": 7}
  ],
  "trend": "stable"
}
```

### Device Activity Pattern
```
GET /api/devices/{mac_address}/activity-pattern
```

**Query Parameters**:
- `days` (int): Days to analyze (default: 7, max: 30)
- `network` (string): Network name

**Response** (200 OK):
```json
{
  "mac": "AA:BB:CC:DD:EE:FF",
  "hostname": "iPhone",
  "heatmap": [
    {"day": "Monday", "hours": [0.0, 0.0, null, 0.5, 1.0, 1.0, "..."]}
  ],
  "total_readings": 1200,
  "period_days": 7
}
```

Each value in `hours` is a connection probability (0.0-1.0) or `null` if no data.

### Node Load Analysis
```
GET /api/nodes/load-analysis
```

**Query Parameters**:
- `hours` (int): Hours to analyze (default: 24, max: 720)
- `network` (string): Network name

**Response** (200 OK):
```json
{
  "imbalance_score": 0.35,
  "nodes": [
    {"node_id": 1, "eero_id": "12345", "location": "Living Room", "avg_devices": 12.3, "max_devices": 18, "pct_of_total": 45.2, "is_gateway": true}
  ],
  "roaming_events": [
    {"device_mac": "AA:BB:CC:DD:EE:FF", "hostname": "Laptop", "from_node": "Office", "to_node": "Living Room", "at": "2025-10-19T14:30:00"}
  ],
  "roaming_summary": {"total_events": 23, "unique_devices": 8, "most_roaming_device": {"mac": "AA:BB:CC:DD:EE:FF", "hostname": "Laptop", "events": 5}}
}
```

### Guest Network Usage
```
GET /api/network/guest-usage
```

**Query Parameters**:
- `hours` (int): Hours to look back (default: 24, max: 720)
- `network` (string): Network name

**Response** (200 OK):
```json
{
  "hours": 24,
  "guest_device_count": 3,
  "guest_devices": [
    {"hostname": "Guest-Phone", "mac": "AA:BB:CC:DD:EE:FF", "type": "mobile"}
  ],
  "guest_bandwidth_down_mbps": 125.3,
  "guest_bandwidth_up_mbps": 12.8,
  "guest_pct_of_total": 15.2,
  "non_guest_pct_of_total": 84.8
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

# HELP eero_network_health_score Overall network health score (0-100)
# TYPE eero_network_health_score gauge
eero_network_health_score{network="My Network"} 92.6

# HELP eero_network_wan_uptime_pct WAN uptime percentage
# TYPE eero_network_wan_uptime_pct gauge
eero_network_wan_uptime_pct{network="My Network",window="24h"} 99.8
eero_network_wan_uptime_pct{network="My Network",window="7d"} 99.2
eero_network_wan_uptime_pct{network="My Network",window="30d"} 98.5

# HELP eero_node_restarts_30d Detected node restarts in last 30 days
# TYPE eero_node_restarts_30d gauge
eero_node_restarts_30d{network="My Network",node_id="12345",location="Living Room"} 0
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

### Advanced Filtering
```
GET /api/devices?node=Living+Room&type=mobile&since=2025-10-01
```
