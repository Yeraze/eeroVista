"""Migration 001: Add network_name column to all tables for multi-network support.

This migration adds network_name to:
- eero_nodes
- devices
- device_connections
- network_metrics
- speedtests
- daily_bandwidth
- ip_reservations
- port_forwards

For existing data, we populate with the first network's name from the authenticated account.
"""

import logging
from typing import Optional

from sqlalchemy import MetaData, Table, inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_first_network_name(eero_client) -> Optional[str]:
    """Get the first network name from the authenticated account."""
    if eero_client is None:
        return None

    try:
        if not eero_client.is_authenticated():
            return None

        networks = eero_client.get_networks()
        if not networks:
            return None

        first_network = networks[0]
        if isinstance(first_network, dict):
            return first_network.get('name')
        else:
            return first_network.name
    except Exception as e:
        logger.error(f"Failed to get network name: {e}")
        return None


def column_exists(engine, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def run(session: Session, eero_client) -> None:
    """Run the migration to add network_name columns."""
    engine = session.get_bind()

    # Get default network name for existing data
    default_network = get_first_network_name(eero_client)
    if not default_network:
        logger.warning("No authenticated network found. Using 'default' as network name.")
        default_network = "default"

    logger.info(f"Running migration 001: Adding network_name columns (default='{default_network}')")

    tables_to_migrate = [
        'eero_nodes',
        'devices',
        'device_connections',
        'network_metrics',
        'speedtests',
        'daily_bandwidth',
        'ip_reservations',
        'port_forwards',
    ]

    for table_name in tables_to_migrate:
        if column_exists(engine, table_name, 'network_name'):
            logger.info(f"  ✓ {table_name}.network_name already exists")
            continue

        try:
            # Add column with default value
            logger.info(f"  Adding network_name to {table_name}...")
            session.execute(text(f"""
                ALTER TABLE {table_name}
                ADD COLUMN network_name VARCHAR NOT NULL DEFAULT '{default_network}'
            """))

            # Create index for performance
            session.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_{table_name}_network_name
                ON {table_name}(network_name)
            """))

            session.commit()
            logger.info(f"  ✓ Added network_name to {table_name}")

        except Exception as e:
            logger.error(f"  ✗ Failed to add network_name to {table_name}: {e}")
            session.rollback()
            raise

    # Update unique constraints for tables that need network-specific uniqueness
    logger.info("Updating unique constraints...")

    try:
        # IpReservation: network + mac must be unique
        # Drop old constraint, create new one
        if not column_exists(engine, 'ip_reservations', 'network_name'):
            logger.info("  Skipping ip_reservations constraint update (column doesn't exist)")
        else:
            session.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_network_mac
                ON ip_reservations(network_name, mac_address)
            """))
            logger.info("  ✓ Updated ip_reservations unique constraint")

        # PortForward: network + ip + port + protocol must be unique
        if not column_exists(engine, 'port_forwards', 'network_name'):
            logger.info("  Skipping port_forwards constraint update (column doesn't exist)")
        else:
            session.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_network_port_forward_rule
                ON port_forwards(network_name, ip_address, gateway_port, protocol)
            """))
            logger.info("  ✓ Updated port_forwards unique constraint")

        # DailyBandwidth: network + device + date must be unique
        if not column_exists(engine, 'daily_bandwidth', 'network_name'):
            logger.info("  Skipping daily_bandwidth constraint update (column doesn't exist)")
        else:
            session.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uix_network_device_date
                ON daily_bandwidth(network_name, device_id, date)
            """))
            logger.info("  ✓ Updated daily_bandwidth unique constraint")

        session.commit()

    except Exception as e:
        logger.error(f"  ✗ Failed to update constraints: {e}")
        session.rollback()
        raise

    logger.info("Migration 001 completed successfully")


def rollback(session: Session) -> None:
    """Rollback the migration (drop network_name columns)."""
    engine = session.get_bind()
    logger.info("Rolling back migration 001: Removing network_name columns")

    tables = [
        'eero_nodes',
        'devices',
        'device_connections',
        'network_metrics',
        'speedtests',
        'daily_bandwidth',
        'ip_reservations',
        'port_forwards',
    ]

    for table_name in tables:
        if not column_exists(engine, table_name, 'network_name'):
            continue

        try:
            # SQLite doesn't support DROP COLUMN easily, so we'd need to recreate tables
            # For now, just log a warning
            logger.warning(f"  Cannot easily remove network_name from {table_name} (SQLite limitation)")
            logger.warning(f"  Consider backing up data and recreating database")
        except Exception as e:
            logger.error(f"  Failed to process {table_name}: {e}")

    logger.info("Rollback note: SQLite doesn't support DROP COLUMN. Manual intervention required.")
