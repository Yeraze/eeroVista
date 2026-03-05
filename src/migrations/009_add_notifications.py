"""Migration 009: Add notification_rules and notification_history tables.

This migration creates tables for managing notification rules and tracking
sent notifications for dedup/cooldown purposes.
"""

import logging

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session, eero_client) -> None:
    """Create notification_rules and notification_history tables."""
    engine = session.get_bind()
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if "notification_rules" not in existing_tables:
        session.execute(text("""
            CREATE TABLE notification_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                network_name TEXT NOT NULL,
                rule_type TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                config_json TEXT NOT NULL DEFAULT '{}',
                cooldown_minutes INTEGER NOT NULL DEFAULT 60,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        session.execute(text(
            "CREATE INDEX ix_notification_rules_network ON notification_rules (network_name)"
        ))
        logger.info("Created notification_rules table")
    else:
        logger.info("notification_rules table already exists")

    if "notification_history" not in existing_tables:
        session.execute(text("""
            CREATE TABLE notification_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER NOT NULL REFERENCES notification_rules(id) ON DELETE CASCADE,
                event_key TEXT NOT NULL,
                message TEXT NOT NULL,
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                resolved_at DATETIME
            )
        """))
        session.execute(text(
            "CREATE INDEX ix_notification_history_rule_event ON notification_history (rule_id, event_key)"
        ))
        session.execute(text(
            "CREATE INDEX ix_notification_history_sent_at ON notification_history (sent_at)"
        ))
        logger.info("Created notification_history table")
    else:
        logger.info("notification_history table already exists")

    session.commit()
    logger.info("Migration 009 completed")
