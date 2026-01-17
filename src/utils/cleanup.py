"""Database cleanup utilities for maintaining optimal performance."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.models.database import DeviceConnection, EeroNodeMetric, NetworkMetric

logger = logging.getLogger(__name__)


def cleanup_old_connection_records(
    session: Session,
    retention_days: int = 30
) -> dict:
    """Remove DeviceConnection records older than the retention period.

    Args:
        session: Database session
        retention_days: Number of days to retain records (default: 30)

    Returns:
        dict with cleanup statistics
    """
    try:
        # Use timezone-aware datetime (Python 3.12+ compatible)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
        # Remove timezone for comparison with naive datetime in database
        cutoff_date_naive = cutoff_date.replace(tzinfo=None)

        # Delete old records and get actual count deleted
        delete_query = session.query(DeviceConnection).filter(
            DeviceConnection.timestamp < cutoff_date_naive
        )
        records_deleted = delete_query.delete(synchronize_session=False)
        session.commit()

        if records_deleted == 0:
            logger.info(f"No connection records older than {retention_days} days found")
        else:
            logger.info(
                f"Cleaned up {records_deleted} connection records older than "
                f"{retention_days} days (before {cutoff_date_naive.date()})"
            )

        return {
            "success": True,
            "records_deleted": records_deleted,
            "retention_days": retention_days,
            "cutoff_date": cutoff_date.isoformat(),
        }

    except Exception as e:
        session.rollback()
        logger.error(f"Failed to cleanup old connection records: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "records_deleted": 0,
            "retention_days": retention_days,
        }


def cleanup_old_node_metrics(
    session: Session,
    retention_days: int = 30
) -> dict:
    """Remove EeroNodeMetric records older than the retention period.

    Args:
        session: Database session
        retention_days: Number of days to retain records (default: 30)

    Returns:
        dict with cleanup statistics
    """
    try:
        # Use timezone-aware datetime (Python 3.12+ compatible)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
        # Remove timezone for comparison with naive datetime in database
        cutoff_date_naive = cutoff_date.replace(tzinfo=None)

        # Delete old records and get actual count deleted
        delete_query = session.query(EeroNodeMetric).filter(
            EeroNodeMetric.timestamp < cutoff_date_naive
        )
        records_deleted = delete_query.delete(synchronize_session=False)
        session.commit()

        if records_deleted == 0:
            logger.info(f"No node metric records older than {retention_days} days found")
        else:
            logger.info(
                f"Cleaned up {records_deleted} node metric records older than "
                f"{retention_days} days (before {cutoff_date_naive.date()})"
            )

        return {
            "success": True,
            "records_deleted": records_deleted,
            "retention_days": retention_days,
            "cutoff_date": cutoff_date.isoformat(),
        }

    except Exception as e:
        session.rollback()
        logger.error(f"Failed to cleanup old node metric records: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "records_deleted": 0,
            "retention_days": retention_days,
        }


def cleanup_old_network_metrics(
    session: Session,
    retention_days: int = 30
) -> dict:
    """Remove NetworkMetric records older than the retention period.

    Args:
        session: Database session
        retention_days: Number of days to retain records (default: 30)

    Returns:
        dict with cleanup statistics
    """
    try:
        # Use timezone-aware datetime (Python 3.12+ compatible)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=retention_days)
        # Remove timezone for comparison with naive datetime in database
        cutoff_date_naive = cutoff_date.replace(tzinfo=None)

        # Delete old records and get actual count deleted
        delete_query = session.query(NetworkMetric).filter(
            NetworkMetric.timestamp < cutoff_date_naive
        )
        records_deleted = delete_query.delete(synchronize_session=False)
        session.commit()

        if records_deleted == 0:
            logger.info(f"No network metric records older than {retention_days} days found")
        else:
            logger.info(
                f"Cleaned up {records_deleted} network metric records older than "
                f"{retention_days} days (before {cutoff_date_naive.date()})"
            )

        return {
            "success": True,
            "records_deleted": records_deleted,
            "retention_days": retention_days,
            "cutoff_date": cutoff_date.isoformat(),
        }

    except Exception as e:
        session.rollback()
        logger.error(f"Failed to cleanup old network metric records: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "records_deleted": 0,
            "retention_days": retention_days,
        }


def vacuum_database(session: Session) -> dict:
    """Run VACUUM on the SQLite database to reclaim disk space and optimize performance.

    VACUUM rebuilds the database file, reclaiming unused space from deleted records
    and defragmenting the file for faster access. This should be run after bulk
    deletions to prevent the database file from growing indefinitely.

    Note: VACUUM requires exclusive access to the database and may take several
    seconds on large databases.

    Args:
        session: Database session

    Returns:
        dict with vacuum statistics
    """
    try:
        # Get database file size before vacuum (for SQLite)
        engine = session.get_bind()

        # Get page statistics before vacuum
        result = session.execute(text("PRAGMA page_count"))
        page_count_before = result.scalar()
        result = session.execute(text("PRAGMA freelist_count"))
        freelist_before = result.scalar()
        result = session.execute(text("PRAGMA page_size"))
        page_size = result.scalar()

        size_before = page_count_before * page_size if page_count_before and page_size else 0
        fragmentation = (freelist_before / page_count_before * 100) if page_count_before else 0

        # Only vacuum if there's significant fragmentation (> 10%)
        if fragmentation < 10:
            logger.info(
                f"Skipping VACUUM - fragmentation is only {fragmentation:.1f}% "
                f"(threshold: 10%)"
            )
            return {
                "success": True,
                "skipped": True,
                "reason": f"Low fragmentation ({fragmentation:.1f}%)",
                "fragmentation_percent": fragmentation,
            }

        logger.info(
            f"Running VACUUM - {fragmentation:.1f}% fragmentation detected "
            f"({freelist_before:,} free pages / {page_count_before:,} total)"
        )

        # Commit any pending transactions before VACUUM
        session.commit()

        # VACUUM must be run outside of a transaction
        # Use raw connection to execute VACUUM
        connection = engine.raw_connection()
        try:
            connection.execute("VACUUM")
            connection.commit()
        finally:
            connection.close()

        # Get size after vacuum
        result = session.execute(text("PRAGMA page_count"))
        page_count_after = result.scalar()
        size_after = page_count_after * page_size if page_count_after and page_size else 0

        bytes_reclaimed = size_before - size_after
        mb_reclaimed = bytes_reclaimed / (1024 * 1024)

        logger.info(
            f"VACUUM completed: reclaimed {mb_reclaimed:.1f} MB "
            f"({size_before / (1024*1024):.1f} MB -> {size_after / (1024*1024):.1f} MB)"
        )

        return {
            "success": True,
            "skipped": False,
            "size_before_bytes": size_before,
            "size_after_bytes": size_after,
            "bytes_reclaimed": bytes_reclaimed,
            "mb_reclaimed": round(mb_reclaimed, 2),
            "fragmentation_percent_before": round(fragmentation, 1),
        }

    except Exception as e:
        logger.error(f"Failed to vacuum database: {e}", exc_info=True)
        return {
            "success": False,
            "skipped": False,
            "error": str(e),
        }


def run_all_cleanup_tasks(
    session: Session,
    retention_days: int = 30,
    run_vacuum: bool = True
) -> dict:
    """Run all cleanup tasks including optional VACUUM.

    Args:
        session: Database session
        retention_days: Number of days to retain records (default: 30)
        run_vacuum: Whether to run VACUUM after cleanup (default: True)

    Returns:
        dict with combined cleanup statistics
    """
    logger.info(f"Starting database cleanup (retention: {retention_days} days)")

    connection_result = cleanup_old_connection_records(session, retention_days)
    node_metric_result = cleanup_old_node_metrics(session, retention_days)
    network_metric_result = cleanup_old_network_metrics(session, retention_days)

    total_deleted = (
        connection_result.get("records_deleted", 0) +
        node_metric_result.get("records_deleted", 0) +
        network_metric_result.get("records_deleted", 0)
    )

    logger.info(f"Database cleanup completed: {total_deleted} total records deleted")

    # Run VACUUM to reclaim disk space if records were deleted or if requested
    vacuum_result = None
    if run_vacuum:
        vacuum_result = vacuum_database(session)

    cleanup_success = (
        connection_result["success"] and
        node_metric_result["success"] and
        network_metric_result["success"]
    )

    result = {
        "success": cleanup_success,
        "total_records_deleted": total_deleted,
        "connection_records_deleted": connection_result.get("records_deleted", 0),
        "node_metric_records_deleted": node_metric_result.get("records_deleted", 0),
        "network_metric_records_deleted": network_metric_result.get("records_deleted", 0),
        "retention_days": retention_days,
    }

    if vacuum_result:
        result["vacuum"] = vacuum_result

    return result
