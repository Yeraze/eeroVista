"""Main FastAPI application for eeroVista."""

import logging
import sys
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src import __version__

# IMPORTANT: Apply eero-client patches before any imports that use eero
# This import triggers module-level code that applies BOTH patches:
#   1. patch_pydantic_models() - Makes Optional fields accept None
#   2. patch_eero_client() - Fixes TypeAdapter usage
from src.utils.eero_patch import patch_eero_client  # noqa: F401

from src.api import device_groups, health, notifications, prometheus, setup, web, zabbix
from src.config import ensure_data_directory, get_settings
from src.mcp_server import build_mcp_server
from src.scheduler.jobs import get_scheduler
from src.utils.database import init_database

# Get settings to configure logging level
settings = get_settings()

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)

# Build the MCP server (when enabled) so it can be mounted on the app below.
# Its Streamable HTTP session manager must run within the app lifespan.
mcp_server = build_mcp_server(settings.mcp_path) if settings.mcp_enabled else None


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

    async with AsyncExitStack() as stack:
        # Run the MCP Streamable HTTP session manager for the app's lifetime.
        if mcp_server is not None:
            await stack.enter_async_context(mcp_server.session_manager.run())
            logger.info("MCP server enabled at %s (no authentication)", settings.mcp_path)

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
app.include_router(prometheus.router)
app.include_router(zabbix.router)
app.include_router(device_groups.router)
app.include_router(notifications.router)

# Mount the MCP server (read-only network-status tools for AI agents) when enabled.
if mcp_server is not None:
    app.mount(settings.mcp_path, mcp_server.streamable_http_app())


@app.get("/favicon.ico")
async def favicon():
    """Return 404 for favicon requests."""
    from fastapi.responses import Response
    return Response(status_code=404)


if __name__ == "__main__":
    import uvicorn

    log_level = settings.log_level.lower()

    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8080,
        reload=settings.debug,
        log_level=log_level,
    )
