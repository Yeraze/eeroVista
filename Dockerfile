FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libffi-dev \
    dnsmasq \
    supervisor \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY static/ ./static/

# Copy configuration files
COPY config/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Create data directory and DNS directories
RUN mkdir -p /data /etc/dnsmasq.d /var/run/dnsmasq

# Create empty hosts file for dnsmasq
RUN touch /etc/dnsmasq.d/eerovista.hosts

# Expose ports (web and DNS)
EXPOSE 8080
EXPOSE 53/udp
EXPOSE 53/tcp

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_PATH=/data/eerovista.db

# Run application via entrypoint script
CMD ["/docker-entrypoint.sh"]
