# eeroVista Zabbix Templates

This directory contains Zabbix templates for monitoring Eero mesh networks via eeroVista.

## Available Templates

### 1. Single-Host Monitoring (Recommended for Small Networks)

**Template**: `zabbix_template_eerovista.xml`

- **Best for**: Networks with <50 devices
- **Creates**: One Zabbix host with many items
- **Pros**: Simpler setup, less Zabbix overhead
- **Cons**: All metrics under one host

**What you get**:
- Network-wide metrics (total/online devices, WAN status)
- Speedtest metrics (download, upload, latency)
- Per-device items via Low-Level Discovery
- Per-node items via Low-Level Discovery
- Triggers for offline devices, weak signals, slow speeds

### 2. Auto-Discovery with Individual Hosts (Recommended for Large Networks)

**Templates**:
- `zabbix_template_eerovista_autodiscovery.xml` (discovery orchestrator)
- `zabbix_template_eerovista_device.xml` (device monitoring)
- `zabbix_template_eerovista_node.xml` (node monitoring)

- **Best for**: Networks with 50+ devices, or when you want granular host-level management
- **Creates**: Individual Zabbix hosts for each device and node
- **Pros**: Better organization, individual host management, inventory support
- **Cons**: More Zabbix resources, requires Zabbix 6.0+

**What you get**:
- Automatic host creation for each discovered device
- Automatic host creation for each discovered node
- Zabbix inventory populated with MAC addresses, device types, models
- Each host has its own set of items and triggers
- Better for Maps, Mass Updates, and SLA reporting

## Installation

### Single-Host Monitoring

1. Import `zabbix_template_eerovista.xml`
2. Create a host for your eeroVista instance
3. Configure macros:
   - `{$EEROVISTA_SCHEME}` = `http` or `https`
   - `{$EEROVISTA_PORT}` = `8080` (or your port)
4. Link template to host
5. Wait for discovery to populate items

### Auto-Discovery with Individual Hosts

1. Import all three templates in this order:
   - `zabbix_template_eerovista_device.xml`
   - `zabbix_template_eerovista_node.xml`
   - `zabbix_template_eerovista_autodiscovery.xml`
2. Create host groups:
   - `eeroVista/Devices` (or customize with `{$EEROVISTA_HOST_GROUP}`)
   - `eeroVista/Nodes` (or customize with `{$EEROVISTA_NODE_GROUP}`)
3. Create a host for your eeroVista instance
4. Configure macros:
   - `{$EEROVISTA_SCHEME}` = `http` or `https`
   - `{$EEROVISTA_PORT}` = `8080` (or your port)
   - `{$EEROVISTA_HOST_GROUP}` = `eeroVista/Devices`
   - `{$EEROVISTA_NODE_GROUP}` = `eeroVista/Nodes`
5. Link autodiscovery template to host
6. Wait 10-30 minutes for discovery
7. Check host groups for auto-created device and node hosts

## Configuration

### HTTPS Support

Both templates support HTTPS for reverse proxies:

```
{$EEROVISTA_SCHEME} = https
{$EEROVISTA_PORT} = 443
```

### Thresholds

Customize alert thresholds with macros:

```
{$SIGNAL_WARN} = -70    # WiFi signal warning (dBm)
{$SIGNAL_CRIT} = -80    # WiFi signal critical (dBm)
{$SPEED_WARN} = 100     # Download speed warning (Mbps)
{$LATENCY_WARN} = 50    # Latency warning (ms)
```

## Inventory Fields (Auto-Discovery)

The auto-discovery templates set `inventory_mode=AUTOMATIC` for all created hosts.
While Zabbix 6.0 host prototypes don't support direct inventory population via XML,
the following information is available via host macros:

**Device Hosts**:
- `{$DEVICE_MAC}` - Device MAC address
- `{$DEVICE_HOSTNAME}` - Device hostname
- `{$DEVICE_NICKNAME}` - Device nickname/friendly name
- `{$DEVICE_TYPE}` - Device type (laptop, phone, tablet, etc.)

**Node Hosts**:
- `{$NODE_ID}` - Eero node ID
- `{$NODE_NAME}` - Node location/name
- `{$NODE_MODEL}` - Node hardware model

These macros can be used in:
- Item names and descriptions
- Trigger names and messages  
- Manual inventory population
- External scripts and integrations

## Compatibility

- **Zabbix Version**: 6.0+ (for all templates)
  - Auto-discovery requires 6.0+ for host prototypes
- **eeroVista Version**: Any version with Zabbix API support
- **Protocol**: HTTP or HTTPS

## Troubleshooting

### Discovery not working

- Verify eeroVista is accessible at the configured URL
- Check macro values (scheme, port, host groups)
- Review Zabbix server logs for HTTP agent errors
- Ensure eeroVista Zabbix endpoints return valid JSON

### Hosts not auto-created

- Verify you're using Zabbix 6.0 or later
- Check that host groups exist before discovery runs
- Review discovery rule logs in Zabbix UI
- Ensure Device/Node templates are imported first

### Template import errors

- Ensure no dashes in UUIDs (must be 32 hex characters)
- Verify `<applications>` tags are replaced with `<tags>`
- Check that group "Templates/Network devices" exists

## Support

For issues or questions:
- GitHub: https://github.com/Yeraze/eeroVista/issues
- Documentation: https://github.com/Yeraze/eeroVista

