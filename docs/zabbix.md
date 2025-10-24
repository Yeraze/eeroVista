# Zabbix Integration

Guide for integrating eeroVista with Zabbix for network monitoring and alerting.

## Overview

eeroVista provides Zabbix-compatible endpoints for:
- Low-Level Discovery (LLD) of devices and nodes
- Metric collection via Zabbix Agent
- Network topology monitoring
- **Multi-network support** (filter metrics by network)

## Multi-Network Support

**New in v2.0+**: All Zabbix endpoints now support filtering by network name.

If you have multiple Eero networks (e.g., home and office), you can:
- Use the `network` query parameter to filter devices, nodes, and metrics by network
- Create separate Zabbix hosts for each network
- Monitor all networks independently

**Query Parameter**: Add `?network=NetworkName` to any Zabbix endpoint URL.

**Backwards Compatibility**: If the `network` parameter is not specified, eeroVista defaults to the first available network.

**Example URLs**:
```
# Default (first network)
http://eerovista:8080/api/zabbix/discovery/devices

# Specific network
http://eerovista:8080/api/zabbix/discovery/devices?network=Home
http://eerovista:8080/api/zabbix/data?item=network.devices.total&network=Office
```

## Architecture

```
┌──────────┐    HTTP      ┌───────────┐    Eero API    ┌──────────┐
│  Zabbix  │──────────────> eeroVista │──────────────> │   Eero   │
│  Server  │    polls     │           │    queries     │  Network │
└──────────┘              └───────────┘                └──────────┘
```

## Setup Overview

1. Import eeroVista template to Zabbix
2. Create host for eeroVista instance
3. Link template to host
4. Configure discovery rules
5. Set up triggers and alerts

## Zabbix Templates

eeroVista provides two pre-built Zabbix templates to fit different network sizes and monitoring preferences.

### Template Options

#### 1. Single-Host Monitoring (Recommended for Small Networks)

