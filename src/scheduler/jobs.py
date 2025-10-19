"""Background job scheduler using APScheduler."""

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.collectors import DeviceCollector, NetworkCollector, SpeedtestCollector
from src.config import get_settings
from src.eero_client import EeroClientWrapper
from src.utils.database import get_db_context

logger = logging.getLogger(__name__)


class CollectorScheduler:
    """Manages scheduled data collection tasks."""

    def __init__(self):
        """Initialize scheduler."""
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.settings = get_settings()

    def start(self) -> None:
        """Start the scheduler and add collection jobs."""
        if self.scheduler and self.scheduler.running:
            logger.warning("Scheduler already running")
            return

        logger.info("Starting collector scheduler")
        self.scheduler = AsyncIOScheduler()

        # Add collection jobs using configured intervals
        device_interval = self.settings.collection_interval_devices
        network_interval = self.settings.collection_interval_network

        # Device collector
        self.scheduler.add_job(
            func=self._run_device_collector,
            trigger=IntervalTrigger(seconds=device_interval),
            id="device_collector",
            name="Device Collector",
            replace_existing=True,
        )

        # Network collector
        self.scheduler.add_job(
            func=self._run_network_collector,
            trigger=IntervalTrigger(seconds=network_interval),
            id="network_collector",
            name="Network Collector",
            replace_existing=True,
        )

        # Speedtest collector - use network interval
        # (passive collection, won't trigger tests)
        self.scheduler.add_job(
            func=self._run_speedtest_collector,
            trigger=IntervalTrigger(seconds=network_interval),
            id="speedtest_collector",
            name="Speedtest Collector",
            replace_existing=True,
        )

        # Start the scheduler
        self.scheduler.start()
        logger.info(
            f"Scheduler started - device collector: {device_interval}s, "
            f"network/speedtest collectors: {network_interval}s"
        )

        # Run collectors immediately on startup
        logger.info("Running initial data collection...")
        self._run_device_collector()
        self._run_network_collector()
        self._run_speedtest_collector()

    def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler and self.scheduler.running:
            logger.info("Stopping collector scheduler")
            self.scheduler.shutdown()
            self.scheduler = None

    def _run_device_collector(self) -> None:
        """Run the device collector."""
        try:
            with get_db_context() as db:
                client = EeroClientWrapper(db)
                collector = DeviceCollector(db, client)
                result = collector.run()

                if result.get("success"):
                    logger.info(
                        f"Device collection complete: {result.get('items_collected')} devices"
                    )

                    # Update DNS hosts file after successful device collection
                    try:
                        from src.services.dns_service import update_dns_on_device_change
                        update_dns_on_device_change()
                    except Exception as dns_error:
                        logger.error(f"DNS update failed: {dns_error}", exc_info=True)
                else:
                    logger.error(f"Device collection failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Device collector error: {e}", exc_info=True)

    def _run_network_collector(self) -> None:
        """Run the network collector."""
        try:
            with get_db_context() as db:
                client = EeroClientWrapper(db)
                collector = NetworkCollector(db, client)
                result = collector.run()

                if result.get("success"):
                    logger.info("Network collection complete")
                else:
                    logger.error(f"Network collection failed: {result.get('error')}")

        except Exception as e:
            logger.error(f"Network collector error: {e}", exc_info=True)

    def _run_speedtest_collector(self) -> None:
        """Run the speedtest collector."""
        try:
            with get_db_context() as db:
                client = EeroClientWrapper(db)
                collector = SpeedtestCollector(db, client)
                result = collector.run()

                if result.get("success"):
                    items = result.get("items_collected", 0)
                    if items > 0:
                        logger.info(f"Speedtest collection complete: {items} new results")

        except Exception as e:
            logger.error(f"Speedtest collector error: {e}", exc_info=True)


# Global scheduler instance
_scheduler: Optional[CollectorScheduler] = None


def get_scheduler() -> CollectorScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = CollectorScheduler()
    return _scheduler
