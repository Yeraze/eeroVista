"""Database cleanup utilities for maintaining optimal performance."""

import logging
from datetime import datetime, timedelta

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
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

        # Count records to be deleted
        count_query = session.query(func.count(DeviceConnection.id)).filter(
            DeviceConnection.timestamp < cutoff_date
        )
        records_to_delete = count_query.scalar()

        if records_to_delete == 0:
            logger.info(f"No connection records older than {retention_days} days found")
            return {
                "success": True,
                "records_deleted": 0,
                "retention_days": retention_days,
                "cutoff_date": cutoff_date.isoformat(),
            }

        # Delete old records
        delete_query = session.query(DeviceConnection).filter(
            DeviceConnection.timestamp < cutoff_date
        )
        delete_query.delete(synchronize_session=False)
        session.commit()

        logger.info(
            f"Cleaned up {records_to_delete} connection records older than "
            f"{retention_days} days (before {cutoff_date.date()})"
        )

        return {
            "success": True,
            "records_deleted": records_to_delete,
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
        cutoff_date = datetime.utcnow() - timedelta(days=retention_days)

        # Count records to be deleted
        count_query = session.query(func.count(EeroNodeMetric.id)).filter(
            EeroNodeMetric.timestamp < cutoff_date
        )
        records_to_delete = count_query.scalar()

        if records_to_delete == 0:
            logger.info(f"No node metric records older than {retention_days} days found")
            return {
                "success": True,
                "records_deleted": 0,
                "retention_days": retention_days,
                "cutoff_date": cutoff_date.isoformat(),
            }

        # Delete old records
        delete_query = session.query(EeroNodeMetric).filter(
            EeroNodeMetric.timestamp < cutoff_date
        )
        delete_query.delete(synchronize_session=False)
        session.commit()

        logger.info(
            f"Cleaned up {records_to_delete} node metric records older than "
            f"{retention_days} days (before {cutoff_date.date()})"
        )

        return {
            "success": True,
            "records_deleted": records_to_delete,
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
