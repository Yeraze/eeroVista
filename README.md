# eeroVista

<div align="center">
  <img src="eerovista.png" alt="eeroVista Logo" width="200"/>

  <p><strong>Read-only monitoring for Eero mesh networks</strong></p>

  [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
  [![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
  [![Docker Image](https://ghcr-badge.egpl.dev/yeraze/eerovista/latest_tag?color=%235b4566&ignore=latest,main,sha256*&label=version&trim=major)](https://github.com/Yeraze/eeroVista/pkgs/container/eeroVista)
[![Docker Pulls](https://ghcr-badge.egpl.dev/yeraze/eerovista/size?color=%235b4566&tag=latest&label=image%20size&trim=)](https://github.com/Yeraze/eeroVista/pkgs/container/eeroVista)
</div>

---

## Overview

eeroVista is a **read-only** web-based monitoring tool for Eero mesh networks. It provides:

- 📊 **Real-time Dashboard** - View network status, connected devices, and bandwidth usage
- 📈 **Historical Data** - Track device connections and network performance over time
- 🚀 **Speedtest History** - Monitor ISP performance with historical speedtest results
- 🔔 **Notifications** - Configurable alerts via 100+ services (email, Slack, Discord, Telegram, webhooks, and more) powered by [Apprise](https://github.com/caronc/apprise)
- 🔗 **Device Groups** - Combine multiple network interfaces from the same physical device into a single logical entry with aggregated bandwidth
- 🔌 **Multi-Format Exports** - Prometheus metrics, Zabbix LLD, and JSON API
- 🎨 **Beautiful UI** - Clean interface using the Catppuccin Latte color theme
- 🐳 **Docker-Ready** - Simple container deployment with persistent storage

## Features

### Web Interface
- Network overview dashboard with real-time statistics
- Device list with connection status, signal strength, and bandwidth
- Device grouping to combine multiple interfaces (e.g., wired + wireless) into a single logical device
- Network topology visualization showing mesh node connections
- Speedtest history graphs and trends
- Notification management with rule configuration and history
- Clean, accessible UI with Catppuccin Latte theme

### Notifications
- **5 alert types**: Node offline, device offline, new device connected, high bandwidth usage, firmware updates available
- **100+ delivery services** via [Apprise](https://github.com/caronc/apprise): email, Slack, Discord, Telegram, Microsoft Teams, webhooks, and more
- Configurable cooldown periods per rule to prevent alert fatigue
- Notification history tracking with deduplication
- Test notification support from the Settings page

### Monitoring Integration
- **Prometheus** metrics endpoint for scraping
- **Zabbix** Low-Level Discovery (LLD) for devices and nodes
- **JSON API** for custom integrations
- Health check endpoint for uptime monitoring

### Data Collection
- Automatic background collection of device metrics (every 30s)
- Network-wide statistics (every 60s)
- Notification rule evaluation (every 60s)
- Passive speedtest result collection
- Configurable data retention policies

## Quick Start

### Using Docker Compose (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/Yeraze/eeroVista.git
   cd eeroVista
   ```

2. Create data directory:
   ```bash
   mkdir data
   ```

3. Start the container:
   ```bash
   docker compose up -d
   ```

4. Open your browser to `http://localhost:8080`

5. Complete the first-run setup wizard to authenticate with your Eero account

### Using Docker Run

```bash
docker run -d \
  --name eerovista \
  -p 8080:8080 \
  -v $(pwd)/data:/data \
  --restart unless-stopped \
  yeraze/eerovista:latest
```

## Documentation

Full documentation is available at [https://yeraze.github.io/eeroVista/](https://yeraze.github.io/eeroVista/)

- [Getting Started Guide](docs/getting-started.md)
- [Configuration Reference](docs/configuration.md)
- [API Documentation](docs/api-reference.md)
- [Prometheus Integration](docs/prometheus.md)
- [Zabbix Integration](docs/zabbix.md)
- [Development Guide](docs/development.md)
- [Architecture Documentation](ARCHITECTURE.md)

## Screenshots

### Dashboard
![Dashboard](docs/images/mainpage.png)
*Real-time network overview with bandwidth usage, top consumers, and network statistics*

### Device List
![Device List](docs/images/devicelist.png)
*Connected devices with status, IP addresses, signal strength, and port forwarding indicators*

### Device Details
![Device Details](docs/images/device-detail.png)
*Individual device metrics, bandwidth graphs, DNS aliases, and port forward configuration*

### Network Topology
![Network Topology](docs/images/nodes.png)
*Mesh network topology showing nodes, connection quality, and routing configuration*

### Topology Visualization
![Topology Visualization](docs/images/topology.png)
*Visual representation of network mesh connections and device distribution*

## Important Notes

⚠️ **Read-Only System**: eeroVista cannot modify your Eero configuration, reboot devices, or trigger speedtests. It only reads existing data from your network.

⚠️ **Unofficial**: This project uses reverse-engineered APIs and is not affiliated with or endorsed by Eero.

⚠️ **Local Storage**: All data is stored locally in SQLite. No data is sent to external services.

⚠️ **Amazon Login Limitation**: If your Eero account uses Amazon for login, eeroVista may not work directly due to API limitations. **Workaround**: Have someone in your household create a standard Eero account (with email/password) and invite them as an admin to your network. Then use those credentials to authenticate eeroVista.

## Troubleshooting & FAQ

### I see all my devices but no bandwidth data
This is normal behavior. eeroVista does not have access to historical data from before it was started. Only bandwidth and connection data collected **after the container launches** will be tracked. You should start seeing bandwidth graphs after data has been collected for a few minutes.

### Authentication fails with "Account linked with Amazon" error
Your Eero account is linked to Amazon Login, which is not directly supported by the API. See the workaround in the Important Notes section above - create a separate admin account using email/password authentication.

### Data appears to be missing after restart
If you restart the container without persisting the `/data` directory, all collected data will be lost. Make sure you're using a volume mount (as shown in the Quick Start) to persist your database.

## Configuration

Configure eeroVista via environment variables in `docker-compose.yml`:

```yaml
environment:
  # Collection intervals (seconds)
  - COLLECTION_INTERVAL_DEVICES=30      # Device metrics
  - COLLECTION_INTERVAL_NETWORK=60      # Network metrics

  # Data retention (days)
  - DATA_RETENTION_RAW_DAYS=7           # Raw time-series data
  - DATA_RETENTION_HOURLY_DAYS=30       # Hourly aggregates
  - DATA_RETENTION_DAILY_DAYS=365       # Daily aggregates

  # Logging
  - LOG_LEVEL=INFO                      # DEBUG, INFO, WARNING, ERROR
```

See [Configuration Reference](docs/configuration.md) for all options.

## API Endpoints

### Web Interface
- `/` - Dashboard
- `/devices` - Device list
- `/network` - Network topology
- `/speedtest` - Speedtest history

### Notifications & Device Groups
- `/api/notification-settings` - Apprise URL configuration (GET/PUT)
- `/api/notification-rules` - Notification rule CRUD
- `/api/notification-history` - Recent notification history
- `/api/device-groups` - Device group management

### Monitoring Integration
- `/metrics` - Prometheus metrics
- `/api/health` - Health check
- `/api/devices` - JSON device list
- `/api/zabbix/discovery/devices` - Zabbix device discovery
- `/api/zabbix/discovery/nodes` - Zabbix node discovery

See [API Reference](docs/api-reference.md) for complete documentation.

## Technology Stack

- **Backend**: FastAPI, SQLAlchemy, APScheduler
- **Frontend**: Jinja2, Chart.js, Bootstrap (Catppuccin Latte theme)
- **Database**: SQLite
- **API Client**: eero-client Python package
- **Containerization**: Docker

## Development

### Local Setup

```bash
# Clone repository
git clone https://github.com/Yeraze/eeroVista.git
cd eeroVista

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8080
```

See [Development Guide](docs/development.md) for detailed setup instructions.

### Running Tests

```bash
pytest
pytest --cov=src --cov-report=html
```

## Contributing

Contributions are welcome! Please see the [Development Guide](docs/development.md) for:
- Setting up your development environment
- Code style guidelines (Black, Ruff)
- Testing requirements
- Pull request process

### Workflow

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes and add tests
4. Run tests and linters: `pytest && black src/ && ruff check src/`
5. Commit your changes: `git commit -m "feat: Add my feature"`
6. Push to your fork: `git push origin feature/my-feature`
7. Open a Pull Request

## Roadmap

- [x] Initial release
  - [x] Core architecture and documentation
  - [x] Database models and collectors
  - [x] Web interface with Catppuccin theme
  - [x] Prometheus exporter
  - [x] Zabbix integration
  - [x] Docker image

- [x] Notifications
  - [x] Apprise-based notification delivery (100+ services)
  - [x] Node offline / device offline alerts
  - [x] New device detection
  - [x] High bandwidth alerts
  - [x] Firmware update alerts
  - [x] Configurable cooldowns and history

- [x] Device Groups
  - [x] Combine multiple interfaces into logical devices
  - [x] Aggregated bandwidth display

- [ ] Future enhancements
  - [ ] CSV export functionality
  - [ ] Advanced device filtering
  - [ ] Bandwidth heatmaps
  - [ ] Mobile-responsive design

## License

MIT License - See [LICENSE](LICENSE) file for details

## Acknowledgments

- [eero-client](https://github.com/343max/eero-client) - Python library for Eero API
- [Catppuccin](https://github.com/catppuccin/catppuccin) - Soothing pastel theme
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [Chart.js](https://www.chartjs.org/) - JavaScript charting library

## Support

- **Documentation**: [https://yeraze.github.io/eeroVista/](https://yeraze.github.io/eeroVista/)
- **Issues**: [GitHub Issues](https://github.com/Yeraze/eeroVista/issues)
- **Discussions**: [GitHub Discussions](https://github.com/Yeraze/eeroVista/discussions)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=yeraze/eeroVista&type=date&legend=top-left)](https://www.star-history.com/#yeraze/eeroVista&type=date&legend=top-left)
---

<div align="center">
  Made with ❤️ using the Catppuccin Latte theme
</div>
