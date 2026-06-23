"""Migration 010: Add hourly_bandwidth table and DailyBandwidth.source column.

Supports the data_usage endpoint integration for server-computed bandwidth totals.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session, eero_client) -> None:
    """Create hourly_bandwidth table and add source column to daily_bandwidth."""
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

    # Add source column to daily_bandwidth if missing
    if "daily_bandwidth" in existing_tables:
        columns = [col["name"] for col in inspector.get_columns("daily_bandwidth")]
        if "source" not in columns:
            session.execute(text(
                "ALTER TABLE daily_bandwidth ADD COLUMN source TEXT DEFAULT 'rate'"
            ))
            logger.info("Added source column to daily_bandwidth")
        else:
            logger.info("daily_bandwidth.source column already exists")

    session.commit()
    logger.info("Migration 010 completed")
