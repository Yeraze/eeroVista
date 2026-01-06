"""DNS service for managing dnsmasq hosts file."""

import json
import logging
import os
import re
import signal
from typing import List, Tuple

from sqlalchemy.orm import Session

from src.models.database import Device, DeviceConnection, EeroNode
from src.utils.database import get_db_context

logger = logging.getLogger(__name__)

# Path to dnsmasq hosts file
HOSTS_FILE_PATH = os.getenv("DNSMASQ_HOSTS_PATH", "/etc/dnsmasq.d/eerovista.hosts")
DNS_DOMAIN = os.getenv("DNS_DOMAIN", "eero.local")


def sanitize_hostname(name: str) -> str:
    """
    Sanitize a device name to be DNS-compatible.

    - Remove symbols (except hyphens)
    - Replace spaces with underscores
    - Convert to lowercase
    - Ensure starts with alphanumeric
    """
    if not name:
        return ""

    # Convert to lowercase
    name = name.lower()

    # Replace spaces with underscores
    name = name.replace(" ", "_")

    # Remove or replace special characters (keep alphanumeric, hyphens, underscores)
    name = re.sub(r"[^a-z0-9_-]", "", name)

    # Ensure starts with alphanumeric (prepend 'device' if not)
    if name and not name[0].isalnum():
        name = "device_" + name

    return name


def generate_hosts_file() -> Tuple[int, int]:
    """
    Generate dnsmasq hosts file from device database.

    Includes:
    - All online devices (priority)
    - Offline devices seen within last 24 hours (if no IP/hostname conflict)

    Returns:
        Tuple of (total_entries, devices_with_ip)
    """
    from datetime import datetime, timedelta

    try:
        with get_db_context() as db:
            hosts_entries = []
            used_ips = set()
            used_hostnames = set()

            # Get all eero nodes
            nodes = db.query(EeroNode).all()

            for node in nodes:
                # Get node name and sanitize
                node_name = sanitize_hostname(node.location or f"eero_{node.id}")

                # Eero nodes don't have IPs in our data, so we skip them
                # unless we can get their management IP somehow

            # Get all devices with their latest connection
            devices = db.query(Device).all()
            devices_with_ip = 0
            offline_cutoff = datetime.utcnow() - timedelta(hours=24)

            # Separate online and offline devices
            online_devices = []
            offline_devices = []

            for device in devices:
                # Get most recent connection
                latest_connection = (
                    db.query(DeviceConnection)
                    .filter(DeviceConnection.device_id == device.id)
                    .order_by(DeviceConnection.timestamp.desc())
                    .first()
                )

                if not latest_connection or not latest_connection.ip_address:
                    continue

                # Skip IPv6 addresses
                if ":" in latest_connection.ip_address:
                    continue

                if latest_connection.is_connected:
                    online_devices.append((device, latest_connection))
                elif latest_connection.timestamp >= offline_cutoff:
                    offline_devices.append((device, latest_connection))

            def add_device_entry(device, connection):
                """Add a device entry if no conflict exists."""
                nonlocal devices_with_ip

                ip_address = connection.ip_address
                device_name = device.nickname or device.hostname or device.mac_address
                hostname = sanitize_hostname(device_name)

                if not hostname:
                    hostname = f"device_{device.id}"

                # Check for conflicts
                if ip_address in used_ips or hostname in used_hostnames:
                    return False

                # Add entry
                hosts_entries.append(f"{ip_address}\t{hostname}.{DNS_DOMAIN}\t{hostname}")
                used_ips.add(ip_address)
                used_hostnames.add(hostname)
                devices_with_ip += 1

                # Add aliases if they exist
                if device.aliases:
                    try:
                        aliases = json.loads(device.aliases)
                        for alias in aliases:
                            alias_hostname = sanitize_hostname(alias)
                            if alias_hostname and alias_hostname not in used_hostnames:
                                hosts_entries.append(f"{ip_address}\t{alias_hostname}.{DNS_DOMAIN}\t{alias_hostname}")
                                used_hostnames.add(alias_hostname)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON in aliases for device {device.id}")

                return True

            # Process online devices first (they get priority)
            for device, connection in online_devices:
                add_device_entry(device, connection)

            # Process offline devices (only if no conflict)
            offline_added = 0
            for device, connection in offline_devices:
                if add_device_entry(device, connection):
                    offline_added += 1

            # Write to hosts file
            hosts_content = "\n".join(hosts_entries) + "\n"

            with open(HOSTS_FILE_PATH, "w") as f:
                f.write("# Generated by eeroVista\n")
                f.write("# Do not edit manually - changes will be overwritten\n")
                f.write(f"# Total entries: {len(hosts_entries)}\n")
                f.write(f"# Online devices: {len(online_devices)}, Offline (recent): {offline_added}\n\n")
                f.write(hosts_content)

            logger.info(
                f"DNS hosts file updated: {len(hosts_entries)} entries, "
                f"{len(online_devices)} online, {offline_added} offline (recent)"
            )

            # Signal dnsmasq to reload
            reload_dnsmasq()

            return len(hosts_entries), devices_with_ip

    except Exception as e:
        logger.error(f"Failed to generate DNS hosts file: {e}", exc_info=True)
        return 0, 0


def reload_dnsmasq() -> bool:
    """
    Signal dnsmasq to reload its configuration.

    Returns:
        True if successful, False otherwise
    """
    try:
        # Find dnsmasq process and send SIGHUP to reload
        import subprocess

        result = subprocess.run(
            ["pkill", "-HUP", "dnsmasq"],
            capture_output=True,
            timeout=5
        )

        if result.returncode == 0:
            logger.info("dnsmasq reloaded successfully")
            return True
        else:
            logger.warning(f"dnsmasq reload returned code {result.returncode}")
            return False

    except Exception as e:
        logger.error(f"Failed to reload dnsmasq: {e}")
        return False


def update_dns_on_device_change() -> None:
    """
    Update DNS hosts file when device data changes.
    This should be called after device collection completes.
    """
    try:
        total, with_ip = generate_hosts_file()
        logger.info(f"DNS update complete: {total} entries, {with_ip} devices with IPs")
    except Exception as e:
        logger.error(f"DNS update failed: {e}", exc_info=True)


def update_dns_hosts(db: Session) -> None:
    """
    Update DNS hosts file directly using an existing database session.
    This is useful for immediate updates after alias changes.
    """
    try:
        total, with_ip = generate_hosts_file()
        logger.info(f"DNS hosts updated: {total} entries, {with_ip} devices with IPs")
    except Exception as e:
        logger.error(f"Failed to update DNS hosts: {e}", exc_info=True)
