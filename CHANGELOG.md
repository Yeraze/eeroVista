# Changelog

## [2.8.1] — 2026-06-13

### Fixed

- **MCP server behind a reverse proxy**: The MCP endpoint rejected proxied requests with `421 Invalid Host header` because the transport's DNS-rebinding protection only trusted `localhost`. Added `MCP_ALLOWED_HOSTS` (comma-separated public hostnames, or `*` to trust the proxy) so the configured host is accepted. Also enabled uvicorn proxy-header handling (`--proxy-headers`/`forwarded_allow_ips`) so the `/mcp` → `/mcp/` redirect respects `X-Forwarded-Proto` instead of downgrading to `http://`. Documented the trailing-slash endpoint (`/mcp/`) and proxy requirements.

## [2.8.0] — 2026-06-13

### Added

- **MCP server for AI agents**: New optional [Model Context Protocol](docs/mcp.md) server exposing a curated set of 12 read-only tools (network summary, device/node lists, health score, WAN uptime, outages, speedtests, signal quality, top bandwidth users, and more) over Streamable HTTP. Mounted on the existing web server at a configurable path (`MCP_PATH`, default `/mcp`) and disabled by default (`MCP_ENABLED`). The tools reuse the existing REST query logic, so output matches the API. The endpoint has no authentication — expose only behind a trusted reverse proxy.

## [2.7.2] — 2026-05-26

### Fixed

