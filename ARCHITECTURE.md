# eeroVista Architecture

## Overview

eeroVista is a **read-only** monitoring system for Eero mesh networks, providing historical data collection, visualization, and multi-format metric exports.

## Core Principles

1. **Read-Only**: Query eero API only; no control operations (no reboots, config changes)
2. **Time-Series Storage**: SQLite-based historical data with configurable retention
3. **Multi-Format Export**: Prometheus, Zabbix, and JSON API endpoints
4. **Docker-First**: Single container deployment with volume persistence
5. **Lightweight**: Minimal dependencies, embedded scheduler, no external services required

---

## Technology Stack

### Backend
- **Python 3.11+**
- **FastAPI** - Modern async web framework with automatic OpenAPI docs
- **SQLAlchemy 2.x** - ORM for database operations
- **APScheduler** - Embedded background task scheduler
- **eero-client** - Eero API client library (latest with pydantic models)

### Frontend
- **Jinja2** - Template engine
- **Chart.js** - Interactive time-series graphs
- **Catppuccin Latte** - Color theme (see Design System below)
- **Bootstrap 5** - Component framework (customized with Catppuccin colors)

### Data Layer
- **SQLite** - Embedded database for time-series metrics
- **pandas** - Data aggregation and analysis

### Export/Integration
- **prometheus_client** - Metrics exposition
- **Custom JSON API** - Zabbix LLD and data endpoints

---

## Design System - Catppuccin Latte Theme

### Color Palette

#### Accent Colors
```css
--rosewater: #dc8a78;  /* Soft rose */
--flamingo: #dd7878;   /* Coral pink */
--pink: #ea76cb;       /* Bright pink */
--mauve: #8839ef;      /* Purple */
--red: #d20f39;        /* Error states */
--maroon: #e64553;     /* Dark red */
--peach: #fe640b;      /* Orange accent */
--yellow: #df8e1d;     /* Warnings */
--green: #40a02b;      /* Success states */
--teal: #179299;       /* Info accent */
--sky: #04a5e5;        /* Light blue */
--sapphire: #209fb5;   /* Medium blue */
--blue: #1e66f5;       /* Primary brand */
--lavender: #7287fd;   /* Light purple */
```

#### UI Colors
```css
/* Text hierarchy */
--text: #4c4f69;       /* Primary text */
--subtext1: #5c5f77;   /* Secondary text */
--subtext0: #6c6f85;   /* Tertiary text */

/* Overlays & borders */
--overlay2: #7c7f93;
--overlay1: #8c8fa1;
--overlay0: #9ca0b0;

/* Surfaces */
--surface2: #acb0be;   /* Elevated cards */
--surface1: #bcc0cc;   /* Cards */
--surface0: #ccd0da;   /* Subtle backgrounds */

/* Base layers */
--base: #eff1f5;       /* Main background */
--mantle: #e6e9ef;     /* Secondary background */
--crust: #dce0e8;      /* Window background */
```

### Color Usage Guidelines

