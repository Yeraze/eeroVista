#!/bin/bash
set -e

# Generate dnsmasq configuration with domain from environment variable
DNS_DOMAIN=${DNS_DOMAIN:-eero.local}

cat > /etc/dnsmasq.conf <<EOF
# dnsmasq configuration for eeroVista
# LOCAL-ONLY DNS resolution for devices managed by eeroVista
# No upstream forwarding - only answers queries from local hosts file
# Domain: ${DNS_DOMAIN}

# Don't read /etc/resolv.conf or /etc/hosts
no-resolv
no-hosts

# Listen on all interfaces
listen-address=0.0.0.0

# Don't bind to specific interfaces
bind-interfaces

# NO UPSTREAM SERVERS - local resolution only
# Any query not in our hosts file returns NXDOMAIN

# Read additional hosts from our generated file
addn-hosts=/etc/dnsmasq.d/eerovista.hosts

# Cache DNS queries
cache-size=1000

# Log queries for debugging (comment out in production)
log-queries
log-facility=/var/log/dnsmasq.log

# Domain for local devices
domain=${DNS_DOMAIN}
local=/${DNS_DOMAIN}/

# Handle all queries locally - never forward anything
local=//

# Block DNS-SD and mDNS queries
local=/_dns-sd._udp/
local=/_tcp.local/
local=/_udp.local/
local=/local/

# Never forward plain names (without a dot or domain part)
domain-needed

# Never forward addresses in the non-routed address spaces
bogus-priv

# Enable DHCP lease integration (disabled since we're read-only)
# We only provide DNS, not DHCP
EOF

echo "DNS domain configured as: ${DNS_DOMAIN}"

# Start supervisor
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
