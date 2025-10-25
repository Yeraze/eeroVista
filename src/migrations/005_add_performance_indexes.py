"""Migration 005: Add database indexes for query performance optimization.

This migration adds indexes to frequently-queried columns:
- device_connections(device_id) - for JOINs on device lookups
- device_connections(timestamp) - for finding latest connections
- device_connections(eero_node_id) - for JOINs on node lookups
- device_connections(device_id, timestamp) - composite index for latest connection queries
- devices(network_name) - for network filtering
- devices(mac_address) - for device lookups
- eero_nodes(network_name) - for network filtering

These indexes significantly improve performance of API endpoints that join across
devices, connections, and nodes.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def index_exists(engine, table_name: str, index_name: str) -> bool:
    """Check if an index exists on a table."""
    inspector = inspect(engine)
    indexes = inspector.get_indexes(table_name)
    return any(idx['name'] == index_name for idx in indexes)


def run(session: Session, eero_client) -> None:
    """Run the migration to add performance indexes."""
    engine = session.get_bind()

    logger.info("Running migration 005: Adding performance indexes")

    # Define indexes to create
    # Format: (table_name, index_name, columns, unique)
    indexes_to_create = [
        # DeviceConnection indexes
        ('device_connections', 'idx_device_connections_device_id', ['device_id'], False),
        ('device_connections', 'idx_device_connections_timestamp', ['timestamp'], False),
        ('device_connections', 'idx_device_connections_eero_node_id', ['eero_node_id'], False),
        ('device_connections', 'idx_device_connections_device_timestamp', ['device_id', 'timestamp'], False),

        # Device indexes
        ('devices', 'idx_devices_network_name', ['network_name'], False),
        ('devices', 'idx_devices_mac_address', ['mac_address'], False),

        # EeroNode indexes
        ('eero_nodes', 'idx_eero_nodes_network_name', ['network_name'], False),
    ]

    for table_name, index_name, columns, unique in indexes_to_create:
        try:
            # Check if table exists
            inspector = inspect(engine)
            if table_name not in inspector.get_table_names():
                logger.warning(f"  ⚠ Table {table_name} does not exist, skipping index {index_name}")
                continue

            # Check if index already exists
            if index_exists(engine, table_name, index_name):
                logger.info(f"  ✓ Index {index_name} already exists on {table_name}")
                continue

            # Create index
            columns_str = ', '.join(columns)
            unique_str = 'UNIQUE ' if unique else ''
            sql = f"CREATE {unique_str}INDEX {index_name} ON {table_name} ({columns_str})"

            session.execute(text(sql))
            session.commit()
            logger.info(f"  ✓ Created index {index_name} on {table_name}({columns_str})")

        except Exception as e:
            session.rollback()
            logger.error(f"  ✗ Failed to create index {index_name}: {e}")
            # Continue with other indexes even if one fails

    logger.info("Migration 005 completed")
