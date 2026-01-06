"""DNS service for managing dnsmasq hosts file."""

import json
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta
from typing import Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.database import Device, DeviceConnection
from src.utils.database import get_db_context

logger = logging.getLogger(__name__)

# Path to dnsmasq hosts file
HOSTS_FILE_PATH = os.getenv("DNSMASQ_HOSTS_PATH", "/etc/dnsmasq.d/eerovista.hosts")
DNS_DOMAIN = os.getenv("DNS_DOMAIN", "eero.local")
OFFLINE_INCLUSION_HOURS = int(os.getenv("DNS_OFFLINE_HOURS", "24"))


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
    - Offline devices seen within configured hours (if no IP/hostname conflict)

    Format: One line per IP with all hostnames on that line:
        192.168.1.1  hostname.domain  hostname  alias1.domain  alias1

    Returns:
        Tuple of (total_lines, devices_added)
    """
    temp_path = None
    try:
        with get_db_context() as db:
            hosts_entries = []  # List of (ip, [hostnames]) tuples
            used_ips = set()
            used_hostnames = set()
            devices_added = 0

            offline_cutoff = datetime.utcnow() - timedelta(hours=OFFLINE_INCLUSION_HOURS)

            # Get latest connection for each device in ONE query (fixes N+1 problem)
            latest_connections_subq = (
                db.query(
                    DeviceConnection.device_id,
                    func.max(DeviceConnection.timestamp).label('max_timestamp')
                )
                .group_by(DeviceConnection.device_id)
                .subquery()
            )

            # Join to get full connection records with device info
            results = (
                db.query(Device, DeviceConnection)
                .join(
                    latest_connections_subq,
                    Device.id == latest_connections_subq.c.device_id
                )
                .join(
                    DeviceConnection,
                    (DeviceConnection.device_id == latest_connections_subq.c.device_id) &
                    (DeviceConnection.timestamp == latest_connections_subq.c.max_timestamp)
                )
                .all()
            )

            # Separate online and offline devices
            online_devices = []
            offline_devices = []

            for device, connection in results:
                if not connection.ip_address:
                    continue

                # Skip IPv6 addresses
                if ":" in connection.ip_address:
                    continue

                if connection.is_connected:
                    online_devices.append((device, connection))
                elif connection.timestamp >= offline_cutoff:
                    offline_devices.append((device, connection))

            def add_device_entry(device, connection, is_offline=False):
                """Add a device entry if no conflict exists."""
                nonlocal devices_added

                ip_address = connection.ip_address
                device_name = device.nickname or device.hostname or device.mac_address
                hostname = sanitize_hostname(device_name)

                if not hostname:
                    hostname = f"device_{device.id}"

                status = "offline" if is_offline else "online"

                # Check for IP conflict
                if ip_address in used_ips:
                    logger.debug(f"Skipping {status} device '{device_name}': IP {ip_address} conflict")
                    return False

                # Check for hostname conflict
                if hostname in used_hostnames:
                    logger.debug(f"Skipping {status} device '{device_name}': hostname '{hostname}' conflict")
                    return False

                # Build list of hostnames for this IP (FQDN and short name pairs)
                hostnames = [f"{hostname}.{DNS_DOMAIN}", hostname]
                used_hostnames.add(hostname)

                # Add aliases if they exist
                if device.aliases:
                    try:
                        aliases = json.loads(device.aliases)
                        for alias in aliases:
                            alias_hostname = sanitize_hostname(alias)
                            if alias_hostname:
                                if alias_hostname in used_hostnames:
                                    logger.warning(
                                        f"Alias '{alias}' for device '{device_name}' "
                                        f"conflicts with existing hostname, skipping"
                                    )
                                    continue
                                hostnames.extend([f"{alias_hostname}.{DNS_DOMAIN}", alias_hostname])
                                used_hostnames.add(alias_hostname)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON in aliases for device {device.id}")

                # Add entry: IP followed by all hostnames on one line
                hosts_entries.append(f"{ip_address}\t" + "\t".join(hostnames))
                used_ips.add(ip_address)
                devices_added += 1

                return True

            # Process online devices first (they get priority)
            online_added = 0
            for device, connection in online_devices:
                if add_device_entry(device, connection, is_offline=False):
                    online_added += 1

            # Process offline devices (only if no conflict)
            offline_added = 0
            for device, connection in offline_devices:
                if add_device_entry(device, connection, is_offline=True):
                    offline_added += 1

            # Build file content
            hosts_content = "\n".join(hosts_entries) + "\n" if hosts_entries else ""
            file_content = (
                "# Generated by eeroVista\n"
                "# Do not edit manually - changes will be overwritten\n"
                f"# Total devices: {devices_added}\n"
                f"# Online: {online_added}, Offline (recent): {offline_added}\n\n"
                + hosts_content
            )

            # Atomic write: write to temp file, then rename
            dir_path = os.path.dirname(HOSTS_FILE_PATH)
            with tempfile.NamedTemporaryFile(mode='w', dir=dir_path, delete=False) as f:
                f.write(file_content)
                temp_path = f.name

            os.replace(temp_path, HOSTS_FILE_PATH)
            temp_path = None  # Clear so finally doesn't try to delete

            logger.info(
                f"DNS hosts file updated: {devices_added} devices, "
                f"{online_added} online, {offline_added} offline (recent)"
            )

            # Signal dnsmasq to reload
            reload_dnsmasq()

            return len(hosts_entries), devices_added

    except Exception as e:
        logger.error(f"Failed to generate DNS hosts file: {e}", exc_info=True)
        return 0, 0
    finally:
        # Cleanup temp file if it exists (in case of error before os.replace)
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


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
        total_lines, devices_added = generate_hosts_file()
        logger.info(f"DNS update complete: {total_lines} lines, {devices_added} devices")
    except Exception as e:
        logger.error(f"DNS update failed: {e}", exc_info=True)


def update_dns_hosts(db: Session) -> None:
    """
    Update DNS hosts file directly using an existing database session.
    This is useful for immediate updates after alias changes.
    """
    try:
        total_lines, devices_added = generate_hosts_file()
        logger.info(f"DNS hosts updated: {total_lines} lines, {devices_added} devices")
    except Exception as e:
        logger.error(f"Failed to update DNS hosts: {e}", exc_info=True)
