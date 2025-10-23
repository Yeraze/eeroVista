"""Migration 003: Fix unique constraints for routing tables (IP reservations and port forwards).

Updates unique constraints from single-column to composite (network_name + column):
- ip_reservations: mac_address -> (network_name, mac_address)
- port_forwards: already has correct composite constraint
"""

import logging
from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session, eero_client) -> None:
    """Fix unique constraints for routing tables."""
    engine = session.get_bind()

    logger.info("Running migration 003: Fixing routing table unique constraints")

    try:
        # Clean up any leftover temp tables from previous failed attempts
        session.execute(text("DROP TABLE IF EXISTS ip_reservations_new"))

        # Recreate ip_reservations table without UNIQUE(mac_address)
        logger.info("  Recreating ip_reservations table...")

        # Drop existing indexes on ip_reservations
        session.execute(text("DROP INDEX IF EXISTS idx_ip_reservations_network_name"))
        session.execute(text("DROP INDEX IF EXISTS ix_ip_reservations_mac_address"))
        session.execute(text("DROP INDEX IF EXISTS uix_network_mac"))

        # Create new table with correct schema
        session.execute(text("""
            CREATE TABLE ip_reservations_new (
                id INTEGER NOT NULL,
                network_name VARCHAR NOT NULL,
                mac_address VARCHAR NOT NULL,
                ip_address VARCHAR NOT NULL,
                description VARCHAR,
                eero_url VARCHAR,
                created_at DATETIME NOT NULL,
                last_seen DATETIME NOT NULL,
                PRIMARY KEY (id)
            )
        """))

        # Copy data
        session.execute(text("""
            INSERT INTO ip_reservations_new
            SELECT id, network_name, mac_address, ip_address, description,
                   eero_url, created_at, last_seen
            FROM ip_reservations
        """))

        # Drop old table and rename
        session.execute(text("DROP TABLE ip_reservations"))
        session.execute(text("ALTER TABLE ip_reservations_new RENAME TO ip_reservations"))

        # Create indexes
        session.execute(text("""
            CREATE INDEX idx_ip_reservations_network_name ON ip_reservations(network_name)
        """))
        session.execute(text("""
            CREATE INDEX idx_ip_reservations_mac_address ON ip_reservations(mac_address)
        """))
        session.execute(text("""
            CREATE UNIQUE INDEX uix_network_mac ON ip_reservations(network_name, mac_address)
        """))

        logger.info("    ✓ Recreated ip_reservations with composite unique constraint")

        # Note: port_forwards already has the correct composite unique constraint
        # (uq_network_port_forward_rule on network_name, ip_address, gateway_port, protocol)
        logger.info("  ✓ port_forwards already has correct composite unique constraint")

        session.commit()
        logger.info("Migration 003 completed successfully")

    except Exception as e:
        logger.error(f"Migration 003 failed: {e}")
        session.rollback()
        raise


def rollback(session: Session) -> None:
    """Rollback migration 003."""
    logger.info("Rolling back migration 003")
    logger.warning("  Note: Rollback not fully implemented for SQLite constraint changes")
