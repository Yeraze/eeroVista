"""Standalone collector process for eeroVista.

Runs APScheduler in a dedicated process managed by supervisord,
preventing duplicate collectors when uvicorn uses multiple workers.
"""

import asyncio
import logging
import signal
import sys

# Apply eero-client patches before any collector imports use eero
from src.utils.eero_patch import patch_eero_client  # noqa: F401

from src.config import ensure_data_directory, get_settings
from src.scheduler.jobs import CollectorScheduler
from src.utils.database import init_database

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


async def main():
    ensure_data_directory()

    logger.info("Initializing database for collector process...")
    init_database()

    scheduler = CollectorScheduler()
    scheduler.start()
    logger.info("Collector scheduler running in dedicated process")

    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("Collector process received shutdown signal")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    await stop_event.wait()

    logger.info("Shutting down collector scheduler...")
    scheduler.stop()
    logger.info("Collector scheduler stopped")


if __name__ == "__main__":
    asyncio.run(main())
