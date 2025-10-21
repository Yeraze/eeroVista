# eeroVista - Project TODO List

## Pending Features

(No pending features at this time)

## Completed
- [x] Guest Network Support (2025-10-21)
  - Added is_guest field to DeviceConnection database model
  - Updated device collector to store guest network status from Eero API
  - Added guest network filter checkbox ("Show Guest Network") in device list UI
  - Added visual "GUEST" badge indicator for guest network devices (Catppuccin peach color)
  - Guest devices appear in Device List with clear visual distinction
  - Added database migration for existing users (automatically runs on startup)
  - Tracks guest network connection status separately from main network in time-series data
  - Fixed frontend null check for is_guest filter (explicit boolean comparison)
  - Added comprehensive test coverage:
    - 4 tests for DeviceConnection model with is_guest field
    - 3 tests for DeviceCollector storing is_guest from API data
    - 4 tests for API response structure including is_guest field
    - Tests cover null/undefined handling, defaults, and query operations
- [x] Device manufacturer field support (2025-10-21)
  - Added manufacturer field to Device database model
  - Updated device collector to store manufacturer from Eero API
  - Enhanced device name fallback chain: nickname → hostname → manufacturer → mac_address
  - Updated Device Details popup to show individual name fields (Nickname, Hostname, Manufacturer)
  - Added database migration for existing users (automatically runs on startup)
  - Fixes devices showing MAC addresses instead of readable manufacturer names (e.g., "Oculus VR, LLC")
- [x] Improved bandwidth formatting for small values (2025-10-21)
  - Updated formatBytes() to show KB for values < 1 MB (e.g., "30.72 KB" instead of "0.03 MB")
  - Added Bytes display for values < 1 KB
  - Updated chart y-axis labels to use smart formatting (automatically shows GB/MB/KB/Bytes)
  - Changed y-axis title from "Data Usage (MB)" to "Data Usage" for accuracy
  - Fixes devices with low bandwidth showing misleading "0 MB" values
- [x] Chart data completeness and hourly view fixes (2025-10-21)
  - Fixed device bandwidth endpoint to return full date range (7/30 days) with zeros for missing data
  - Fixed device hourly chart to show only today's data (UTC timezone parsing issue)
  - Aligned Device Details popup bandwidth charts with Dashboard implementation
  - Added incomplete data indicator (lighter colors for today's data)
  - Added category scale to prevent "Invalid date" x-axis issues
  - Added "(incomplete)" notation in tooltips for today's data
  - Added `is_incomplete` flag to device bandwidth endpoint matching network endpoint
  - Corrected collection interval calculation from 60s to 30s
  - Fixed UTC timestamp parsing by appending 'Z' suffix for correct timezone conversion
  - Ensures consistent chart behavior across Dashboard and Device Details views
- [x] v0.9.0 Release - IP reservations and port forwards tracking (PR #23)
  - Backend: Database models, data collector, and API endpoints for DHCP reservations and port forwards
  - Frontend: Tabbed display on Nodes page, visual indicators in Devices List (🔒 for reserved IPs, 🔀 for port forwards)
  - Device popup: Shows reservation status and configured port forwards with protocol badges
  - Performance: O(1) lookups with Map data structures, smart refresh intervals (hourly collector, 60s UI)
  - Testing: 13 unit tests covering models, collector logic, and API endpoints
  - No database migrations required (new tables created automatically)
- [x] v0.8.0 Release - UI bug fixes and improvements (PR #22)
  - Fixed hourly chart x-axis showing "Invalid date" (explicit category scale)
  - Fixed 7-day/30-day toggle not updating bandwidth chart (destroy/recreate strategy)
  - Fixed bandwidth chart date range (now shows full requested range with zeros for missing days)
  - Redesigned device popup: 2x wider (1000px), full-width graph at top, 2-column layout below
  - No database migrations required
- [x] Hourly bandwidth endpoint optimization (PR #21)
  - SQL aggregation optimization: reduced query time from 3.0s to 2.3s (23% improvement)
  - In-memory caching with 5-minute TTL: cached requests now 0.003s (99.9% faster)
  - Overall: 1000x speedup for dashboard refresh scenarios
  - Enhanced Zabbix test suite: 13 unit tests + 20 integration test stubs
- [x] v0.7.1 Release - Zabbix 6.0+ templates with auto-discovery (PR #20)
  - Zabbix 6.0+ compatibility: deprecated applications→tags, proper UUIDs, required groups
  - New auto-discovery template with host prototypes (creates individual hosts for devices/nodes)
  - HTTPS support via configurable macros
  - Enhanced discovery metadata: IP addresses, MAC addresses, firmware versions, connection types
  - Removed separate template files, consolidated into single complete template
  - Comprehensive setup documentation with troubleshooting
- [x] v0.7.0 Release - Dashboard enhancements, timezone fixes, and performance improvements (PR #19)
  - Dashboard enhancements: incomplete data indicator, top 5 bandwidth consumers, hourly charts
  - Timezone fixes: data collection/API alignment, JavaScript date parsing
  - Performance: anti-flicker optimization for chart updates
  - Code quality: SQLAlchemy fixes, error handling improvements, test coverage
- [x] Reduce graph flicker on 30-second auto-refresh (using Chart.js update() instead of destroy/recreate)
- [x] Update 7/30 day bandwidth graphs to include today (with visual indicator for incomplete data)
- [x] Add top 5 bandwidth consumers stacked graph with "Other" category
- [x] Add hourly graph option to device info popup
- [x] PR #18 - Optimize Prometheus endpoint queries (N+1 fix, deprecation fixes, AttributeError bug fix)
- [x] PR #17 - Monitoring endpoints (Prometheus + Zabbix) with test suite
- [x] Pre-built Zabbix template with comprehensive documentation
- [x] v0.6.0 Release - Hourly bandwidth chart, timezone support, Docker optimization

---

*Last updated: 2025-10-21*
