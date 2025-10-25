"""Database cleanup utilities for maintaining optimal performance."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.models.database import DeviceConnection, EeroNodeMetric

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


def run_all_cleanup_tasks(
    session: Session,
    retention_days: int = 30
) -> dict:
    """Run all cleanup tasks.

    Args:
        session: Database session
        retention_days: Number of days to retain records (default: 30)

    Returns:
        dict with combined cleanup statistics
    """
    logger.info(f"Starting database cleanup (retention: {retention_days} days)")

    connection_result = cleanup_old_connection_records(session, retention_days)
    node_metric_result = cleanup_old_node_metrics(session, retention_days)

    total_deleted = (
        connection_result.get("records_deleted", 0) +
        node_metric_result.get("records_deleted", 0)
    )

    logger.info(f"Database cleanup completed: {total_deleted} total records deleted")

    return {
        "success": connection_result["success"] and node_metric_result["success"],
        "total_records_deleted": total_deleted,
        "connection_records_deleted": connection_result.get("records_deleted", 0),
        "node_metric_records_deleted": node_metric_result.get("records_deleted", 0),
        "retention_days": retention_days,
    }
