"""Main FastAPI application for eeroVista."""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src import __version__
from src.api import health, setup, web
from src.config import ensure_data_directory, get_settings
from src.scheduler.jobs import get_scheduler
from src.utils.database import init_database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    logger.info(f"Starting eeroVista v{__version__}")

    # Ensure data directory exists
    ensure_data_directory()

    # Initialize database
    logger.info("Initializing database...")
    init_database()

    # Start background collectors
    logger.info("Starting background data collectors...")
    scheduler = get_scheduler()
    scheduler.start()

    yield

    # Shutdown
    logger.info("Shutting down eeroVista")
    scheduler.stop()


# Create FastAPI app
app = FastAPI(
    title="eeroVista",
    description="Read-only monitoring for Eero mesh networks",
    version=__version__,
    lifespan=lifespan,
)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include routers
app.include_router(web.router)
app.include_router(setup.router)
app.include_router(health.router)

# TODO: Include additional routers
# app.include_router(prometheus.router)
# app.include_router(zabbix.router)
# app.include_router(devices_api.router)


@app.get("/favicon.ico")
async def favicon():
    """Return 404 for favicon requests."""
    from fastapi.responses import Response
    return Response(status_code=404)


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    log_level = settings.log_level.lower()

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8080,
        reload=settings.debug,
        log_level=log_level,
    )
