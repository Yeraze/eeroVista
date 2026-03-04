# Bonded Devices Design

**Issue:** [#79 - Bonded Devices](https://github.com/Yeraze/eeroVista/issues/79)
**Date:** 2026-03-04

## Problem

A physical device with multiple network interfaces (WiFi + Ethernet, or multiple Ethernets) appears as separate entries in eeroVista because each interface has a unique MAC address. Users need a way to link these entries so the device appears as a single entity in the UI.

## Scope

- **Affected:** Device list page, device detail modal, `/api/devices` endpoint
- **Unchanged:** Prometheus/Zabbix exports, network topology graph, dashboard device counts, per-MAC bandwidth history endpoints

Grouping is a display/analysis-only feature. All underlying data remains independent per-MAC.

## Data Model

Two new tables added via migration 008:

### `device_groups`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PRIMARY KEY, auto-increment |
| `network_name` | TEXT | NOT NULL |
| `name` | TEXT | NOT NULL |
| `created_at` | DATETIME | DEFAULT current timestamp |

### `device_group_members`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | INTEGER | PRIMARY KEY, auto-increment |
| `group_id` | INTEGER | FK -> device_groups.id, ON DELETE CASCADE |
| `device_id` | INTEGER | FK -> devices.id, UNIQUE (one group per device) |

## API Endpoints

### New CRUD Endpoints

| Method | Endpoint | Body / Params | Purpose |
|--------|----------|---------------|---------|
| GET | `/api/device-groups?network=NAME` | - | List all groups with member device IDs |
| POST | `/api/device-groups` | `{network_name, name, device_ids}` | Create a group |
| PUT | `/api/device-groups/{id}` | `{name?, device_ids?}` | Update group name or members |
| DELETE | `/api/device-groups/{id}` | - | Delete group (ungroups all members) |

### Modified: `GET /api/devices`

Grouped devices are returned as a single entry with aggregated stats. Individual member devices are excluded from the top-level list.

Each group entry includes:
- `group_id` and `group_name`
- `group_members`: array of individual device objects with their own stats
- Aggregated fields:
  - `bandwidth_down_mbps` / `bandwidth_up_mbps`: sum of all members
  - `signal_strength`: best (least negative) among connected wireless members
  - `is_connected`: true if any member is connected
  - `connection_type`: concatenated unique types (e.g., "Wired + Wireless")
  - `ip_address`: comma-separated from all connected members

## Frontend UI

### Device List Page

- **"Create Device Group" button** in the toolbar area next to existing filters
- Opens a modal with:
  - Text input for the group name
  - Searchable/filterable checklist of all ungrouped devices on the current network
  - "Create Group" / "Cancel" buttons
- Grouped devices appear as a single row:
  - Name: group name with a link/chain icon
  - Connection: "Wired + Wireless" (or whichever types are present)
  - Bandwidth: aggregated sum
  - Signal: best among wireless members
  - Status: online if any member is online

### Device Detail Modal (for grouped devices)

- Group name displayed at top with "Ungroup" and "Edit Group" buttons
- Sectioned breakdown of each member device showing: MAC, hostname, individual bandwidth, signal, connection type
- Bandwidth chart shows combined history

## Edge Cases

- **Offline members**: Don't contribute to aggregated stats; group remains functional
- **Single-member groups**: Allowed, behaves like any grouped device
- **Duplicate grouping**: UNIQUE constraint on `device_group_members.device_id` prevents it; API returns clear error
- **Network mismatch**: API validates all device_ids belong to the group's network
- **Device disappears from eero**: Row persists in `devices` table with stale `last_seen`; group unaffected