**File**: [`templates/zabbix_template_eerovista.xml`](https://github.com/Yeraze/eeroVista/blob/main/templates/zabbix_template_eerovista.xml)

**Best for**: Networks with <50 devices

**What it does**:
- Creates one Zabbix host with many items
- Network-wide metrics (total/online devices, WAN status, speedtest)
- Per-device and per-node items via Low-Level Discovery
- Simpler setup, less Zabbix overhead

**Quick Import**:
```bash
# Download the template
wget https://raw.githubusercontent.com/Yeraze/eeroVista/main/templates/zabbix_template_eerovista.xml

# Then import via Zabbix web interface:
# Configuration → Templates → Import
```

#### 2. Auto-Discovery with Individual Hosts (Recommended for Large Networks)

**File**: [`templates/zabbix_template_eerovista_complete.xml`](https://github.com/Yeraze/eeroVista/blob/main/templates/zabbix_template_eerovista_complete.xml)

**Best for**: Networks with 50+ devices, or when you want granular host-level management

**What it does**:
- **Automatically creates individual Zabbix hosts** for each discovered device and node
- Device hosts: `eeroVista-Device-{hostname}`
- Node hosts: `eeroVista-Node-{nodename}`
- Zabbix inventory mode enabled with MAC addresses, device types, models available via macros
- Better organization for Maps, Mass Updates, and SLA reporting
- **Requires Zabbix 6.0+**

**Prerequisites**:
Before importing, create these host groups in Zabbix:
- `eeroVista/Devices`
- `eeroVista/Nodes`

**Quick Import**:
```bash
# Download the template
wget https://raw.githubusercontent.com/Yeraze/eeroVista/main/templates/zabbix_template_eerovista_complete.xml

# Then import via Zabbix web interface:
# Configuration → Templates → Import
```

**Setup Steps**:
1. Create host groups: `eeroVista/Devices` and `eeroVista/Nodes`
2. Import the template
3. Create a host for your eeroVista instance (e.g., "my-eerovista")
4. Configure macros on the eeroVista host:
   - `{$EEROVISTA_SCHEME}` = `http` or `https`
   - `{$EEROVISTA_PORT}` = `8080` (or your port)
   - `{$PARENT_HOST}` = hostname or IP of eeroVista server (e.g., `192.168.1.100`)
5. Link the "eeroVista Auto-Discovery" template to the host
6. Wait 10-30 minutes for discovery to run
7. Check host groups for auto-created device and node hosts

Both templates include:
- ✅ Pre-configured triggers and alerts
- ✅ Configurable thresholds via macros
- ✅ JSON preprocessing already configured
- ✅ HTTPS support via `{$EEROVISTA_SCHEME}` macro

**See**: [`templates/README.md`](https://github.com/Yeraze/eeroVista/blob/main/templates/README.md) for detailed import instructions and configuration guide.

### Manual Setup Steps

If you prefer to configure everything manually instead of using the template:

### 1. Create Host

1. Configuration → Hosts → Create host
2. **Host name**: `eeroVista`
3. **Visible name**: `Eero Network`
4. **Groups**: `Network Devices`
5. **Interfaces**:
   - Type: Agent
   - IP: (eeroVista server IP)
   - Port: 8080

### 2. Create Discovery Rules

#### Device Discovery

**Name**: Device Discovery
**Type**: Agent (active)
**Key**: `web.page.get[{$EEROVISTA_SCHEME}://{HOST.CONN}:{$EEROVISTA_PORT}/api/zabbix/discovery/devices]`
**Update interval**: 5m

**LLD Macros**:
- `{#MAC}` - Device MAC address
- `{#HOSTNAME}` - Device hostname
- `{#NICKNAME}` - Device nickname
- `{#TYPE}` - Device type
- `{#NETWORK}` - Network name (NEW in v2.0+)

**Item Prototypes**:

| Name | Key | Type | Value Type |
|------|-----|------|------------|
| Device [{#HOSTNAME}]: Connected | `device.connected[{#MAC}]` | Agent | Numeric |
| Device [{#HOSTNAME}]: Signal | `device.signal[{#MAC}]` | Agent | Numeric |
| Device [{#HOSTNAME}]: Download | `device.bandwidth.down[{#MAC}]` | Agent | Numeric (float) |
| Device [{#HOSTNAME}]: Upload | `device.bandwidth.up[{#MAC}]` | Agent | Numeric (float) |

**Trigger Prototypes**:

| Name | Expression | Severity |
|------|------------|----------|
| Device [{#HOSTNAME}] is offline | `last(/device.connected[{#MAC}])=0` | Warning |
| Device [{#HOSTNAME}] weak signal | `last(/device.signal[{#MAC}])<-70` | Warning |

#### Node Discovery

**Name**: Node Discovery
**Type**: Agent (active)
**Key**: `web.page.get[{$EEROVISTA_SCHEME}://{HOST.CONN}:{$EEROVISTA_PORT}/api/zabbix/discovery/nodes]`
**Update interval**: 10m

**LLD Macros**:
- `{#NODE_ID}` - Node ID
- `{#NODE_NAME}` - Node name
- `{#NODE_MODEL}` - Node model
- `{#IS_GATEWAY}` - Gateway flag
- `{#NETWORK}` - Network name (NEW in v2.0+)

**Item Prototypes**:

| Name | Key | Type | Value Type |
|------|-----|------|------------|
| Node [{#NODE_NAME}]: Status | `node.status[{#NODE_ID}]` | Agent | Numeric |
| Node [{#NODE_NAME}]: Connected Devices | `node.devices[{#NODE_ID}]` | Agent | Numeric |

**Trigger Prototypes**:

| Name | Expression | Severity |
|------|------------|----------|
| Node [{#NODE_NAME}] is offline | `last(/node.status[{#NODE_ID}])=0` | High |

### 3. Create Items

**Network-Wide Items**:

| Name | Key | URL | Type | Update Interval |
|------|-----|-----|------|-----------------|
| Total Devices | `network.devices.total` | `/api/zabbix/data?item=network.devices.total` | Agent | 1m |
| Online Devices | `network.devices.online` | `/api/zabbix/data?item=network.devices.online` | Agent | 1m |
| Speedtest Download | `speedtest.download` | `/api/zabbix/data?item=speedtest.download` | Agent | 5m |
| Speedtest Upload | `speedtest.upload` | `/api/zabbix/data?item=speedtest.upload` | Agent | 5m |
| Speedtest Latency | `speedtest.latency` | `/api/zabbix/data?item=speedtest.latency` | Agent | 5m |

### 4. Create Triggers

| Name | Expression | Severity | Description |
|------|------------|----------|-------------|
| Network offline | `last(/network.devices.online)=0` | Disaster | No devices connected |
| Slow internet | `last(/speedtest.download)<100` | Warning | Download <100 Mbps |
| High latency | `last(/speedtest.latency)>50` | Warning | Latency >50ms |

## Agent Configuration

### Item URL Format

For device-specific items:
```
http://{HOST.CONN}:8080/api/zabbix/data?item=device.connected[AA:BB:CC:DD:EE:FF]
```

Replace `AA:BB:CC:DD:EE:FF` with actual MAC address or use LLD macro `{#MAC}`.

### Response Preprocessing

Zabbix items should extract the `value` field from JSON response:

**Preprocessing steps**:
1. JSONPath: `$.value`
2. Type: Numeric (or appropriate type)

### Example Item Configuration

**Name**: Device Connection Status
**Type**: Agent (active)
**Key**: `web.page.get[http://{HOST.CONN}:8080/api/zabbix/data?item=device.connected[{#MAC}]]`
**Update interval**: 60s

**Preprocessing**:
- JSONPath: `$.value`

## Macros

Define these macros on the host or template:

| Macro | Default | Description |
|-------|---------|-------------|
| `{$EEROVISTA_PORT}` | `8080` | eeroVista HTTP port |
| `{$SIGNAL_WARN}` | `-70` | Signal strength warning threshold (dBm) |
| `{$SIGNAL_CRIT}` | `-80` | Signal strength critical threshold |
| `{$SPEED_WARN}` | `100` | Download speed warning (Mbps) |
| `{$LATENCY_WARN}` | `50` | Latency warning (ms) |

## Multi-Network Configuration

### Option 1: Monitor All Networks with One Host

Create a single Zabbix host that monitors all networks (default behavior):
- Omit the `network` parameter from all URLs
- eeroVista will default to the first network
- Devices and nodes from all networks will be discovered together
- Use `{#NETWORK}` macro in item names to distinguish between networks

**When to use**: Simple setups, single network, or when you want all metrics in one place

### Option 2: Separate Hosts Per Network

Create multiple Zabbix hosts, one for each network:

1. **Get your network names**:
   ```bash
   curl http://eerovista:8080/api/networks
   ```

2. **Create a Zabbix host for each network**:
   - Host 1: "eeroVista-Home"
     - Set macro: `{$NETWORK_NAME}` = "Home"
   - Host 2: "eeroVista-Office"
     - Set macro: `{$NETWORK_NAME}` = "Office"

3. **Update discovery rules** to include network parameter:
   ```
   # Device Discovery for Home network
   web.page.get[{$EEROVISTA_SCHEME}://{HOST.CONN}:{$EEROVISTA_PORT}/api/zabbix/discovery/devices?network={$NETWORK_NAME}]

   # Node Discovery for Office network
   web.page.get[{$EEROVISTA_SCHEME}://{HOST.CONN}:{$EEROVISTA_PORT}/api/zabbix/discovery/nodes?network={$NETWORK_NAME}]
   ```

4. **Update item URLs** to include network parameter:
   ```
   http://{HOST.CONN}:8080/api/zabbix/data?item=network.devices.total&network={$NETWORK_NAME}
   ```

**When to use**: Multiple networks that need independent monitoring, alerting, and reporting

**Benefits**:
- Independent SLA tracking per network
- Separate maintenance windows
- Network-specific dashboards
- Cleaner problem isolation

## Discovery Rules Details

### Device Discovery Response

**Request**:
```
GET http://eerovista:8080/api/zabbix/discovery/devices
```

**Response**:
```json
{
  "data": [
    {
      "{#MAC}": "AA:BB:CC:DD:EE:FF",
      "{#HOSTNAME}": "Johns-iPhone",
      "{#NICKNAME}": "John's Phone",
      "{#TYPE}": "mobile"
    },
    {
      "{#MAC}": "11:22:33:44:55:66",
      "{#HOSTNAME}": "Smart-TV",
      "{#NICKNAME}": "Living Room TV",
      "{#TYPE}": "entertainment"
    }
  ]
}
```

### Node Discovery Response

**Request**:
```
GET http://eerovista:8080/api/zabbix/discovery/nodes
```

**Response**:
```json
{
  "data": [
    {
      "{#NODE_ID}": "12345",
      "{#NODE_NAME}": "Living Room",
      "{#NODE_MODEL}": "eero Pro 6E",
      "{#IS_GATEWAY}": "true"
    },
    {
      "{#NODE_ID}": "67890",
      "{#NODE_NAME}": "Bedroom",
      "{#NODE_MODEL}": "eero 6",
      "{#IS_GATEWAY}": "false"
    }
  ]
}
```

## Item Data Format

### Device Items

**Connection Status**:
```
GET /api/zabbix/data?item=device.connected[AA:BB:CC:DD:EE:FF]

Response:
{
  "value": 1,
  "timestamp": "2025-10-19T14:30:00Z"
}
```
- Value: `1` (connected) or `0` (disconnected)

**Signal Strength**:
```
GET /api/zabbix/data?item=device.signal[AA:BB:CC:DD:EE:FF]

Response:
{
  "value": -45,
  "timestamp": "2025-10-19T14:30:00Z"
}
```
- Value: Signal strength in dBm (negative number)

**Bandwidth**:
```
GET /api/zabbix/data?item=device.bandwidth.down[AA:BB:CC:DD:EE:FF]

Response:
{
  "value": 125.3,
  "timestamp": "2025-10-19T14:30:00Z"
}
```
- Value: Mbps (float)

## Dashboards

### Network Overview Dashboard

**Widgets**:

1. **Graph**: Online Devices
   - Item: `network.devices.online`
   - Type: Line graph
   - Time period: 24 hours

2. **Plain text**: Network Summary
   - Items: `network.devices.total`, `network.devices.online`
   - Format: "Online: {online} / {total}"

3. **Graph**: Speedtest Results
   - Items: `speedtest.download`, `speedtest.upload`
   - Type: Stacked area
   - Time period: 7 days

4. **Problems**: Active Issues
   - Host group: Network Devices
   - Severity: Warning and above

### Device Status Dashboard

**Widgets**:

1. **Table**: All Devices
   - Discovery rule: Device Discovery
   - Columns: Hostname, Connected, Signal, Download, Upload

2. **Graph**: Signal Strength Heatmap
   - Items: All `device.signal[*]`
   - Type: Heatmap

3. **Top Hosts**: Bandwidth Consumers
   - Items: `device.bandwidth.down[*]`
   - Count: 10

## Alerting

### Email Notifications

Configure Zabbix actions to send emails on trigger events:

**Action Name**: eeroVista Alerts

**Conditions**:
- Trigger severity >= Warning
- Host group = Network Devices

**Operations**:
- Send message to: Admin
- Subject: `{TRIGGER.STATUS}: {TRIGGER.NAME}`
- Message:
  ```
  Problem: {TRIGGER.NAME}
  Host: {HOST.NAME}
  Severity: {TRIGGER.SEVERITY}
  Time: {EVENT.TIME} {EVENT.DATE}

  Details: {ITEM.LASTVALUE}
  ```

### Common Triggers

**Device Offline**:
- Expression: `last(/device.connected[{#MAC}])=0 and last(/device.connected[{#MAC}],#2)=1`
- Recovery: `last(/device.connected[{#MAC}])=1`

**Weak Signal**:
- Expression: `last(/device.signal[{#MAC}])<{$SIGNAL_WARN} for 5m`
- Recovery: `last(/device.signal[{#MAC}])>{$SIGNAL_WARN}`

**Slow Internet**:
- Expression: `avg(/speedtest.download,1h)<{$SPEED_WARN}`
- Recovery: `avg(/speedtest.download,1h)>={$SPEED_WARN}`

## Troubleshooting

### Discovery Not Working

1. **Verify URL is accessible**:
   ```bash
   curl http://eerovista:8080/api/zabbix/discovery/devices
   ```

2. **Check Zabbix server logs**:
   ```bash
   tail -f /var/log/zabbix/zabbix_server.log | grep eerovista
   ```

3. **Test Agent items manually** in Zabbix:
   - Configuration → Hosts → Items → Test
   - Enter key and check response

### Items Not Updating

1. **Verify item key format**:
   - Must match: `device.connected[MAC]` format
   - MAC address must be URL-encoded

2. **Check preprocessing**:
   - Ensure JSONPath `$.value` is configured
   - Test preprocessing in item configuration

3. **Review item history**:
   - Monitoring → Latest data
   - Filter by host: eeroVista
   - Check for errors

### High API Load

If eeroVista is being overloaded:

1. **Increase update intervals**:
   - Device items: 2m → 5m
   - Network items: 1m → 2m
   - Discovery rules: 5m → 15m

2. **Use flexible intervals**:
   - Active hours: 1m
   - Off-hours: 5m

3. **Reduce item count**:
   - Filter devices by type in discovery rule
   - Remove unused items

## Best Practices

1. **Update Intervals**:
   - Device discovery: 5-15 minutes
   - Device items: 1-2 minutes
   - Speedtest items: 5-15 minutes

2. **Data Storage**:
   - History: 7 days
   - Trends: 365 days

3. **Trigger Thresholds**:
   - Use macros for easy adjustment
   - Set appropriate `for` durations to avoid flapping
   - Configure different severities (Warning, High, Disaster)

4. **Performance**:
   - Use Agent items (not external scripts)
   - Batch discovery updates
   - Enable value caching in eeroVista (future feature)

## Complete Zabbix Templates

Two production-ready Zabbix templates are available:

### Single-Host Template
**Download**: [`templates/zabbix_template_eerovista.xml`](https://github.com/Yeraze/eeroVista/blob/main/templates/zabbix_template_eerovista.xml)

Best for networks with <50 devices. Creates one host with Low-Level Discovery for all devices and nodes.

### Auto-Discovery Template
**Download**: [`templates/zabbix_template_eerovista_complete.xml`](https://github.com/Yeraze/eeroVista/blob/main/templates/zabbix_template_eerovista_complete.xml)

Best for networks with 50+ devices. Automatically creates individual Zabbix hosts for each device and node. Requires Zabbix 6.0+.

**Prerequisites**: Create host groups `eeroVista/Devices` and `eeroVista/Nodes` before importing.

**Documentation**: [`templates/README.md`](https://github.com/Yeraze/eeroVista/blob/main/templates/README.md)

Both templates include:
- All discovery rules (devices and nodes)
- All item prototypes with proper preprocessing
- Trigger prototypes for automated alerting
- Configurable macros for threshold tuning (`{$EEROVISTA_SCHEME}`, `{$EEROVISTA_PORT}`, `{$PARENT_HOST}`)
- Proper value types and units
- Optimized update intervals
- 7-day history and 365-day trends
- HTTPS support via macro configuration

Simply import the template and link it to your eeroVista host - no manual configuration needed!
