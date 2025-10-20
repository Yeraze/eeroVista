# eeroVista Monitoring Templates

This directory contains pre-built monitoring templates for integrating eeroVista with external monitoring systems.

## Zabbix Template

### Quick Start

**File**: `zabbix_template_eerovista.xml`

**Compatible with**: Zabbix 6.0 and later

### Import Instructions

1. **Download the template**:
   ```bash
   wget https://raw.githubusercontent.com/Yeraze/eeroVista/main/templates/zabbix_template_eerovista.xml
   ```

2. **Import to Zabbix**:
   - Open Zabbix web interface
   - Navigate to: **Configuration** → **Templates**
   - Click **Import** button
   - Click **Choose File** and select `zabbix_template_eerovista.xml`
   - Review import options (defaults are usually fine)
   - Click **Import**

3. **Create a host for eeroVista**:
   - Navigate to: **Configuration** → **Hosts**
   - Click **Create host**
   - Set **Host name**: `eeroVista` (or your preference)
   - Set **Visible name**: `Eero Network`
   - Add to **Groups**: `Network Devices` (or create new group)
   - Under **Interfaces**, add:
     - **Type**: HTTP agent
     - **IP address**: Your eeroVista server IP
     - **DNS name**: (optional) your eeroVista hostname
     - **Connect to**: IP (or DNS)
     - **Port**: 8080 (or custom port if changed)

4. **Link the template**:
   - In the host configuration, go to **Templates** tab
   - Click **Select** next to "Link new templates"
   - Search for `eeroVista Network Monitor`
   - Click **Add**, then **Update**

5. **Verify discovery is working**:
   - Wait 5-10 minutes for initial discovery
   - Navigate to: **Monitoring** → **Latest data**
   - Filter by host: `eeroVista`
   - You should see network metrics and discovered devices/nodes

### What's Included

The template provides comprehensive monitoring with:

#### Network-Wide Metrics
- Total devices count
- Online devices count
- WAN status (online/offline)
- Speedtest results (download, upload, latency)

#### Automatic Device Discovery
Discovers all devices on your Eero network with:
- Connection status (online/offline)
- WiFi signal strength (dBm)
- Current bandwidth (download/upload in Mbps)

#### Automatic Node Discovery
Discovers all Eero mesh nodes with:
- Node status (online/offline)
- Connected device count
- Mesh quality (1-5 bars)

#### Pre-configured Triggers
- **DISASTER**: WAN is offline
- **HIGH**: Eero node is offline
- **WARNING**: Device is offline
- **WARNING**: Weak WiFi signal
- **WARNING**: Slow internet speed
- **WARNING**: High latency
- **WARNING**: Poor mesh quality

#### Configurable Macros

You can customize thresholds by changing these macros (on the host or template level):

| Macro | Default | Description |
|-------|---------|-------------|
| `{$EEROVISTA_PORT}` | `8080` | eeroVista HTTP port |
| `{$SIGNAL_WARN}` | `-70` | Signal warning threshold (dBm) |
| `{$SIGNAL_CRIT}` | `-80` | Signal critical threshold (dBm) |
| `{$SPEED_WARN}` | `100` | Download speed warning (Mbps) |
| `{$LATENCY_WARN}` | `50` | Latency warning (ms) |

**To change macros**:
1. Navigate to: **Configuration** → **Hosts**
2. Click on your eeroVista host
3. Go to **Macros** tab
4. Click **Inherited and host macros**
5. Override any macro value
6. Click **Update**

### Update Intervals

Default polling intervals (can be customized per item):

- **Network metrics**: 1 minute
- **Device status**: 1 minute
- **Device signal/bandwidth**: 2 minutes
- **Speedtest metrics**: 5 minutes
- **Node metrics**: 2-5 minutes
- **Device discovery**: 5 minutes
- **Node discovery**: 10 minutes

**To adjust intervals**:
1. Navigate to: **Configuration** → **Hosts**
2. Click on your eeroVista host
3. Go to **Items** or **Discovery rules**
4. Click on the item you want to modify
5. Change the **Update interval**
6. Click **Update**

### Data Retention

Default retention (can be customized):

- **History**: 7 days (raw data)
- **Trends**: 365 days (hourly averages)

