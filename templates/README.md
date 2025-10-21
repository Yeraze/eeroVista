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

**Template**: `zabbix_template_eerovista_complete.xml`

- **Best for**: Networks with 50+ devices, or when you want granular host-level management
- **Creates**: Individual Zabbix hosts for each device and node
- **Pros**: Better organization, individual host management, inventory support
- **Cons**: More Zabbix resources, requires Zabbix 6.0+

**What you get**:
- Automatic host creation for each discovered device (`eeroVista-Device-{hostname}`)
- Automatic host creation for each discovered node (`eeroVista-Node-{nodename}`)
- Zabbix inventory mode enabled with MAC addresses, device types, models available via macros
- Each host has its own set of items and triggers
- Better for Maps, Mass Updates, and SLA reporting
- Includes all three templates (Device, Node, and Auto-Discovery) in one file

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

**Prerequisites**:
1. Create host groups in Zabbix before importing:
   - `eeroVista/Devices`
   - `eeroVista/Nodes`

**Setup Steps**:
1. Import `zabbix_template_eerovista_complete.xml` into Zabbix
2. Create a host for your eeroVista instance (e.g., "my-eerovista")
3. Configure macros on the eeroVista host:
   - `{$EEROVISTA_SCHEME}` = `http` or `https`
   - `{$EEROVISTA_PORT}` = `8080` (or your port)
   - `{$PARENT_HOST}` = hostname or IP of your eeroVista server (e.g., `192.168.1.100` or `eerovista.local`)
4. Link the "eeroVista Auto-Discovery" template to the host
5. Wait 10-30 minutes for discovery to run
6. Check `eeroVista/Devices` and `eeroVista/Nodes` host groups for auto-created hosts

**Important**: The `{$PARENT_HOST}` macro on your eeroVista host will be inherited by all discovered device and node hosts, allowing them to query the eeroVista API.

## Configuration

### HTTPS Support

Both templates support HTTPS for reverse proxies:

```
{$EEROVISTA_SCHEME} = https
{$EEROVISTA_PORT} = 443
```

### Required Macros (Auto-Discovery)

For the auto-discovery template, set these macros on the eeroVista host:

```
{$EEROVISTA_SCHEME} = http          # or https for reverse proxy
{$EEROVISTA_PORT} = 8080            # your eeroVista port
{$PARENT_HOST} = 192.168.1.100      # hostname or IP of eeroVista server
```

### Thresholds

Customize alert thresholds with macros (apply to single-host or device/node templates):

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
- `{$DEVICE_IP}` - Last known IP address
- `{$DEVICE_CONNECTION_TYPE}` - Connection type (wireless/wired)

**Node Hosts**:
- `{$NODE_ID}` - Eero node ID
- `{$NODE_NAME}` - Node location/name
- `{$NODE_MODEL}` - Node hardware model
- `{$NODE_IS_GATEWAY}` - Gateway flag (1=gateway, 0=leaf node)
- `{$NODE_MAC}` - Node MAC address
- `{$NODE_FIRMWARE}` - Firmware/OS version

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
- Check that host groups `eeroVista/Devices` and `eeroVista/Nodes` exist before importing template
- Review discovery rule logs in Zabbix UI (Latest data → Discovery rules)
- Verify `{$PARENT_HOST}` macro is set correctly on the eeroVista host
- Check that eeroVista API endpoints return data: `/api/zabbix/discovery/devices` and `/api/zabbix/discovery/nodes`

### Template import errors

- Ensure you're using Zabbix 6.0 or later
- Verify the "Templates/Network devices" group exists (standard Zabbix group)
- All UUIDs are properly formatted UUIDv4 (generated with Python's uuid library)
- Templates use `<tags>` instead of deprecated `<applications>`

## Support

For issues or questions:
- GitHub: https://github.com/Yeraze/eeroVista/issues
- Documentation: https://github.com/Yeraze/eeroVista

