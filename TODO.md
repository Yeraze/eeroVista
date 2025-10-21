# eeroVista - Project TODO List

## Pending Features

### Bugs
- [ ] Fix hourly chart x-axis showing "Invalid date" instead of hour labels
- [ ] Fix 7-day/30-day toggle on main page - currently only affects Top Consumers chart, not Bandwidth Usage chart

### UI Enhancements
- [ ] Redesign device popup layout:
  - Make popup twice as wide
  - Graph at full width across the top
  - Below graph: 2-column layout (device details left, aliases right)

## Completed
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

*Last updated: 2025-10-20*