**To adjust retention**:
1. Navigate to: **Configuration** → **Hosts**
2. Click on your eeroVista host
3. Go to **Items**
4. Click on the item you want to modify
5. Change **History storage period** and/or **Trend storage period**
6. Click **Update**

### Creating Dashboards

Example widgets for a custom dashboard:

1. **Network Status Widget** (Plain text):
   - Items: `network.devices.total`, `network.devices.online`, `network.status`
   - Shows: "Online: 15/20 devices | WAN: Up"

2. **Device Count Graph** (Graph):
   - Items: `network.devices.online`
   - Type: Line
   - Time period: 24 hours

3. **Speedtest Graph** (Graph):
   - Items: `speedtest.download`, `speedtest.upload`
   - Type: Stacked area
   - Time period: 7 days

4. **Active Problems** (Problems):
   - Host group: Network Devices
   - Severity: Warning and above
   - Shows: Current alerts

5. **Device Status Table** (Discovery rule widget):
   - Discovery rule: Device Discovery
   - Columns: Hostname, Connected, Signal, Bandwidth

### Troubleshooting

#### No data appearing

1. **Check eeroVista is accessible**:
   ```bash
   curl http://your-eerovista-ip:8080/api/zabbix/discovery/devices
   ```
   Should return JSON with device list.

2. **Check Zabbix server can reach eeroVista**:
   - SSH to Zabbix server
   - Test connectivity:
     ```bash
     curl http://your-eerovista-ip:8080/api/health
     ```

3. **Verify host interface configuration**:
   - Configuration → Hosts → eeroVista
   - Ensure HTTP agent interface has correct IP/DNS and port

4. **Check Zabbix server logs**:
   ```bash
   tail -f /var/log/zabbix/zabbix_server.log | grep eerovista
   ```

#### Discovery not working

1. **Test discovery URL manually**:
   ```bash
   curl http://your-eerovista-ip:8080/api/zabbix/discovery/devices
   ```

2. **Check discovery rule status**:
   - Configuration → Hosts → eeroVista → Discovery rules
   - Click on "Device Discovery" or "Node Discovery"
   - Check **Status** is "Enabled"
   - View **Latest data** to see last discovery execution

3. **Force discovery update**:
   - Configuration → Hosts → eeroVista → Discovery rules
   - Click "Check now" button next to the discovery rule

#### Items showing "Not supported"

1. **Check preprocessing**:
   - Each item should have JSONPath preprocessing: `$.value`
   - Configuration → Hosts → Items → Click item → Preprocessing tab

2. **Test item manually**:
   - Configuration → Hosts → Items
   - Click item name
   - Click "Test" button
   - Review error message

3. **Verify API response format**:
   ```bash
   curl http://your-eerovista-ip:8080/api/zabbix/data?item=network.devices.total
   ```
   Should return: `{"value": 20, "timestamp": "2025-10-20T..."}`

### Advanced Configuration

#### Setting up email alerts

1. **Configure media type**:
   - Administration → Media types
   - Select or create email media type
   - Configure SMTP settings

2. **Create user media**:
   - Administration → Users
   - Select your user → Media tab
   - Add email address

3. **Create action**:
   - Configuration → Actions → Trigger actions
   - Create action with conditions:
     - Trigger severity ≥ Warning
     - Host group = Network Devices
   - Operations: Send message to Admin

#### Integration with external services

The template can be extended to integrate with:
- **Slack**: Use webhook media type
- **PagerDuty**: Use webhook media type
- **Telegram**: Use Telegram media type
- **Custom scripts**: Use script media type

### Template Customization

You can modify the template to fit your needs:

1. **Export template** (after import):
   - Configuration → Templates
   - Select "eeroVista Network Monitor"
   - Click Export
   - Modify XML as needed
   - Re-import

2. **Clone template** (to preserve original):
   - Configuration → Templates
   - Click "eeroVista Network Monitor"
   - Click "Full clone"
   - Modify clone as needed

### Support

For issues or questions:
- **Documentation**: https://yeraze.github.io/eeroVista/zabbix.html
- **GitHub Issues**: https://github.com/Yeraze/eeroVista/issues
- **Discussions**: https://github.com/Yeraze/eeroVista/discussions

## Future Templates

Planned templates for other monitoring systems:
- Grafana dashboard (via Prometheus)
- Nagios/Icinga checks
- Datadog integration

Contributions welcome!