- **Offline notification flapping**: Raised offline detection threshold from hardcoded 2 to configurable 3+ consecutive readings. Added collection-gap awareness — records separated by a failed collection cycle (>5× collection interval) are no longer treated as continuous offline evidence. Downgraded "Large time delta detected" log from warning to debug. ([#117])
- **Config validation**: Added Pydantic field validators to guard against nonsensical values for `offline_consecutive_threshold` and `offline_min_duration_seconds`. ([#117])

## [2.7.1] — 2026-05-18

### Added

- **MQTT publishing with Home Assistant auto-discovery**: Publish device online/offline status, bandwidth metrics, and eero node status to MQTT. Home Assistant auto-discovers the sensors. ([#112])
- **Reverse proxy / HTTPS setup guide**: New documentation for running eeroVista behind nginx/Caddy with TLS. ([#113])
  - **mypy in CI**: Added type-checking to the CI pipeline. ([#109])

### Fixed

- **eero_patch not applying during Account validation**: The monkey-patch for the eero-client library now takes effect before any API calls are made, fixing authentication failures. ([#114])

### Changed

- **Test coverage**: Increased test coverage from 45% to 87% across `src/`. ([#111])
- **Refactored health endpoint**: Split `health.py` (2633 lines) into a `health/` subpackage for maintainability. ([#109])

## [2.7.0] — 2026-03-29

### Added

- **Offline notification debounce**: No longer fires offline notifications on a single missed reading — requires 2 consecutive offline statuses before alerting. ([#106])
- **Recovery notifications**: Sends a "back online" notification when a previously-offline node or device comes back up. ([#106])

## [2.6.4] — 2026-03-26

### Fixed

- **Speedtest model normalization**: Handle both `Speedtest` and `Speed` Pydantic models from the eero API depending on the client version. Added diagnostic logging to detect future model changes. ([#105])

## [2.6.3] — 2026-03-25

### Fixed

- **Speedtest timestamp matching**: Strip timezone info from API timestamps to match SQLite's naive datetime storage correctly.
- **Speedtest collector logging**: Upgraded key log messages from debug to info/warning so collection issues are visible in default log level. ([#104])

## [2.6.2] — 2026-03-25

### Fixed

- **Speedtest NULL backfill**: Backfills NULL speedtest records that were created by a broken collector, preventing gaps in the speedtest history chart. ([#102])
- **ISP timezone crash**: Resolved `ValueError: astimezone() cannot be applied to a naive datetime` in ISP outage detection when comparing aware and naive datetimes. ([#101])

## [2.6.1] — 2026-03-24

### Added

- **WAN outage detection from collection gaps**: Detects ISP/WAN outages when data collection gaps exceed expected intervals, using the speedtest history as ground-truth. ([#99])

### Fixed

- **Speedtest collector with raw API response**: The collector now handles both Pydantic `SpeedtestResult` objects and raw dict responses from the eero API. ([#98])

## [2.6.0] — 2026-03-23

### Added

- **Analytics suite** ([#95]):
  - Node restart detection and bandwidth summary reports (Phase 1)
  - Network health score and ISP reliability tracker (Phase 2)
  - Signal quality trends and speedtest analysis (Phase 3)
  - Device activity patterns and node load analysis (Phase 4)
  - Guest network usage endpoint (Phase 5)
  - Bandwidth utilization heatmap on device detail page
  - Frontend UI for all analytics features
- **Documentation**: Analytics and reports feature guide. ([#94])

### Fixed

- **Starlette 1.0 compatibility**: Updated `TemplateResponse` calls for the new API.
- **WAN status matching**: Fixed query logic for WAN status detection.
- **Daily bandwidth chart memory**: Prevented the chart from growing unboundedly.
- **Timezone handling**: Health score and activity heatmap now respect the configured timezone.
- **NULL bandwidth filtering**: Heatmap no longer includes NULL readings.

## [2.5.3] — 2026-03-19

### Fixed

- **eero-client dependency pins**: Switched to a forked version with relaxed version constraints to resolve dependency resolution failures. ([#90])
- **Snyk vulnerability fixes**: Updated `eero-client`, `starlette`, and `httptools` dependencies. ([#88], [#89])

## [2.5.2] — 2026-03-06

### Fixed

- **Node offline detection**: Now uses the `status` field from `EeroNodeMetric` records for offline detection instead of time-since-last-seen, which was producing false positives during brief API interruptions. ([#86])

## [2.5.1] — 2026-03-05

### Fixed

- **DNS service timezone crash**: Resolved crash from comparing naive/aware datetimes in DNS history queries. ([#84])

## [2.5.0] — 2026-03-05

### Added

- **Apprise notification system** ([#82]):
  - Rule-based notifications (node offline, device offline, high bandwidth, new device, firmware updates)
  - Configurable notification rules with cooldown and skip-until-next-reset
  - Web UI for managing rules, testing, and viewing history
- **Device groups / bonded devices** ([#79]):
  - Group multiple devices together for aggregate bandwidth views
  - CRUD API and migration for device groups
  - Group detail modal with tabbed member details and aggregate bandwidth chart

### Fixed

- **Device offline detection width**: Widened the detection threshold to 5× collection interval to reduce false positives.
- **XSS escaping**: Sanitized user input in notification configuration.
- **Top bandwidth consumers**: Aggregated grouped devices correctly.
- **Prometheus metrics**: Restored missing speedtest and bandwidth metrics. ([#77])

## [2.4.14] — 2026-02-18

### Fixed

- Database vacuum optimization and performance improvements. ([#76])

## [2.4.13] — 2026-02-03

### Fixed

- Current bandwidth display in device dashboard. ([#72])

## [2.4.12] — 2026-02-02

### Added

- Topology view with device icons. ([#71])

## [2.4.10] — 2026-01-17

### Fixed

- Database vacuum and size optimization. ([#68])

## [2.4.9] — 2026-01-06

### Fixed

- Minor bug fixes. ([#66])

## [2.4.8] — 2026-01-05

### Fixed

- Bug fixes. ([#63])

## [2.4.7] — 2025-12-23

### Fixed

- Bug fixes. ([#60])

## [2.4.6] — 2025-11-26

### Fixed

- Bug fixes. ([#58])

## [2.4.5] — 2025-11-14

Initial release. ([#56])

[#56]: https://github.com/Yeraze/eeroVista/pull/56
[#58]: https://github.com/Yeraze/eeroVista/pull/58
[#60]: https://github.com/Yeraze/eeroVista/pull/60
[#63]: https://github.com/Yeraze/eeroVista/pull/63
[#66]: https://github.com/Yeraze/eeroVista/pull/66
[#68]: https://github.com/Yeraze/eeroVista/pull/68
[#71]: https://github.com/Yeraze/eeroVista/pull/71
[#72]: https://github.com/Yeraze/eeroVista/pull/72
[#76]: https://github.com/Yeraze/eeroVista/pull/76
[#77]: https://github.com/Yeraze/eeroVista/pull/77
[#79]: https://github.com/Yeraze/eeroVista/pull/79
[#82]: https://github.com/Yeraze/eeroVista/pull/82
[#84]: https://github.com/Yeraze/eeroVista/pull/84
[#86]: https://github.com/Yeraze/eeroVista/pull/86
[#88]: https://github.com/Yeraze/eeroVista/pull/88
[#89]: https://github.com/Yeraze/eeroVista/pull/89
[#90]: https://github.com/Yeraze/eeroVista/pull/90
[#94]: https://github.com/Yeraze/eeroVista/pull/94
[#95]: https://github.com/Yeraze/eeroVista/pull/95
[#94]: https://github.com/Yeraze/eeroVista/pull/94
[#98]: https://github.com/Yeraze/eeroVista/pull/98
[#99]: https://github.com/Yeraze/eeroVista/pull/99
[#101]: https://github.com/Yeraze/eeroVista/pull/101
[#102]: https://github.com/Yeraze/eeroVista/pull/102
[#104]: https://github.com/Yeraze/eeroVista/pull/104
[#105]: https://github.com/Yeraze/eeroVista/pull/105
[#106]: https://github.com/Yeraze/eeroVista/pull/106
[#109]: https://github.com/Yeraze/eeroVista/pull/109
[#111]: https://github.com/Yeraze/eeroVista/pull/111
[#112]: https://github.com/Yeraze/eeroVista/pull/112
[#113]: https://github.com/Yeraze/eeroVista/pull/113
[#114]: https://github.com/Yeraze/eeroVista/pull/114
[#117]: https://github.com/Yeraze/eeroVista/pull/117

<!--
  Releases with missing PR references: v2.4.7, v2.4.8, v2.4.9, v2.4.10, v2.4.13
  These predate the current changelog format. Link them if PRs are found.
-->
