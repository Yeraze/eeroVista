"""Migration 007: Add connection_mode field to NetworkMetric.

This migration adds a field to track the network connection mode:
- connection_mode: The mode the Eero network is operating in (e.g., 'automatic', 'bridge')

This enables detection of bridge mode where the Eero acts as an access point only
and DHCP/routing is handled by an upstream router.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def column_exists(engine, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def run(session: Session, eero_client) -> None:
    """Run the migration to add connection_mode field."""
    engine = session.get_bind()

    logger.info("Running migration 007: Adding connection_mode field")

    # Check if network_metrics table exists
    inspector = inspect(engine)
    if 'network_metrics' not in inspector.get_table_names():
        logger.error("  ✗ Table network_metrics does not exist")
        return

    # Define column to add
    column_name = 'connection_mode'
    column_type = 'VARCHAR'
    nullable = True
    default = None

    try:
        # Check if column already exists
        if column_exists(engine, 'network_metrics', column_name):
            logger.info(f"  ✓ Column {column_name} already exists")
            return

        # Add column using raw SQL (SQLite compatible)
        nullable_str = "NULL" if nullable else "NOT NULL"
        default_str = f"DEFAULT {default}" if default is not None else ""

        sql = f"ALTER TABLE network_metrics ADD COLUMN {column_name} {column_type} {nullable_str} {default_str}"
        session.execute(text(sql))
        session.commit()

        logger.info(f"  ✓ Added column {column_name} ({column_type})")

    except Exception as e:
        session.rollback()
        logger.error(f"  ✗ Failed to add column {column_name}: {e}")
        raise

    logger.info("Migration 007 completed")
