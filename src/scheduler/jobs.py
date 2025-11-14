"""Background job scheduler using APScheduler."""

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.collectors import DeviceCollector, NetworkCollector, RoutingCollector, SpeedtestCollector
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
        self._migrations_retried = False  # Track if we've retried auth-dependent migrations
        self._consecutive_failures = {
            "device_collector": 0,
            "network_collector": 0,
            "speedtest_collector": 0,
            "routing_collector": 0,
        }
        self._max_consecutive_failures = 3  # Threshold for health alerts

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

        # Routing collector - run hourly (reservations/forwards change infrequently)
        routing_interval = 3600  # 1 hour
        self.scheduler.add_job(
            func=self._run_routing_collector,
            trigger=IntervalTrigger(seconds=routing_interval),
            id="routing_collector",
            name="Routing Collector",
            replace_existing=True,
        )

        # Database cleanup - run daily at 3 AM to remove old records
        self.scheduler.add_job(
            func=self._run_database_cleanup,
            trigger=CronTrigger(hour=3, minute=0),
            id="database_cleanup",
            name="Database Cleanup",
            replace_existing=True,
        )

        # Start the scheduler
        self.scheduler.start()
        logger.info(
            f"Scheduler started - device collector: {device_interval}s, "
            f"network/speedtest collectors: {network_interval}s, "
            f"routing collector: {routing_interval}s, "
            f"database cleanup: daily at 3:00 AM"
        )

        # Run collectors immediately on startup
        logger.info("Running initial data collection...")
        self._run_device_collector()
        self._run_network_collector()
        self._run_speedtest_collector()
        self._run_routing_collector()

    def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler and self.scheduler.running:
            logger.info("Stopping collector scheduler")
            self.scheduler.shutdown()
            self.scheduler = None

    def run_all_collectors_now(self) -> None:
        """Trigger immediate collection run for all collectors."""
        logger.info("Running all collectors immediately")
        self._run_device_collector()
        self._run_network_collector()
        self._run_speedtest_collector()
        self._run_routing_collector()

    def _run_device_collector(self) -> None:
        """Run the device collector."""
        collector_id = "device_collector"
        try:
            with get_db_context() as db:
                client = EeroClientWrapper(db)
                collector = DeviceCollector(db, client)
                result = collector.run()

                if result.get("success"):
                    logger.info(
                        f"Device collection complete: {result.get('items_collected')} devices"
                    )
                    self._record_success(collector_id)

                    # Retry auth-dependent migrations after first successful authentication
                    self._retry_auth_migrations_if_needed(client)

                    # Update DNS hosts file after successful device collection
                    try:
                        from src.services.dns_service import update_dns_on_device_change
                        update_dns_on_device_change()
                    except Exception as dns_error:
                        logger.error(f"DNS update failed: {dns_error}", exc_info=True)
                else:
                    logger.error(f"Device collection failed: {result.get('error')}")
                    self._record_failure(collector_id, result.get('error', 'Unknown error'))

        except Exception as e:
            logger.error(f"Device collector error: {e}", exc_info=True)
            self._record_failure(collector_id, str(e))

    def _run_network_collector(self) -> None:
        """Run the network collector."""
        collector_id = "network_collector"
        try:
            with get_db_context() as db:
                client = EeroClientWrapper(db)
                collector = NetworkCollector(db, client)
                result = collector.run()

                if result.get("success"):
                    logger.info("Network collection complete")
                    self._record_success(collector_id)
                else:
                    logger.error(f"Network collection failed: {result.get('error')}")
                    self._record_failure(collector_id, result.get('error', 'Unknown error'))

        except Exception as e:
            logger.error(f"Network collector error: {e}", exc_info=True)
            self._record_failure(collector_id, str(e))

    def _run_speedtest_collector(self) -> None:
        """Run the speedtest collector."""
        collector_id = "speedtest_collector"
        try:
            with get_db_context() as db:
                client = EeroClientWrapper(db)
                collector = SpeedtestCollector(db, client)
                result = collector.run()

                if result.get("success"):
                    items = result.get("items_collected", 0)
                    if items > 0:
                        logger.info(f"Speedtest collection complete: {items} new results")
                    self._record_success(collector_id)
                else:
                    self._record_failure(collector_id, result.get('error', 'Unknown error'))

        except Exception as e:
            logger.error(f"Speedtest collector error: {e}", exc_info=True)
            self._record_failure(collector_id, str(e))

    def _run_routing_collector(self) -> None:
        """Run the routing collector."""
        collector_id = "routing_collector"
        try:
            with get_db_context() as db:
                client = EeroClientWrapper(db)
                collector = RoutingCollector(db, client)
                result = collector.run()

                if result.get("success"):
                    logger.info(
                        f"Routing collection complete: "
                        f"{result.get('reservations_added', 0)} reservations added, "
                        f"{result.get('reservations_updated', 0)} updated, "
                        f"{result.get('forwards_added', 0)} forwards added, "
                        f"{result.get('forwards_updated', 0)} updated"
                    )
                    self._record_success(collector_id)
                else:
                    logger.error(f"Routing collection failed: {result.get('error')}")
                    self._record_failure(collector_id, result.get('error', 'Unknown error'))

        except Exception as e:
            logger.error(f"Routing collector error: {e}", exc_info=True)
            self._record_failure(collector_id, str(e))

    def _run_database_cleanup(self) -> None:
        """Run database cleanup to remove old records."""
        try:
            from src.utils.cleanup import run_all_cleanup_tasks

            with get_db_context() as db:
                # Keep 30 days of data
                result = run_all_cleanup_tasks(db, retention_days=30)

                if result.get("success"):
                    logger.info(
                        f"Database cleanup complete: "
                        f"{result.get('total_records_deleted', 0)} records deleted"
                    )
                else:
                    logger.error("Database cleanup failed")

        except Exception as e:
            logger.error(f"Database cleanup error: {e}", exc_info=True)

    def _retry_auth_migrations_if_needed(self, eero_client) -> None:
        """Retry auth-dependent migrations if not already done and client is authenticated.

        Args:
            eero_client: EeroClientWrapper instance
        """
        if self._migrations_retried:
            return

        if not eero_client.is_authenticated():
            return

        from src.migrations.runner import has_pending_auth_migrations, retry_auth_migrations

        if has_pending_auth_migrations():
            logger.info("Authenticated - retrying pending migrations")
            retry_auth_migrations(eero_client)
            self._migrations_retried = True

    def _record_success(self, collector_id: str) -> None:
        """Record successful collector run and reset failure counter.

        Args:
            collector_id: The collector identifier
        """
        if collector_id in self._consecutive_failures:
            # Reset consecutive failure count on success
            previous_failures = self._consecutive_failures[collector_id]
            self._consecutive_failures[collector_id] = 0

            # Log recovery if there were previous failures
            if previous_failures > 0:
                logger.info(
                    f"{collector_id} recovered after {previous_failures} consecutive failure(s)"
                )

    def _record_failure(self, collector_id: str, error_msg: str) -> None:
        """Record collector failure and check health status.

        Args:
            collector_id: The collector identifier
            error_msg: The error message from the failure
        """
        if collector_id not in self._consecutive_failures:
            self._consecutive_failures[collector_id] = 0

        self._consecutive_failures[collector_id] += 1
        failure_count = self._consecutive_failures[collector_id]

        logger.warning(
            f"{collector_id} failed {failure_count} consecutive time(s): {error_msg}"
        )

        # Alert on reaching threshold
        if failure_count == self._max_consecutive_failures:
            logger.error(
                f"HEALTH ALERT: {collector_id} has failed {failure_count} consecutive times! "
                f"Collector may be stuck. Last error: {error_msg}"
            )
        elif failure_count > self._max_consecutive_failures:
            # Log periodic reminders for prolonged failures
            if failure_count % 5 == 0:
                logger.error(
                    f"HEALTH ALERT: {collector_id} still failing after {failure_count} attempts"
                )

    def get_health_status(self) -> dict:
        """Get current health status of all collectors.

        Returns:
            dict with health status for each collector
        """
        status = {}
        for collector_id, failures in self._consecutive_failures.items():
            is_healthy = failures < self._max_consecutive_failures
            status[collector_id] = {
                "healthy": is_healthy,
                "consecutive_failures": failures,
                "status": "healthy" if is_healthy else "degraded" if failures < self._max_consecutive_failures * 2 else "critical"
            }
        return status


# Global scheduler instance
_scheduler: Optional[CollectorScheduler] = None


def get_scheduler() -> CollectorScheduler:
    """Get or create the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = CollectorScheduler()
    return _scheduler
