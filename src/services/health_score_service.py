"""Network health score service.

Computes a 0-100 score combining:
- WAN Uptime (30%): % of online readings in the last hour
- Node Availability (25%): % of nodes currently online
- Mesh Quality (25%): Average mesh_quality_bars / 5 * 100
- Signal Quality (20%): Average signal strength mapped to 0-100
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from src.models.database import DeviceConnection, EeroNode, EeroNodeMetric, NetworkMetric

logger = logging.getLogger(__name__)

# Scoring weights
WEIGHT_WAN_UPTIME = 0.30
WEIGHT_NODE_AVAILABILITY = 0.25
WEIGHT_MESH_QUALITY = 0.25
WEIGHT_SIGNAL_QUALITY = 0.20

# Signal strength mapping: -30 dBm = 100, -90 dBm = 0
SIGNAL_BEST = -30
SIGNAL_WORST = -90


def _signal_to_score(dbm: float) -> float:
    """Map signal strength in dBm to a 0-100 score."""
    if dbm >= SIGNAL_BEST:
        return 100.0
    if dbm <= SIGNAL_WORST:
        return 0.0
    return round((dbm - SIGNAL_WORST) / (SIGNAL_BEST - SIGNAL_WORST) * 100, 1)


def compute_health_score(
    db: Session,
    network_name: str,
    window_minutes: int = 60,
) -> Dict[str, Any]:
    """Compute current network health score.

    Args:
        db: Database session.
        network_name: Network to score.
        window_minutes: Time window for WAN uptime calculation.

    Returns:
        Dict with overall score, component scores, and color.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)

    # 1. WAN Uptime (% of online readings)
    wan_total = (
        db.query(func.count())
        .select_from(NetworkMetric)
        .filter(
            NetworkMetric.network_name == network_name,
            NetworkMetric.timestamp >= cutoff,
            NetworkMetric.wan_status.isnot(None),
        )
        .scalar()
    ) or 0

    wan_online = (
        db.query(func.count())
        .select_from(NetworkMetric)
        .filter(
            NetworkMetric.network_name == network_name,
            NetworkMetric.timestamp >= cutoff,
            NetworkMetric.wan_status == "connected",
        )
        .scalar()
    ) or 0

    wan_score = (wan_online / wan_total * 100) if wan_total > 0 else 100.0

    # 2. Node Availability (% of nodes with latest status = online)
    nodes = db.query(EeroNode).filter(EeroNode.network_name == network_name).all()
    nodes_online = 0
    nodes_total = len(nodes)

    for node in nodes:
        latest = (
            db.query(EeroNodeMetric)
            .filter(
                EeroNodeMetric.eero_node_id == node.id,
                EeroNodeMetric.timestamp >= cutoff,
            )
            .order_by(EeroNodeMetric.timestamp.desc())
            .first()
        )
        if latest and latest.status == "online":
            nodes_online += 1

    node_score = (nodes_online / nodes_total * 100) if nodes_total > 0 else 100.0

    # 3. Mesh Quality (average bars / 5 * 100)
    mesh_avg = (
        db.query(func.avg(EeroNodeMetric.mesh_quality_bars))
        .filter(
            EeroNodeMetric.eero_node_id.in_([n.id for n in nodes]),
            EeroNodeMetric.timestamp >= cutoff,
            EeroNodeMetric.mesh_quality_bars.isnot(None),
        )
        .scalar()
    )
    mesh_score = (float(mesh_avg) / 5 * 100) if mesh_avg else 100.0

    # 4. Signal Quality (average signal mapped to 0-100)
    signal_avg = (
        db.query(func.avg(DeviceConnection.signal_strength))
        .filter(
            DeviceConnection.network_name == network_name,
            DeviceConnection.timestamp >= cutoff,
            DeviceConnection.signal_strength.isnot(None),
            DeviceConnection.is_connected == True,
        )
        .scalar()
    )
    signal_score = _signal_to_score(float(signal_avg)) if signal_avg else 100.0

    # Weighted total
    overall = round(
        wan_score * WEIGHT_WAN_UPTIME
        + node_score * WEIGHT_NODE_AVAILABILITY
        + mesh_score * WEIGHT_MESH_QUALITY
        + signal_score * WEIGHT_SIGNAL_QUALITY,
        1,
    )
    overall = max(0, min(100, overall))

    color = "green" if overall >= 80 else "yellow" if overall >= 50 else "red"

    return {
        "score": overall,
        "color": color,
        "components": {
            "wan_uptime": {"score": round(wan_score, 1), "weight": WEIGHT_WAN_UPTIME},
            "node_availability": {"score": round(node_score, 1), "weight": WEIGHT_NODE_AVAILABILITY},
            "mesh_quality": {"score": round(mesh_score, 1), "weight": WEIGHT_MESH_QUALITY},
            "signal_quality": {"score": round(signal_score, 1), "weight": WEIGHT_SIGNAL_QUALITY},
        },
        "window_minutes": window_minutes,
    }


def compute_health_history(
    db: Session,
    network_name: str,
    hours: int = 168,
) -> List[Dict[str, Any]]:
    """Compute hourly health scores for a historical trend.

    Args:
        db: Database session.
        network_name: Network to score.
        hours: Number of hours to look back.

    Returns:
        List of {timestamp, score} dicts, one per hour.
    """
    now = datetime.now(timezone.utc)
    history = []

    for h in range(hours, -1, -1):
        hour_end = now - timedelta(hours=h)
        hour_start = hour_end - timedelta(hours=1)

        # Simplified scoring for historical data - use WAN + node status only
        # to avoid expensive per-hour signal queries
        wan_total = (
            db.query(func.count())
            .select_from(NetworkMetric)
            .filter(
                NetworkMetric.network_name == network_name,
                NetworkMetric.timestamp >= hour_start,
                NetworkMetric.timestamp < hour_end,
                NetworkMetric.wan_status.isnot(None),
            )
            .scalar()
        ) or 0

        wan_online = (
            db.query(func.count())
            .select_from(NetworkMetric)
            .filter(
                NetworkMetric.network_name == network_name,
                NetworkMetric.timestamp >= hour_start,
                NetworkMetric.timestamp < hour_end,
                NetworkMetric.wan_status == "connected",
            )
            .scalar()
        ) or 0

        wan_pct = (wan_online / wan_total * 100) if wan_total > 0 else None

        if wan_pct is not None:
            history.append({
                "timestamp": hour_end.isoformat(),
                "score": round(wan_pct, 1),
            })

    return history
