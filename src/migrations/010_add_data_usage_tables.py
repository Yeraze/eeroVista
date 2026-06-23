"""Migration 010: Add hourly_bandwidth table.

Supports the data_usage endpoint integration for server-computed bandwidth totals.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session, eero_client) -> None:
    """Create hourly_bandwidth table."""
    engine = session.get_bind()
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    # Create hourly_bandwidth table
    if "hourly_bandwidth" not in existing_tables:
        session.execute(text("""
            CREATE TABLE hourly_bandwidth (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                network_name TEXT NOT NULL,
                device_id INTEGER REFERENCES devices(id),
                hour_start DATETIME NOT NULL,
                download_bytes REAL NOT NULL DEFAULT 0.0,
                upload_bytes REAL NOT NULL DEFAULT 0.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        session.execute(text(
            "CREATE INDEX ix_hourly_bandwidth_network ON hourly_bandwidth (network_name)"
        ))
        session.execute(text(
            "CREATE INDEX ix_hourly_bandwidth_hour ON hourly_bandwidth (hour_start)"
        ))
        session.execute(text(
            "CREATE UNIQUE INDEX uix_network_device_hour ON hourly_bandwidth (network_name, device_id, hour_start)"
        ))
        logger.info("Created hourly_bandwidth table")
    else:
        logger.info("hourly_bandwidth table already exists")

    session.commit()
    logger.info("Migration 010 completed")
