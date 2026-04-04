"""Request models and shared helpers for health API endpoints."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.eero_client import EeroClientWrapper
from src.utils.database import get_db

logger = logging.getLogger(__name__)


# Request models
class DeviceAliasesRequest(BaseModel):
    """Request model for updating device aliases."""
    aliases: List[str]


# Track when the app started
APP_START_TIME = datetime.now(timezone.utc)

# Simple in-memory cache for expensive queries
# Cache structure: {cache_key: (data, expiry_time)}
_bandwidth_cache: Dict[str, tuple[Dict[str, Any], float]] = {}
CACHE_TTL_SECONDS = 300  # 5 minutes


def get_eero_client(db: Session = Depends(get_db)) -> EeroClientWrapper:
    """Dependency to get Eero client."""
    return EeroClientWrapper(db)


def get_network_name_filter(network: Optional[str], client: EeroClientWrapper) -> Optional[str]:
    """
    Get the network name to filter by.

    If network is specified, use it.
    If not specified, use the first available network for backwards compatibility.
    Returns None only if no networks are available.
    """
    if network:
        return network

    # Default to first network for backwards compatibility
    networks = client.get_networks()
    if not networks:
        return None

    first_network = networks[0]
    if isinstance(first_network, dict):
        return first_network.get('name')
    else:
        return first_network.name
