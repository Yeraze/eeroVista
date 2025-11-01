"""Database migration runner."""

import logging
from pathlib import Path
from typing import List, Set

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.models.database import Config

logger = logging.getLogger(__name__)

# Track migrations that were skipped due to missing authentication
_skipped_auth_migrations: Set[str] = set()


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


def run_migrations(session: Session, eero_client, retry_skipped: bool = False) -> None:
    """Run all pending migrations.

    Args:
        session: Database session
        eero_client: Eero client wrapper (may be None if not authenticated)
        retry_skipped: If True, retry migrations that were previously skipped
    """
    logger.info("Checking for pending database migrations...")

    applied = get_applied_migrations(session)
    logger.info(f"Applied migrations: {applied if applied else 'none'}")

    # Import migrations
    migrations = [
        ('001_add_network_name', 'src.migrations.001_add_network_name', False),
        ('002_update_unique_constraints', 'src.migrations.002_update_unique_constraints', False),
        ('003_fix_routing_constraints', 'src.migrations.003_fix_routing_constraints', False),
        ('004_correct_network_assignments', 'src.migrations.004_correct_network_assignments', True),  # Requires auth
        ('005_add_performance_indexes', 'src.migrations.005_add_performance_indexes', False),
        ('006_add_node_connection_type', 'src.migrations.006_add_node_connection_type', False),
        ('007_add_connection_mode', 'src.migrations.007_add_connection_mode', False),
    ]

    for migration_name, module_path, requires_auth in migrations:
        # Skip already applied migrations unless we're retrying
        if migration_name in applied:
            if not (retry_skipped and migration_name in _skipped_auth_migrations):
                logger.info(f"  ✓ {migration_name} (already applied)")
                continue
            else:
                logger.info(f"  Retrying previously skipped migration: {migration_name}")
                _skipped_auth_migrations.discard(migration_name)

        # Skip auth-required migrations if not authenticated (unless retrying)
        if requires_auth and not retry_skipped:
            if not eero_client or not eero_client.is_authenticated():
                logger.warning(f"  ⏸ {migration_name} (skipped - requires authentication)")
                _skipped_auth_migrations.add(migration_name)
                continue

        logger.info(f"  Running {migration_name}...")
        try:
            # Dynamically import and run migration
            import importlib
            migration_module = importlib.import_module(module_path)

            migration_module.run(session, eero_client)
            mark_migration_applied(session, migration_name)

            logger.info(f"  ✓ {migration_name} completed")
            _skipped_auth_migrations.discard(migration_name)
        except Exception as e:
            logger.error(f"  ✗ {migration_name} failed: {e}")
            raise

    if not retry_skipped and _skipped_auth_migrations:
        logger.info(f"Migrations skipped (will retry after authentication): {', '.join(_skipped_auth_migrations)}")
    else:
        logger.info("All migrations completed")


def has_pending_auth_migrations() -> bool:
    """Check if there are migrations waiting for authentication."""
    return len(_skipped_auth_migrations) > 0


def retry_auth_migrations(eero_client) -> None:
    """Retry migrations that were skipped due to missing authentication.

    This should be called after successful Eero authentication.

    Args:
        eero_client: Authenticated Eero client wrapper
    """
    if not _skipped_auth_migrations:
        return

    logger.info("Retrying auth-dependent migrations after successful authentication")

    from src.utils.database import get_db_context

    try:
        with get_db_context() as session:
            run_migrations(session, eero_client, retry_skipped=True)
    except Exception as e:
        logger.error(f"Failed to retry auth-dependent migrations: {e}", exc_info=True)
