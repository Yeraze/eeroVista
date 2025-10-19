# eeroVista

A read-only web-based monitoring tool for Eero mesh networks.

## Features

- **Real-time Dashboard**: View network status, connected devices, and bandwidth usage
- **Historical Data**: Track device connections and network performance over time
- **Speedtest History**: Monitor ISP performance with historical speedtest results
- **Multi-Format Exports**:
  - Prometheus metrics endpoint
  - Zabbix LLD integration
  - JSON API for custom integrations
- **Beautiful UI**: Clean interface using the Catppuccin Latte color theme
- **Docker-Ready**: Simple container deployment with persistent storage

## Quick Start

### Using Docker Compose

1. Clone the repository:
   ```bash
   git clone https://github.com/yeraze/eerovista.git
   cd eerovista
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

## Documentation

- [Getting Started Guide](getting-started.md)
- [Configuration Reference](configuration.md)
- [API Documentation](api-reference.md)
- [Prometheus Integration](prometheus.md)
- [Zabbix Integration](zabbix.md)
- [Development Guide](development.md)

## Screenshots

(To be added)

## Important Notes

- **Read-Only**: eeroVista cannot modify your Eero configuration or reboot devices
- **Unofficial**: This project uses reverse-engineered APIs and is not affiliated with Eero
- **Local Storage**: All data is stored locally in SQLite; no external services required

## License

MIT License - See LICENSE file for details

## Contributing

Contributions are welcome! Please see [Development Guide](development.md) for setup instructions.
