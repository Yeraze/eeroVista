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


@router.get("/collection-status")
async def collection_status() -> Dict[str, Any]:
    """Get data collection status and timestamps."""
    try:
        with get_db_context() as db:
            from src.models.database import Config

            # Get last collection timestamps
            collectors = ["device", "network", "speedtest"]
            last_collections = {}

            for collector_type in collectors:
                config_key = f"last_collection_{collector_type}"
                config = db.query(Config).filter(Config.key == config_key).first()

                if config and config.value:
                    try:
                        timestamp = datetime.fromisoformat(config.value)
                        last_collections[collector_type] = {
                            "timestamp": config.value,
                            "seconds_ago": int(
                                (datetime.utcnow() - timestamp).total_seconds()
                            ),
                        }
                    except Exception:
                        last_collections[collector_type] = None
                else:
                    last_collections[collector_type] = None

            return {
                "collections": last_collections,
                "collection_interval_seconds": 300,  # 5 minutes
            }

    except Exception as e:
        logger.error(f"Failed to get collection status: {e}")
        return {"collections": {}, "error": str(e)}
