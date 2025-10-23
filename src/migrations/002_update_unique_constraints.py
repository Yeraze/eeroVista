"""Migration 002: Update unique constraints for multi-network support.

Updates unique constraints from single-column to composite (network_name + column):
- eero_nodes: eero_id -> (network_name, eero_id)
- devices: mac_address -> (network_name, mac_address)
"""

import logging
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session, eero_client) -> None:
    """Update unique constraints for multi-network support."""
    engine = session.get_bind()

    logger.info("Running migration 002: Updating unique constraints for multi-network")

    # SQLite doesn't support dropping constraints directly
    # We need to recreate tables without the old UNIQUE constraints

    try:
        # Clean up any leftover temp tables from previous failed attempts
        session.execute(text("DROP TABLE IF EXISTS eero_nodes_new"))
        session.execute(text("DROP TABLE IF EXISTS devices_new"))

        # Recreate eero_nodes table without UNIQUE(eero_id)
        logger.info("  Recreating eero_nodes table...")

        # Drop existing indexes on eero_nodes
        session.execute(text("DROP INDEX IF EXISTS idx_eero_nodes_network_name"))
        session.execute(text("DROP INDEX IF EXISTS idx_eero_nodes_eero_id"))
        session.execute(text("DROP INDEX IF EXISTS uix_network_eero"))

        # Create new table with correct schema
        session.execute(text("""
            CREATE TABLE eero_nodes_new (
                id INTEGER NOT NULL,
                network_name VARCHAR NOT NULL,
                eero_id VARCHAR NOT NULL,
                location VARCHAR,
                model VARCHAR,
                mac_address VARCHAR,
                is_gateway BOOLEAN,
                os_version VARCHAR,
                update_available BOOLEAN,
                created_at DATETIME NOT NULL,
                last_seen DATETIME,
                PRIMARY KEY (id)
            )
        """))

        # Copy data
        session.execute(text("""
            INSERT INTO eero_nodes_new
            SELECT id, network_name, eero_id, location, model, mac_address,
                   is_gateway, os_version, update_available, created_at, last_seen
            FROM eero_nodes
        """))

        # Drop old table and rename
        session.execute(text("DROP TABLE eero_nodes"))
        session.execute(text("ALTER TABLE eero_nodes_new RENAME TO eero_nodes"))

        # Create indexes
        session.execute(text("""
            CREATE INDEX idx_eero_nodes_network_name ON eero_nodes(network_name)
        """))
        session.execute(text("""
            CREATE INDEX idx_eero_nodes_eero_id ON eero_nodes(eero_id)
        """))
        session.execute(text("""
            CREATE UNIQUE INDEX uix_network_eero ON eero_nodes(network_name, eero_id)
        """))

        logger.info("    ✓ Recreated eero_nodes with composite unique constraint")

        # Recreate devices table without UNIQUE(mac_address)
        logger.info("  Recreating devices table...")

        # Drop existing indexes on devices
        session.execute(text("DROP INDEX IF EXISTS idx_devices_network_name"))
        session.execute(text("DROP INDEX IF EXISTS idx_devices_mac_address"))
        session.execute(text("DROP INDEX IF EXISTS uix_network_mac"))

        # Create new table with correct schema
        session.execute(text("""
            CREATE TABLE devices_new (
                id INTEGER NOT NULL,
                network_name VARCHAR NOT NULL,
                mac_address VARCHAR NOT NULL,
                hostname VARCHAR,
                nickname VARCHAR,
                manufacturer VARCHAR,
                device_type VARCHAR,
                aliases TEXT,
                first_seen DATETIME NOT NULL,
                last_seen DATETIME,
                PRIMARY KEY (id)
            )
        """))

        # Copy data
        session.execute(text("""
            INSERT INTO devices_new
            SELECT id, network_name, mac_address, hostname, nickname, manufacturer,
                   device_type, aliases, first_seen, last_seen
            FROM devices
        """))

        # Drop old table and rename
        session.execute(text("DROP TABLE devices"))
        session.execute(text("ALTER TABLE devices_new RENAME TO devices"))

        # Create indexes
        session.execute(text("""
            CREATE INDEX idx_devices_network_name ON devices(network_name)
        """))
        session.execute(text("""
            CREATE INDEX idx_devices_mac_address ON devices(mac_address)
        """))
        session.execute(text("""
            CREATE UNIQUE INDEX uix_network_mac ON devices(network_name, mac_address)
        """))

        logger.info("    ✓ Recreated devices with composite unique constraint")

        session.commit()
        logger.info("Migration 002 completed successfully")

    except Exception as e:
        logger.error(f"Migration 002 failed: {e}")
        session.rollback()
        raise


def rollback(session: Session) -> None:
    """Rollback migration 002."""
    logger.info("Rolling back migration 002")
    logger.warning("  Note: Rollback not fully implemented for SQLite constraint changes")
