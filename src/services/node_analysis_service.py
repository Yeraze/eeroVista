"""Node analysis service for restart detection and node health metrics."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from src.models.database import EeroNode, EeroNodeMetric

logger = logging.getLogger(__name__)


def detect_restarts(
    db: Session,
    node_id: int,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Detect node restarts by finding uptime counter resets.

    A restart is detected when uptime_seconds[t] < uptime_seconds[t-1].
    The estimated restart time is timestamp[t] - uptime_seconds[t].

    Args:
        db: Database session.
        node_id: Internal node ID.
        days: Number of days to look back.

    Returns:
        List of restart events with detected_at, estimated_restart_at,
        and previous_uptime_seconds.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    metrics = (
        db.query(EeroNodeMetric.timestamp, EeroNodeMetric.uptime_seconds)
        .filter(
            EeroNodeMetric.eero_node_id == node_id,
            EeroNodeMetric.timestamp >= cutoff,
            EeroNodeMetric.uptime_seconds.isnot(None),
        )
        .order_by(EeroNodeMetric.timestamp.asc())
        .all()
    )

    restarts = []
    for i in range(1, len(metrics)):
        prev_uptime = metrics[i - 1].uptime_seconds
        curr_uptime = metrics[i].uptime_seconds
        curr_ts = metrics[i].timestamp

        if curr_uptime < prev_uptime:
            estimated_restart = curr_ts - timedelta(seconds=curr_uptime)
            restarts.append({
                "detected_at": curr_ts.isoformat(),
                "estimated_restart_at": estimated_restart.isoformat(),
                "previous_uptime_seconds": prev_uptime,
            })

    return restarts


def get_node_restart_summary(
    db: Session,
    node_id: int,
    node_name: str,
    days: int = 30,
) -> Dict[str, Any]:
    """Get restart history summary for a node.

    Args:
        db: Database session.
        node_id: Internal node ID.
        node_name: Node location name for display.
        days: Number of days to look back.

    Returns:
        Summary dict with restarts list, count, and MTBR.
    """
    restarts = detect_restarts(db, node_id, days)

    mtbr_hours: Optional[float] = None
    if len(restarts) >= 2:
        # Calculate mean time between restarts
        restart_times = [
            datetime.fromisoformat(r["detected_at"]) for r in restarts
        ]
        intervals = [
            (restart_times[i] - restart_times[i - 1]).total_seconds() / 3600
            for i in range(1, len(restart_times))
        ]
        mtbr_hours = round(sum(intervals) / len(intervals), 1)

    return {
        "node_id": node_id,
        "node_name": node_name,
        "restarts": restarts,
        "total_restarts": len(restarts),
        "mean_time_between_restarts_hours": mtbr_hours,
        "period_days": days,
    }


def get_all_nodes_restart_counts(
    db: Session,
    network_name: str,
    days: int = 30,
) -> Dict[int, int]:
    """Get restart counts for all nodes in a network.

    Returns a dict mapping node_id -> restart_count for quick lookups.
    """
    nodes = (
        db.query(EeroNode)
        .filter(EeroNode.network_name == network_name)
        .all()
    )

    counts = {}
    for node in nodes:
        restarts = detect_restarts(db, node.id, days)
        counts[node.id] = len(restarts)

    return counts
