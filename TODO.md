# eeroVista - Project TODO List

## Pending Features

### Dashboard Performance
- [ ] Speed up hourly graph loading (currently ~5s to switch to/from)
  - Profile API endpoint response time
  - Optimize client-side rendering
  - Consider caching or lazy loading

## Completed
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
