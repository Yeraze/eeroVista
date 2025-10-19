# Prometheus Integration

Guide for integrating eeroVista with Prometheus for metrics collection and alerting.

## Overview

eeroVista exposes a `/metrics` endpoint compatible with Prometheus scraping. This allows you to:
- Collect time-series metrics from your Eero network
- Create Grafana dashboards
- Set up alerts for device connectivity and network issues
- Monitor long-term trends

## Metrics Endpoint

**URL**: `http://<eerovista-host>:8080/metrics`

**Format**: Prometheus text exposition format

**Update Frequency**: Metrics reflect the latest collected data (typically 30-60 seconds old)

## Prometheus Configuration

### Basic Scrape Config

Add this to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'eerovista'
    scrape_interval: 60s
    scrape_timeout: 10s
    static_configs:
      - targets: ['eerovista:8080']
        labels:
          instance: 'home'
          network: 'eero'
```

### Docker Compose Setup

If running Prometheus in Docker alongside eeroVista:

```yaml
version: '3.8'

services:
  eerovista:
    image: eerovista:latest
    container_name: eerovista
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    networks:
      - monitoring

  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus-data:/prometheus
    networks:
      - monitoring
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'

networks:
  monitoring:
    driver: bridge

volumes:
  prometheus-data:
```

## Available Metrics

### Device Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `eero_device_connected` | gauge | mac, hostname, node | Connection status (1=online, 0=offline) |
| `eero_device_signal_strength` | gauge | mac, hostname, node | WiFi signal strength (dBm) |
| `eero_device_bandwidth_mbps` | gauge | mac, hostname, direction | Bandwidth usage (download/upload) |

**Example**:
```promql
eero_device_connected{mac="AA:BB:CC:DD:EE:FF",hostname="Johns-iPhone",node="Living Room"} 1
eero_device_signal_strength{mac="AA:BB:CC:DD:EE:FF",hostname="Johns-iPhone",node="Living Room"} -45
eero_device_bandwidth_mbps{mac="AA:BB:CC:DD:EE:FF",hostname="Johns-iPhone",direction="download"} 125.3
```

### Network Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `eero_network_devices_total` | gauge | - | Total known devices |
| `eero_network_devices_online` | gauge | - | Currently connected devices |

**Example**:
```promql
eero_network_devices_total 15
eero_network_devices_online 12
```

### Node Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `eero_node_status` | gauge | node, location, gateway | Node status (1=online, 0=offline) |
| `eero_node_connected_devices` | gauge | node | Devices connected to this node |

**Example**:
```promql
eero_node_status{node="Living Room",location="Living Room",gateway="true"} 1
eero_node_connected_devices{node="Living Room"} 5
```

### Speedtest Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `eero_speedtest_download_mbps` | gauge | - | Latest download speed |
| `eero_speedtest_upload_mbps` | gauge | - | Latest upload speed |
| `eero_speedtest_latency_ms` | gauge | - | Latest latency |

**Example**:
```promql
eero_speedtest_download_mbps 950.2
eero_speedtest_upload_mbps 45.8
eero_speedtest_latency_ms 12.4
```

## Example Queries

### Device Connectivity

**Count online devices**:
```promql
sum(eero_device_connected)
```

**Offline devices**:
```promql
eero_device_connected == 0
```

**Devices per node**:
```promql
sum by (node) (eero_device_connected)
```

### Signal Quality

**Average signal strength**:
```promql
avg(eero_device_signal_strength)
```

**Weak signals (worse than -70 dBm)**:
```promql
eero_device_signal_strength < -70
```

**Signal strength by node**:
```promql
avg by (node) (eero_device_signal_strength)
```

### Bandwidth Usage

**Total download bandwidth**:
```promql
sum(eero_device_bandwidth_mbps{direction="download"})
```

**Top 5 bandwidth consumers**:
```promql
topk(5, eero_device_bandwidth_mbps{direction="download"})
```

**Upload vs Download ratio**:
```promql
sum(eero_device_bandwidth_mbps{direction="upload"}) / sum(eero_device_bandwidth_mbps{direction="download"})
```

### Network Health

**Network uptime percentage (last 24h)**:
```promql
avg_over_time(eero_network_devices_online[24h]) / avg_over_time(eero_network_devices_total[24h]) * 100
```

**Speedtest download trend (last 7 days)**:
```promql
avg_over_time(eero_speedtest_download_mbps[7d])
```

## Alerting Rules

Create an `alerts.yml` file:

```yaml
groups:
  - name: eero_network
    interval: 60s
    rules:
      # Alert if network has no devices online
      - alert: NetworkDown
        expr: eero_network_devices_online == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Eero network appears down"
          description: "No devices connected for 5 minutes"

      # Alert if a specific device goes offline
      - alert: DeviceOffline
        expr: eero_device_connected{hostname="Critical-Device"} == 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Device {{ $labels.hostname }} is offline"
          description: "{{ $labels.hostname }} has been offline for 2 minutes"

      # Alert if signal strength is poor
      - alert: WeakSignal
        expr: eero_device_signal_strength < -75
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Weak WiFi signal for {{ $labels.hostname }}"
          description: "Signal strength {{ $value }}dBm on {{ $labels.node }}"

      # Alert if speedtest results are degraded
      - alert: SlowInternetSpeed
        expr: eero_speedtest_download_mbps < 100
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "Internet speed degraded"
          description: "Download speed {{ $value }}Mbps (expected >100Mbps)"

      # Alert if an eero node goes offline
      - alert: EeroNodeOffline
        expr: eero_node_status == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Eero node {{ $labels.node }} is offline"
          description: "Node at {{ $labels.location }} has been offline for 5 minutes"
