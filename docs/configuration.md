# Configuration Reference

Complete reference for eeroVista configuration options.

## Environment Variables

All configuration is done through environment variables in `docker-compose.yml` or Docker run commands.

### Database Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_PATH` | `/data/eerovista.db` | Path to SQLite database file |

### Collection Intervals

| Variable | Default | Description |
|----------|---------|-------------|
| `COLLECTION_INTERVAL_DEVICES` | `30` | Seconds between device metric collections |
| `COLLECTION_INTERVAL_NETWORK` | `60` | Seconds between network metric collections |

**Recommendations**:
- **Devices**: 30-60 seconds for near real-time tracking
- **Network**: 60-300 seconds for overall health monitoring

### Data Retention

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_RETENTION_RAW_DAYS` | `7` | Days to keep raw time-series data |
| `DATA_RETENTION_HOURLY_DAYS` | `30` | Days to keep hourly aggregates |
| `DATA_RETENTION_DAILY_DAYS` | `365` | Days to keep daily aggregates |

**Disk Usage Estimates** (per day of raw data):
- ~10 MB for 10 devices
- ~50 MB for 50 devices
- ~100 MB for 100 devices

### Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL |

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `EERO_SESSION_TOKEN` | (empty) | Pre-authenticated session token (advanced) |

**Note**: Session token is normally stored in the database after first-run wizard. Only set this variable for advanced use cases like container recreation.

## Docker Compose Example

```yaml
version: '3.8'

services:
  eerovista:
    image: eerovista:latest
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
```

## Performance Tuning

### High-Frequency Monitoring

For near real-time device tracking:
```yaml
environment:
  - COLLECTION_INTERVAL_DEVICES=15    # Collect every 15 seconds
  - DATA_RETENTION_RAW_DAYS=3         # Keep less raw data
```

**Trade-offs**:
- More API calls to Eero (watch for rate limits)
- Higher disk usage
- Better temporal resolution

### Low-Resource Mode

For minimal resource usage:
```yaml
environment:
  - COLLECTION_INTERVAL_DEVICES=120   # Collect every 2 minutes
  - COLLECTION_INTERVAL_NETWORK=300   # Collect every 5 minutes
  - DATA_RETENTION_RAW_DAYS=3         # Keep 3 days raw
  - DATA_RETENTION_HOURLY_DAYS=14     # Keep 2 weeks hourly
```

**Trade-offs**:
- Lower disk usage
- Fewer API calls
- Less granular data

## Volume Mounts

### Data Directory

Mount `/data` for persistent database storage:
```yaml
volumes:
  - ./data:/data              # Local directory
  - /mnt/nas/eerovista:/data  # Network storage
  - eerovista-data:/data      # Named volume
```

### Database Backup

To backup the database:
```bash
# While container is running
docker compose exec eerovista sqlite3 /data/eerovista.db ".backup /data/backup.db"

# Copy backup out
docker cp eerovista:/data/backup.db ./eerovista-backup-$(date +%Y%m%d).db
```

## Network Configuration

### Custom Port

Change the exposed port:
```yaml
ports:
  - "3000:8080"  # Access on http://localhost:3000
```

### Reverse Proxy

Example nginx configuration:
```nginx
server {
    listen 80;
    server_name eerovista.example.com;

    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Security Considerations

### Read-Only Database Access

The web UI has read-only access to the database. Only background collectors can write data.

### Session Token Security

- Session tokens are stored encrypted in the database
- Never commit `docker-compose.yml` with `EERO_SESSION_TOKEN` set
- Use environment file for secrets:

```yaml
env_file:
  - .env.secrets  # Add to .gitignore
```

### Network Isolation

Run on a dedicated Docker network:
```yaml
networks:
  eerovista-net:
    driver: bridge

services:
  eerovista:
    networks:
      - eerovista-net
```

## Troubleshooting Configuration

### View Current Configuration

```bash
# Show environment variables
docker compose exec eerovista env | grep -E "COLLECTION|RETENTION|LOG_LEVEL"

# Check database settings
docker compose exec eerovista sqlite3 /data/eerovista.db "SELECT * FROM config;"
```

### Reset Configuration

To reset to defaults, remove the database and restart:
```bash
docker compose down
rm data/eerovista.db
docker compose up -d
```

**Warning**: This deletes all collected data.

## Advanced: Custom Configuration File

(Future enhancement: Support for YAML/JSON configuration file)

Currently, all configuration is through environment variables. A future version may support:
```yaml
# eerovista.yml
database:
  path: /data/eerovista.db

collectors:
  devices:
    interval: 30
    enabled: true
  network:
    interval: 60
    enabled: true

retention:
  raw_days: 7
  hourly_days: 30
  daily_days: 365
```