- **Primary Actions**: `--blue` (#1e66f5)
- **Success/Online**: `--green` (#40a02b)
- **Warning/Degraded**: `--yellow` (#df8e1d)
- **Error/Offline**: `--red` (#d20f39)
- **Charts**: Rotate through accent colors (blue, green, teal, mauve, pink, peach)
- **Backgrounds**: Use base/mantle/crust hierarchy
- **Text**: Use text/subtext1/subtext0 for hierarchy

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Docker Container                         │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐ │
│  │              FastAPI Web Application                   │ │
│  │                                                         │ │
│  │  Web UI Routes:                                        │ │
│  │  - /              Dashboard (graphs, overview)         │ │
│  │  - /devices       Device list & details               │ │
│  │  - /network       Network topology view               │ │
│  │  - /speedtest     Speedtest history                   │ │
│  │  - /settings      Configuration (read-only display)   │ │
│  │                                                         │ │
│  │  API Routes:                                           │ │
│  │  - /metrics       Prometheus exporter                 │ │
│  │  - /api/health    Health check endpoint               │ │
│  │  - /api/devices   JSON device list                    │ │
│  │  - /api/zabbix/*  Zabbix LLD & data                   │ │
│  └───────────────────────────────────────────────────────┘ │
│                            │                                 │
│  ┌───────────────────────────────────────────────────────┐ │
│  │          APScheduler Background Jobs                   │ │
│  │  - Device collector (30s)                              │ │
│  │  - Network metrics (1m)                                │ │
│  │  - Data retention cleanup (daily)                      │ │
│  │  Note: No speedtest trigger (passive collection only)  │ │
│  └───────────────────────────────────────────────────────┘ │
│                            │                                 │
│  ┌───────────────────────────────────────────────────────┐ │
│  │              Eero Client Wrapper                       │ │
│  │  - Session management & token refresh                  │ │
│  │  - Rate limiting (respect API limits)                  │ │
│  │  - Error handling & retries                            │ │
│  │  - READ-ONLY endpoints only:                           │ │
│  │    * account, networks, eeros, devices                 │ │
│  │    * diagnostics, speedtest (results), insights        │ │
│  └───────────────────────────────────────────────────────┘ │
│                            │                                 │
│  ┌───────────────────────────────────────────────────────┐ │
│  │          SQLite Database (/data/eerovista.db)         │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
          External Monitoring   User Browser
          - Prometheus          - Web Dashboard
          - Zabbix             - Device Tracking
          - Grafana            - Speedtest History
```

---

## Database Schema

### Tables

#### `eero_nodes`
Stores mesh network node (eero device) information.
```sql
CREATE TABLE eero_nodes (
    id INTEGER PRIMARY KEY,
    eero_id TEXT UNIQUE NOT NULL,
    location TEXT,
    model TEXT,
    mac_address TEXT,
    is_gateway BOOLEAN,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP
);
```

#### `devices`
Connected client device registry.
```sql
CREATE TABLE devices (
    id INTEGER PRIMARY KEY,
    mac_address TEXT UNIQUE NOT NULL,
    hostname TEXT,
    nickname TEXT,
    device_type TEXT,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP
);
```

#### `device_connections`
Time-series device connection metrics.
```sql
CREATE TABLE device_connections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id INTEGER NOT NULL,
    eero_node_id INTEGER,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_connected BOOLEAN,
    connection_type TEXT,
    signal_strength INTEGER,
    ip_address TEXT,
    bandwidth_down_mbps REAL,
    bandwidth_up_mbps REAL,
    FOREIGN KEY (device_id) REFERENCES devices(id),
    FOREIGN KEY (eero_node_id) REFERENCES eero_nodes(id)
);
CREATE INDEX idx_device_connections_timestamp ON device_connections(timestamp);
CREATE INDEX idx_device_connections_device ON device_connections(device_id, timestamp);
```

#### `network_metrics`
Network-wide time-series metrics.
```sql
CREATE TABLE network_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_devices INTEGER,
    total_devices_online INTEGER,
    guest_network_enabled BOOLEAN,
    wan_status TEXT
);
CREATE INDEX idx_network_metrics_timestamp ON network_metrics(timestamp);
```

#### `speedtests`
Historical speedtest results (collected passively from eero API).
```sql
CREATE TABLE speedtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    download_mbps REAL,
    upload_mbps REAL,
    latency_ms REAL,
    jitter_ms REAL,
    server_location TEXT,
    isp TEXT
);
CREATE INDEX idx_speedtests_timestamp ON speedtests(timestamp);
```

#### `eero_node_metrics`
Per-node time-series metrics.
```sql
CREATE TABLE eero_node_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eero_node_id INTEGER NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT,
    connected_device_count INTEGER,
    uptime_seconds INTEGER,
    FOREIGN KEY (eero_node_id) REFERENCES eero_nodes(id)
);
CREATE INDEX idx_eero_metrics_timestamp ON eero_node_metrics(timestamp);
CREATE INDEX idx_eero_metrics_node ON eero_node_metrics(eero_node_id, timestamp);
```

#### `config`
Application configuration key-value store.
```sql
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Directory Structure

```
eerovista/
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── README.md
├── CLAUDE.md
├── ARCHITECTURE.md
├── eerovista.png
├── .gitignore
├── docs/                           # GitHub Pages documentation
│   ├── index.md                    # Project homepage
│   ├── getting-started.md          # Installation guide
│   ├── configuration.md            # Configuration reference
│   ├── api-reference.md            # API endpoint docs
│   ├── prometheus.md               # Prometheus integration guide
│   ├── zabbix.md                   # Zabbix integration guide
│   ├── development.md              # Development setup
│   └── _config.yml                 # Jekyll/GitHub Pages config
├── src/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app entry point
│   ├── config.py                   # Configuration management
│   ├── models/
│   │   ├── __init__.py
│   │   └── database.py             # SQLAlchemy models
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── base.py                 # Base collector class
│   │   ├── device_collector.py
│   │   ├── network_collector.py
│   │   └── speedtest_collector.py
│   ├── eero_client/
│   │   ├── __init__.py
│   │   ├── client.py               # Wrapper around eero-client
│   │   └── auth.py                 # Authentication management
│   ├── api/
│   │   ├── __init__.py
│   │   ├── web.py                  # Web UI routes
│   │   ├── prometheus.py           # Prometheus /metrics
│   │   ├── zabbix.py               # Zabbix endpoints
│   │   └── devices.py              # JSON API endpoints
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── jobs.py                 # APScheduler job definitions
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── database.py             # Database utilities
│   │   └── retention.py            # Data retention policies
│   └── templates/
│       ├── base.html               # Base template with Catppuccin theme
│       ├── dashboard.html
│       ├── devices.html
│       ├── network.html
│       ├── speedtest.html
│       └── settings.html
├── static/
│   ├── css/
│   │   └── catppuccin-latte.css    # Theme CSS variables
│   ├── js/
│   │   ├── charts.js               # Chart.js configurations
│   │   └── main.js                 # Main frontend JS
│   └── img/
│       └── logo.png
└── data/                           # Volume mount (git-ignored)
    └── eerovista.db                # SQLite database
```

---

## Data Collection Strategy

### Collection Intervals

| Collector | Interval | Endpoints Used | Purpose |
|-----------|----------|----------------|---------|
| Device metrics | 30s | `devices`, `eeros` | Track connections, bandwidth, signal |
| Network metrics | 60s | `networks`, `account` | Overall network health |
| Speedtest passive | On API change | `speedtest` | Collect results from eero-run tests |

### Data Retention Policy

| Data Type | Raw Data | Hourly Aggregates | Daily Aggregates |
|-----------|----------|-------------------|------------------|
| Device connections | 7 days | 30 days | 1 year |
| Network metrics | 7 days | 30 days | 1 year |
| Speedtest results | Forever | N/A | N/A |
| Eero node metrics | 7 days | 30 days | 1 year |

---

## API Endpoints

### Web UI Routes
- `GET /` - Dashboard with graphs and overview
- `GET /devices` - Device list and details
- `GET /network` - Network topology visualization
- `GET /speedtest` - Speedtest history
- `GET /settings` - Configuration display (read-only)

### Prometheus Export
- `GET /metrics` - Prometheus metrics endpoint

Example metrics:
```
# Device metrics
eero_device_connected{mac="...", hostname="...", node="..."} 1
eero_device_signal_strength{mac="...", node="..."} -45
eero_device_bandwidth_mbps{mac="...", direction="download"} 125.3

# Network metrics
eero_network_devices_total 15
eero_network_devices_online 12

# Node metrics
eero_node_status{node="Living Room", location="..."} 1
eero_node_connected_devices{node="Living Room"} 5

# Speedtest metrics
eero_speedtest_download_mbps 950.2
eero_speedtest_upload_mbps 45.8
eero_speedtest_latency_ms 12.4
```

### Zabbix Integration
- `GET /api/zabbix/discovery/devices` - Device discovery (LLD)
- `GET /api/zabbix/discovery/nodes` - Node discovery (LLD)
- `GET /api/zabbix/data?item=<item_key>` - Metric data

### JSON API
- `GET /api/health` - Health check
- `GET /api/devices` - List all devices with latest metrics
- `GET /api/devices/{mac}` - Device detail with history
- `GET /api/network/summary` - Network summary stats

---

## Docker Configuration

### Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./src/
COPY static/ ./static/

# Create data directory
RUN mkdir -p /data

# Expose port
EXPOSE 8080

# Run application
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### docker-compose.yml
```yaml
version: '3.8'

services:
  eerovista:
    build: .
    container_name: eerovista
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    environment:
      # Database
      - DATABASE_PATH=/data/eerovista.db

      # Collection intervals (seconds)
      - COLLECTION_INTERVAL_DEVICES=30
      - COLLECTION_INTERVAL_NETWORK=60

      # Data retention (days)
      - DATA_RETENTION_RAW_DAYS=7
      - DATA_RETENTION_HOURLY_DAYS=30
      - DATA_RETENTION_DAILY_DAYS=365

      # Logging
      - LOG_LEVEL=INFO

      # Eero authentication (set after initial setup)
      # - EERO_SESSION_TOKEN=<token>
```

---

## GitHub Pages Setup

The `docs/` folder contains user and API documentation published via GitHub Pages.

### Enable GitHub Pages
1. Go to repository Settings → Pages
2. Source: Deploy from branch `main` → `/docs`
3. Custom domain (optional)

### Jekyll Configuration
Create `docs/_config.yml`:
```yaml
theme: jekyll-theme-minimal
title: eeroVista
description: Read-only monitoring for Eero mesh networks
```

### Documentation Structure
- **index.md**: Project overview, features, screenshots
- **getting-started.md**: Docker setup, first-run wizard
- **configuration.md**: Environment variables, settings
- **api-reference.md**: API endpoint specifications
- **prometheus.md**: Prometheus integration guide with example configs
- **zabbix.md**: Zabbix template and LLD setup
- **development.md**: Local development setup

---

## Security Considerations

1. **No Control Operations**: System is read-only; cannot modify eero configuration
2. **Session Token Storage**: Encrypted in SQLite config table
3. **API Rate Limiting**: Respect eero API limits to avoid account issues
4. **No Exposed Credentials**: Use environment variables only
5. **Read-Only Database Access**: Web UI has no write capabilities to prevent tampering

---

## Future Enhancements

- **Alerting**: Optional webhook notifications for device offline/online
- **CSV Export**: Download historical data as CSV
- **Advanced Filtering**: Filter devices by type, location, time range
- **Bandwidth Heatmaps**: Visualize usage patterns over time
- **Mobile-Responsive Design**: Optimize UI for mobile devices
- **Multi-Network Support**: Monitor multiple eero networks from one instance