```

Reference in `prometheus.yml`:
```yaml
rule_files:
  - 'alerts.yml'

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']
```

## Grafana Dashboards

### Import Pre-Built Dashboard

A Grafana dashboard for eeroVista is available (coming soon).

**Dashboard ID**: TBD

**Import Steps**:
1. Open Grafana
2. Go to Dashboards → Import
3. Enter dashboard ID or upload JSON
4. Select Prometheus data source
5. Click Import

### Create Custom Dashboard

**Panel Examples**:

**1. Network Overview**:
- Stat panel: `eero_network_devices_online` / `eero_network_devices_total`
- Time series: `eero_network_devices_online`

**2. Device List**:
- Table panel with query:
  ```promql
  eero_device_connected
  ```
- Columns: hostname, node, signal_strength, bandwidth

**3. Signal Heatmap**:
- Heatmap panel:
  ```promql
  eero_device_signal_strength
  ```

**4. Bandwidth Graph**:
- Time series:
  ```promql
  sum by (direction) (eero_device_bandwidth_mbps)
  ```

**5. Speedtest History**:
- Time series:
  ```promql
  eero_speedtest_download_mbps
  eero_speedtest_upload_mbps
  ```

## Troubleshooting

### Metrics Not Appearing

1. **Verify endpoint is accessible**:
   ```bash
   curl http://eerovista:8080/metrics
   ```

2. **Check Prometheus targets**:
   - Open `http://prometheus:9090/targets`
   - Ensure eerovista target is UP

3. **Review Prometheus logs**:
   ```bash
   docker logs prometheus
   ```

### Stale Metrics

- Metrics reflect eeroVista's collection intervals (30-60s)
- If data seems old, check eerovista logs:
  ```bash
  docker logs eerovista
  ```

### High Cardinality

With many devices, metric cardinality can be high. Consider:
- Filtering devices by labels in queries
- Reducing scrape frequency to 120s
- Using recording rules for common aggregations

## Best Practices

1. **Scrape Interval**: 60 seconds recommended (matches collection frequency)
2. **Retention**: 30 days minimum for trend analysis
3. **Labels**: Use device hostname, not MAC, in dashboards for readability
4. **Aggregation**: Use recording rules for frequently-used queries
5. **Alerts**: Set appropriate `for` durations to avoid flapping

## Example Prometheus Stack

Complete monitoring stack with Grafana:

```yaml
version: '3.8'

services:
  eerovista:
    image: eerovista:latest
    networks:
      - monitoring

  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - ./alerts.yml:/etc/prometheus/alerts.yml
      - prometheus-data:/prometheus
    networks:
      - monitoring
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    volumes:
      - grafana-data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    networks:
      - monitoring
    ports:
      - "3000:3000"

  alertmanager:
    image: prom/alertmanager:latest
    volumes:
      - ./alertmanager.yml:/etc/alertmanager/alertmanager.yml
    networks:
      - monitoring
    ports:
      - "9093:9093"

networks:
  monitoring:

volumes:
  prometheus-data:
  grafana-data:
```

Access:
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000` (admin/admin)
- Alertmanager: `http://localhost:9093`
