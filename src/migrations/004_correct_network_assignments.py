"""Migration 004: Correct network assignments for existing data.

Fixes network_name assignments by matching MAC addresses and Eero IDs
between the database and current Eero API data, instead of assuming all
legacy data belongs to the first network.
"""

import logging
from typing import Dict, Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def build_device_network_map(eero_client) -> Dict[str, str]:
    """Build a map of MAC address -> network name from Eero API.

    Returns:
        Dict mapping MAC addresses to network names
    """
    mac_to_network = {}

    try:
        if not eero_client or not eero_client.is_authenticated():
            logger.warning("Eero client not authenticated, cannot build network map")
            return mac_to_network

        networks = eero_client.get_networks()
        if not networks:
            logger.warning("No networks found")
            return mac_to_network

        logger.info(f"Building device-to-network map from {len(networks)} network(s)")

        for network in networks:
            # Get network name
            if isinstance(network, dict):
                network_name = network.get('name')
            else:
                network_name = network.name

            if not network_name:
                logger.warning("Network has no name, skipping")
                continue

            # Get network client and devices
            try:
                network_client = eero_client.get_network_client(network_name)
                if not network_client:
                    logger.warning(f"Could not get client for network '{network_name}'")
                    continue

                devices = network_client.devices
                if not devices:
                    logger.info(f"No devices found for network '{network_name}'")
                    continue

                device_count = 0
                for device in devices:
                    mac = device.mac
                    if mac:
                        mac_to_network[mac.lower()] = network_name
                        device_count += 1

                logger.info(f"  Mapped {device_count} devices to network '{network_name}'")

            except Exception as e:
                logger.error(f"Error getting devices for network '{network_name}': {e}")
                continue

        logger.info(f"Built map with {len(mac_to_network)} total devices")
        return mac_to_network

    except Exception as e:
        logger.error(f"Error building device network map: {e}")
        return mac_to_network


def build_node_network_map(eero_client) -> Dict[str, str]:
    """Build a map of eero_id -> network name from Eero API.

    Returns:
        Dict mapping eero IDs to network names
    """
    eero_id_to_network = {}

    try:
        if not eero_client or not eero_client.is_authenticated():
            return eero_id_to_network

        networks = eero_client.get_networks()
        if not networks:
            return eero_id_to_network

        logger.info(f"Building node-to-network map from {len(networks)} network(s)")

        for network in networks:
            if isinstance(network, dict):
                network_name = network.get('name')
            else:
                network_name = network.name

            if not network_name:
                continue

            try:
                network_client = eero_client.get_network_client(network_name)
                if not network_client:
                    continue

                eeros = network_client.eeros
                if not eeros:
                    continue

                node_count = 0
                for eero in eeros:
                    eero_id = str(eero.id) if hasattr(eero, 'id') else None
                    if eero_id:
                        eero_id_to_network[eero_id] = network_name
                        node_count += 1

                logger.info(f"  Mapped {node_count} nodes to network '{network_name}'")

            except Exception as e:
                logger.error(f"Error getting nodes for network '{network_name}': {e}")
                continue

        logger.info(f"Built map with {len(eero_id_to_network)} total nodes")
        return eero_id_to_network

    except Exception as e:
        logger.error(f"Error building node network map: {e}")
        return eero_id_to_network


