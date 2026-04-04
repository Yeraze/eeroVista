# Reverse Proxy & HTTPS Setup

This guide covers deploying eeroVista behind a reverse proxy with TLS termination for secure HTTPS access.

## Why Use a Reverse Proxy?

- **HTTPS/TLS encryption** for all traffic between browser and server
- **Custom domain names** instead of IP:port access
- **Centralized certificate management** with automatic renewal
- **Additional security headers** and access control

## Nginx

### Basic HTTPS with Let's Encrypt

1. Install Nginx and Certbot on your host:
   ```bash
   sudo apt install nginx certbot python3-certbot-nginx
   ```

2. Create the Nginx site configuration:

   ```nginx
   # /etc/nginx/sites-available/eerovista
   server {
       listen 80;
       server_name eerovista.example.com;

       # Redirect HTTP to HTTPS
       return 301 https://$host$request_uri;
   }

   server {
       listen 443 ssl http2;
       server_name eerovista.example.com;

       ssl_certificate /etc/letsencrypt/live/eerovista.example.com/fullchain.pem;
       ssl_certificate_key /etc/letsencrypt/live/eerovista.example.com/privkey.pem;

       # Modern TLS settings
       ssl_protocols TLSv1.2 TLSv1.3;
       ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
       ssl_prefer_server_ciphers off;

       # Security headers
       add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
       add_header X-Content-Type-Options nosniff always;
       add_header X-Frame-Options DENY always;
       add_header Referrer-Policy strict-origin-when-cross-origin always;

       location / {
           proxy_pass http://127.0.0.1:8080;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;

           # Timeouts for long-running API requests
           proxy_read_timeout 90s;
           proxy_connect_timeout 10s;
       }

       # Prometheus metrics -- restrict to local/monitoring network
       location /metrics {
           proxy_pass http://127.0.0.1:8080/metrics;
           allow 10.0.0.0/8;
           allow 172.16.0.0/12;
           allow 192.168.0.0/16;
           deny all;
       }
   }
   ```

3. Enable the site and obtain a certificate:
   ```bash
   sudo ln -s /etc/nginx/sites-available/eerovista /etc/nginx/sites-enabled/
   sudo certbot --nginx -d eerovista.example.com
   sudo nginx -t && sudo systemctl reload nginx
   ```

Certbot will automatically configure certificate renewal via a systemd timer.

### Nginx in Docker Compose

