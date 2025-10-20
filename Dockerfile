# Build stage - includes build tools needed for compiling Python packages
FROM python:3.11-slim AS builder

# Set working directory
WORKDIR /app

# Install build dependencies (only needed during pip install)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Final stage - minimal runtime image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install only runtime dependencies (no compilers!)
RUN apt-get update && apt-get install -y \
    libffi8 \
    dnsmasq \
    supervisor \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder stage
COPY --from=builder /install /usr/local

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