def run(session: Session, eero_client) -> None:
    """Correct network assignments based on current API data."""

    logger.info("Running migration 004: Correcting network assignments")

    try:
        # Build mapping from MAC addresses and Eero IDs to network names
        mac_to_network = build_device_network_map(eero_client)
        eero_id_to_network = build_node_network_map(eero_client)

        if not mac_to_network and not eero_id_to_network:
            logger.warning("Could not build device/node maps - skipping migration")
            logger.warning("This migration requires an authenticated Eero connection")
            return

        # Correct eero_nodes assignments
        if eero_id_to_network:
            logger.info("  Correcting eero_nodes network assignments...")

            # Get all eero_nodes that might need correction
            result = session.execute(text("""
                SELECT id, eero_id, network_name, location
                FROM eero_nodes
            """))

            nodes_updated = 0
            for row in result:
                node_id, eero_id, current_network, location = row
                correct_network = eero_id_to_network.get(eero_id)

                if correct_network and correct_network != current_network:
                    logger.info(f"    Updating node {location} ({eero_id}): '{current_network}' -> '{correct_network}'")
                    session.execute(
                        text("UPDATE eero_nodes SET network_name = :network WHERE id = :id"),
                        {"network": correct_network, "id": node_id}
                    )
                    nodes_updated += 1

            logger.info(f"    ✓ Updated {nodes_updated} eero_nodes")

        # Correct devices assignments
        if mac_to_network:
            logger.info("  Correcting devices network assignments...")

            # Get all devices that might need correction
            result = session.execute(text("""
                SELECT id, mac_address, network_name, hostname
                FROM devices
            """))

            devices_updated = 0
            for row in result:
                device_id, mac, current_network, hostname = row
                correct_network = mac_to_network.get(mac.lower())

                if correct_network and correct_network != current_network:
                    logger.info(f"    Updating device {hostname} ({mac}): '{current_network}' -> '{correct_network}'")
                    session.execute(
                        text("UPDATE devices SET network_name = :network WHERE id = :id"),
                        {"network": correct_network, "id": device_id}
                    )
                    devices_updated += 1

            logger.info(f"    ✓ Updated {devices_updated} devices")

        # Correct related tables by following device relationships
        if mac_to_network:
            logger.info("  Correcting device_connections network assignments...")
            connections_updated = session.execute(text("""
                UPDATE device_connections
                SET network_name = (SELECT network_name FROM devices WHERE devices.id = device_connections.device_id)
                WHERE network_name != (SELECT network_name FROM devices WHERE devices.id = device_connections.device_id)
            """)).rowcount
            logger.info(f"    ✓ Updated {connections_updated} device_connections")

            logger.info("  Correcting daily_bandwidth network assignments...")
            bandwidth_updated = session.execute(text("""
                UPDATE daily_bandwidth
                SET network_name = (SELECT network_name FROM devices WHERE devices.id = daily_bandwidth.device_id)
                WHERE device_id IS NOT NULL
                  AND network_name != (SELECT network_name FROM devices WHERE devices.id = daily_bandwidth.device_id)
            """)).rowcount
            logger.info(f"    ✓ Updated {bandwidth_updated} daily_bandwidth records")

            logger.info("  Correcting ip_reservations network assignments...")
            reservations_updated = session.execute(text("""
                UPDATE ip_reservations
                SET network_name = (
                    SELECT network_name FROM devices
                    WHERE LOWER(devices.mac_address) = LOWER(ip_reservations.mac_address)
                    LIMIT 1
                )
                WHERE EXISTS (
                    SELECT 1 FROM devices
                    WHERE LOWER(devices.mac_address) = LOWER(ip_reservations.mac_address)
                      AND devices.network_name != ip_reservations.network_name
                )
            """)).rowcount
            logger.info(f"    ✓ Updated {reservations_updated} ip_reservations")

        # Correct network-level tables (network_metrics, speedtests, port_forwards)
        # These need manual review or API lookup since they don't have device relationships
        logger.info("  Note: network_metrics, speedtests, and port_forwards may need manual correction")

        session.commit()
        logger.info("Migration 004 completed successfully")

    except Exception as e:
        logger.error(f"Migration 004 failed: {e}", exc_info=True)
        session.rollback()
        raise


def rollback(session: Session) -> None:
    """Rollback migration 004."""
    logger.info("Rolling back migration 004")
    logger.warning("  Note: Rollback would require knowing the original incorrect values")
    logger.warning("  Recommend restoring from backup if rollback is needed")