If you prefer running Nginx alongside eeroVista in Docker Compose, see the [Traefik section](#traefik-with-docker-compose) below for a more Docker-native approach, or mount your Nginx config into an Nginx container:

```yaml
services:
  eerovista:
    image: eerovista:latest
    container_name: eerovista
    restart: unless-stopped
    volumes:
      - ./data:/data
    environment:
      - DATABASE_PATH=/data/eerovista.db
      - TZ=America/New_York
    # No published ports -- only accessible via the reverse proxy network
    networks:
      - proxy

  nginx:
    image: nginx:alpine
    container_name: nginx-proxy
    restart: unless-stopped
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./nginx/eerovista.conf:/etc/nginx/conf.d/default.conf:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on:
      - eerovista
    networks:
      - proxy

networks:
  proxy:
    driver: bridge
```

In this setup, change `proxy_pass` to `http://eerovista:8080` (using the Docker service name).

## Traefik with Docker Compose

Traefik is a reverse proxy designed for container environments with automatic service discovery and Let's Encrypt integration.

### docker-compose.yml

```yaml
services:
  traefik:
    image: traefik:v3.3
    container_name: traefik
    restart: unless-stopped
    command:
      - "--api.dashboard=false"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--entrypoints.web.http.redirections.entryPoint.to=websecure"
      - "--certificatesresolvers.letsencrypt.acme.httpchallenge.entrypoint=web"
      - "--certificatesresolvers.letsencrypt.acme.email=you@example.com"
      - "--certificatesresolvers.letsencrypt.acme.storage=/letsencrypt/acme.json"
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./letsencrypt:/letsencrypt
    networks:
      - proxy

  eerovista:
    image: eerovista:latest
    container_name: eerovista
    restart: unless-stopped
    volumes:
      - ./data:/data
    environment:
      - DATABASE_PATH=/data/eerovista.db
      - TZ=America/New_York
      - COLLECTION_INTERVAL_DEVICES=30
      - COLLECTION_INTERVAL_NETWORK=60
      - DATA_RETENTION_RAW_DAYS=7
      - DATA_RETENTION_HOURLY_DAYS=30
      - DATA_RETENTION_DAILY_DAYS=365
      - LOG_LEVEL=INFO
      - ENCRYPTION_KEY=change-me-to-a-random-base64-string
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.eerovista.rule=Host(`eerovista.example.com`)"
      - "traefik.http.routers.eerovista.entrypoints=websecure"
      - "traefik.http.routers.eerovista.tls.certresolver=letsencrypt"
      - "traefik.http.services.eerovista.loadbalancer.server.port=8080"
      # Security headers middleware
      - "traefik.http.middlewares.eerovista-headers.headers.stsSeconds=63072000"
      - "traefik.http.middlewares.eerovista-headers.headers.stsIncludeSubdomains=true"
      - "traefik.http.middlewares.eerovista-headers.headers.contentTypeNosniff=true"
      - "traefik.http.middlewares.eerovista-headers.headers.frameDeny=true"
      - "traefik.http.middlewares.eerovista-headers.headers.referrerPolicy=strict-origin-when-cross-origin"
      - "traefik.http.routers.eerovista.middlewares=eerovista-headers"
    networks:
      - proxy

networks:
  proxy:
    driver: bridge
```

**Setup steps:**

1. Replace `eerovista.example.com` with your domain
2. Replace `you@example.com` with your email for Let's Encrypt notifications
3. Generate a unique `ENCRYPTION_KEY` (see [Security Recommendations](#security-recommendations))
4. Create directories: `mkdir -p data letsencrypt`
5. Start: `docker compose up -d`

Traefik will automatically obtain and renew TLS certificates from Let's Encrypt.

## Security Recommendations

### Generate a Unique Encryption Key

eeroVista uses an encryption key to secure stored session tokens. Generate a random key:

```bash
openssl rand -base64 32
```

Set this as the `ENCRYPTION_KEY` environment variable. Keep it consistent across container restarts to avoid losing access to stored tokens.

### Use Environment Files for Secrets

Store sensitive values in a `.env` file instead of directly in `docker-compose.yml`:

```bash
# .env (add to .gitignore)
ENCRYPTION_KEY=your-generated-key-here
EERO_SESSION_TOKEN=
```

```yaml
# docker-compose.yml
services:
  eerovista:
    env_file:
      - .env
```

### Network Isolation

Keep eeroVista on an internal Docker network with only the reverse proxy having external access:

```yaml
services:
  eerovista:
    # No "ports" section -- not directly accessible from outside Docker
    networks:
      - internal

  traefik:
    ports:
      - "80:80"
      - "443:443"
    networks:
      - internal
      - proxy

networks:
  internal:
    internal: true   # No external access
  proxy:
    driver: bridge
```

### Restrict Monitoring Endpoints

If you expose Prometheus metrics, restrict access to your monitoring network (see the Nginx example above). For Traefik, use an IP allowlist middleware:

```yaml
labels:
  - "traefik.http.middlewares.metrics-allowlist.ipallowlist.sourcerange=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
```

### Additional Hardening

- **Disable Traefik dashboard** in production (`api.dashboard=false`)
- **Keep Docker socket access read-only** (`:ro` on the volume mount)
- **Run eeroVista as non-root** (already the default in the container)
- **Enable automatic updates** for the reverse proxy container
- **Use firewall rules** (ufw/iptables) to restrict access to ports 80/443

## Self-Signed Certificates (Local Networks)

If you run eeroVista on a local network without a public domain, you can use self-signed certificates:

```bash
mkdir -p certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout certs/eerovista.key \
  -out certs/eerovista.crt \
  -subj "/CN=eerovista.local"
```

Use these with the Nginx Docker Compose setup by updating the config to reference `/etc/nginx/certs/eerovista.crt` and `/etc/nginx/certs/eerovista.key`.

**Note:** Browsers will show a security warning for self-signed certificates. You can add an exception or install the certificate in your OS trust store.
