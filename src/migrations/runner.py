"""Database migration runner."""

import logging
from pathlib import Path
from typing import List

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.models.database import Config

logger = logging.getLogger(__name__)


def get_applied_migrations(session: Session) -> List[str]:
    """Get list of migrations that have been applied."""
    try:
        result = session.execute(
            text("SELECT value FROM config WHERE key = 'schema_version'")
        ).fetchone()

        if result and result[0]:
            return result[0].split(',')
        return []
    except Exception:
        # Table might not exist yet
        return []


def mark_migration_applied(session: Session, migration_name: str) -> None:
    """Mark a migration as applied."""
    applied = get_applied_migrations(session)
    if migration_name not in applied:
        applied.append(migration_name)

    # Upsert the schema version
    session.execute(
        text("""
            INSERT INTO config (key, value, updated_at)
            VALUES ('schema_version', :value, CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET
                value = :value,
                updated_at = CURRENT_TIMESTAMP
        """),
        {"value": ','.join(applied)}
    )
    session.commit()


def run_migrations(session: Session, eero_client) -> None:
    """Run all pending migrations."""
    logger.info("Checking for pending database migrations...")

    applied = get_applied_migrations(session)
    logger.info(f"Applied migrations: {applied if applied else 'none'}")

    # Import migrations
    migrations = [
        ('001_add_network_name', 'src.migrations.001_add_network_name'),
        ('002_update_unique_constraints', 'src.migrations.002_update_unique_constraints'),
    ]

    for migration_name, module_path in migrations:
        if migration_name in applied:
            logger.info(f"  ✓ {migration_name} (already applied)")
            continue

        logger.info(f"  Running {migration_name}...")
        try:
            # Dynamically import and run migration
            import importlib
            migration_module = importlib.import_module(module_path)

            migration_module.run(session, eero_client)
            mark_migration_applied(session, migration_name)

            logger.info(f"  ✓ {migration_name} completed")
        except Exception as e:
            logger.error(f"  ✗ {migration_name} failed: {e}")
            raise

    logger.info("All migrations completed")
