"""Migration 008: Add device_groups and device_group_members tables.

This migration creates tables for organizing devices into groups:
- device_groups: Named groups scoped to a network
- device_group_members: Maps devices to groups (each device in at most one group)
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session, eero_client) -> None:
    """Create device_groups and device_group_members tables."""
    engine = session.get_bind()
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if "device_groups" not in existing_tables:
        session.execute(text("""
            CREATE TABLE device_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                network_name TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        session.execute(text(
            "CREATE INDEX ix_device_groups_network_name ON device_groups (network_name)"
        ))
        logger.info("Created device_groups table")
    else:
        logger.info("device_groups table already exists")

    if "device_group_members" not in existing_tables:
        session.execute(text("""
            CREATE TABLE device_group_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL REFERENCES device_groups(id) ON DELETE CASCADE,
                device_id INTEGER NOT NULL REFERENCES devices(id),
                UNIQUE (device_id)
            )
        """))
        logger.info("Created device_group_members table")
    else:
        logger.info("device_group_members table already exists")

    session.commit()
    logger.info("Migration 008 completed")
