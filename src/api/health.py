"""Health check and status API endpoints."""

import logging
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src import __version__
from src.eero_client import EeroClientWrapper
from src.utils.database import get_db, get_db_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["health"])

# Track when the app started
APP_START_TIME = datetime.utcnow()


def get_eero_client(db: Session = Depends(get_db)) -> EeroClientWrapper:
    """Dependency to get Eero client."""
    return EeroClientWrapper(db)


@router.get("/health")
async def health_check(client: EeroClientWrapper = Depends(get_eero_client)) -> Dict[str, Any]:
    """Health check endpoint."""
    uptime = (datetime.utcnow() - APP_START_TIME).total_seconds()

    # Check database
    db_status = "connected"
    try:
        # Try a simple query
        with get_db_context() as db:
            from src.models.database import Config
            db.query(Config).first()
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "error"

    # Check Eero API auth
    eero_status = "authenticated" if client.is_authenticated() else "not_authenticated"

    overall_status = "healthy" if db_status == "connected" else "degraded"

    return {
        "status": overall_status,
        "version": __version__,
        "uptime_seconds": int(uptime),
        "database": db_status,
        "eero_api": eero_status,
        "timestamp": datetime.utcnow().isoformat(),
    }
