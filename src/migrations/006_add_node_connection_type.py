"""Migration 006: Add node connection type fields.

This migration adds fields to track how eero nodes are connected to their upstream nodes:
- connection_type: 'WIRED' or 'WIRELESS' backhaul connection
- is_wired: Boolean indicating wired backhaul
- upstream_node_name: Name of the upstream node (for wireless connections)
- upstream_node_id: Database ID of the upstream node (for establishing relationships)

These fields enable proper visualization of mesh topology showing wired vs wireless
node-to-node connections.
"""

import logging

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, MetaData, Table, inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def column_exists(engine, table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def run(session: Session, eero_client) -> None:
    """Run the migration to add node connection type fields."""
    engine = session.get_bind()

    logger.info("Running migration 006: Adding node connection type fields")

    # Check if eero_nodes table exists
    inspector = inspect(engine)
    if 'eero_nodes' not in inspector.get_table_names():
        logger.error("  ✗ Table eero_nodes does not exist")
        return

    # Define columns to add
    # Format: (column_name, column_type, nullable, default)
    columns_to_add = [
        ('connection_type', 'VARCHAR', True, None),  # 'WIRED', 'WIRELESS', or NULL (for gateway)
        ('upstream_node_name', 'VARCHAR', True, None),  # Name of upstream node (for display)
        ('upstream_node_id', 'INTEGER', True, None),  # Foreign key to eero_nodes.id
    ]

    for column_name, column_type, nullable, default in columns_to_add:
        try:
            # Check if column already exists
            if column_exists(engine, 'eero_nodes', column_name):
                logger.info(f"  ✓ Column {column_name} already exists")
                continue

            # Add column using raw SQL (SQLite compatible)
            nullable_str = "NULL" if nullable else "NOT NULL"
            default_str = f"DEFAULT {default}" if default is not None else ""

            sql = f"ALTER TABLE eero_nodes ADD COLUMN {column_name} {column_type} {nullable_str} {default_str}"
            session.execute(text(sql))
            session.commit()

            logger.info(f"  ✓ Added column {column_name} ({column_type})")

        except Exception as e:
            session.rollback()
            logger.error(f"  ✗ Failed to add column {column_name}: {e}")
            raise

    # Note: Foreign key constraint is not added for SQLite compatibility
    # The upstream_node_id column will reference eero_nodes.id by convention
    logger.info("  ℹ Note: upstream_node_id references eero_nodes.id (enforced in code)")

    logger.info("Migration 006 completed")
