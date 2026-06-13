---
layout: default
title: MCP Server (AI Agents)
nav_order: 7
---

# MCP Server (AI Agents)

eeroVista can expose a **Model Context Protocol (MCP)** server so that AI agents
(such as Claude) can query your eero network status in real time using a curated
set of read-only tools. The tools reuse eeroVista's existing query logic, so they
return the same data as the REST API — just packaged for agent consumption.

Like the rest of eeroVista, the MCP server is **strictly read-only**. None of the
tools can change your network configuration.

## ⚠️ Security

The MCP endpoint has **no authentication**. Only enable it when eeroVista is on a
network you control or behind a trusted reverse proxy that restricts access. Do
not expose the `/mcp` path directly to the public internet.

See [Reverse Proxy & HTTPS](reverse-proxy.md) for how to put eeroVista (and the
MCP endpoint) behind nginx/Caddy with TLS and access controls.

## Configuration

The MCP server is **disabled by default**. Enable it with environment variables in
your `docker-compose.yml`:

```yaml
environment:
  - MCP_ENABLED=true                    # Enable the MCP server (default: false)
  - MCP_PATH=/mcp                       # Path the endpoint is mounted at (default: /mcp)
  - MCP_ALLOWED_HOSTS=eero.example.com  # Public hostname(s) when behind a proxy
```

When enabled, the server is mounted on the existing eeroVista web server — same
host and port (default `8080`) — using the **Streamable HTTP** transport. With the
defaults above, the endpoint is:

```
http://<your-host>:8080/mcp
```

### Running behind a reverse proxy

The MCP transport has built-in DNS-rebinding protection that, by default, only
accepts requests whose `Host` header is `localhost`. When eeroVista runs behind a
reverse proxy (nginx, Caddy, etc.) the proxy forwards the **public** hostname, so
you must allow it or every request is rejected with **`421 Invalid Host header`**:

```yaml
environment:
  - MCP_ALLOWED_HOSTS=eero.example.com         # one or more, comma-separated
  # - MCP_ALLOWED_HOSTS=*                       # or trust the proxy entirely
```

`localhost` is always allowed (for local access and health checks). Set
`MCP_ALLOWED_HOSTS=*` to disable host checking completely and fully trust the
proxy.

Two more proxy requirements:

- **Forward the original scheme.** eeroVista honors `X-Forwarded-Proto`, so make
  sure your proxy sets it (`proxy_set_header X-Forwarded-Proto $scheme;` in
  nginx). Otherwise the `/mcp` → `/mcp/` redirect is emitted as `http://` and TLS
  clients refuse to follow it.
- **Use the trailing slash.** The endpoint lives at `/mcp/`; a request to `/mcp`
  is redirected. Point clients at the trailing-slash URL (or a path that maps to
  it) to avoid a redirect round-trip: `https://eero.example.com/mcp/`.

See [Reverse Proxy & HTTPS](reverse-proxy.md) for full proxy configuration.

## Connecting an agent

Point any MCP client that supports the Streamable HTTP transport at the endpoint
URL. For example, with the Claude Code CLI:

```bash
claude mcp add --transport http eerovista https://eero.example.com/mcp/
```

Or in an MCP client configuration file:

```json
{
  "mcpServers": {
    "eerovista": {
      "transport": "http",
      "url": "https://eero.example.com/mcp/"
    }
  }
}
```

> Note the **trailing slash** on `/mcp/` — see [Running behind a reverse
> proxy](#running-behind-a-reverse-proxy) below.

## Available tools

All tools accept an optional `network` argument (the network name); omit it to use
the default (first) network.

| Tool | Description |
| --- | --- |
| `dashboard_stats` | High-level summary: device counts, health score, WAN status, latest speedtest. |
| `network_summary` | Network totals plus per-node status (location, model, uptime, connected devices). |
| `list_devices` | All client devices: name, MAC, IP, manufacturer, connection type, signal. |
| `list_nodes` | The eero nodes (access points): location, model, status, uptime, backhaul. |
| `collection_status` | Background data-collection health and freshness timestamps. |
| `firmware_status` | Current firmware version and whether an update is available. |
| `health_score` | Current network health score (0–100) and contributing factors. |
| `wan_uptime` | WAN uptime percentages over 24 h / 7 d / 30 d. |
| `recent_outages` | Recent WAN outages within `days` (default 30). |
| `speedtest_analysis` | Speedtest trends (download/upload/latency) over `days` (default 30). |
| `signal_summary` | Wireless signal-quality summary across all devices. |
| `top_bandwidth_devices` | Top bandwidth consumers over `days` (default 7), up to `limit` (default 5). |

## Notes

- Data is served from eeroVista's local SQLite database, populated by the
  background collectors. Use `collection_status` to confirm how fresh it is.
- Because the tools reuse the REST handlers, their output matches the
  corresponding endpoints documented in the [API Reference](api-reference.md).
