# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

eeroVista is a **read-only** web-based monitoring tool for Eero Mesh Network devices. It runs in a Docker container and provides:
- Interactive web interface with graphs and tables of network status
- API endpoints for external monitoring systems (Prometheus, Zabbix)
- Uses the `eero-client` Python package for authentication and network queries
- SQLite database for persistent data storage

**Important**: This is a view/query-only system. No control operations (reboots, configuration changes, etc.) are supported.

## Architecture

The project is organized as:
- Docker containerized application
- Python backend using the eero-client package for network communication
- Web interface for visualization using **Catppuccin Latte** color theme
- SQLite database for time-series metric storage
- Export endpoints compatible with Prometheus and Zabbix
- Documentation in `docs/` folder published via GitHub Pages

## Design Guidelines

- **Frontend Theme**: Use Catppuccin Latte color palette for all UI components
- **Read-Only**: Only use GET endpoints from eero-client API; no POST operations for control
- **Data Collection**: Background collectors query eero API at configurable intervals
- **Documentation**: Maintain user and API documentation in `docs/` for GitHub Pages

## Development Commands

(To be added as project structure is defined)
- Never push directly to main, always create a branch & PR