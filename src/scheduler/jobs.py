"""Background job scheduler using APScheduler."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.collectors import DeviceCollector, NetworkCollector, RoutingCollector, SpeedtestCollector
from src.config import get_settings
from src.eero_client import EeroClientWrapper
from src.utils.database import get_db_context

logger = logging.getLogger(__name__)

# Default timeout for API operations (seconds)
DEFAULT_COLLECTOR_TIMEOUT = 60


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
        # Use 8 workers (2x collectors) for resilience if threads hang
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="collector")
        # Explicit initialization for all collectors
        self._running_collectors: dict[str, bool] = {
            "device_collector": False,
            "network_collector": False,
            "speedtest_collector": False,
            "routing_collector": False,
        }
        self._lock = threading.Lock()

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

    def _run_with_timeout(
        self,
        collector_id: str,
        func: Callable[[], dict],
        timeout: int = DEFAULT_COLLECTOR_TIMEOUT
    ) -> dict:
        """Run a collector function with timeout protection.

        This prevents collectors from hanging indefinitely if the eero API
        times out or becomes unresponsive. If a collector is already running,
        the new invocation is skipped to prevent job pileup.

        Note: Python's ThreadPoolExecutor.cancel() only prevents tasks from
        starting, it cannot interrupt running threads. If a timeout occurs,
        the thread may continue running in the background until completion.
        The running state tracking prevents new invocations from piling up.

        Args:
            collector_id: Unique identifier for the collector
            func: The collector function to run (must return dict)
            timeout: Maximum seconds to wait (default: 60)

        Returns:
            dict with success status and any error information
        """
        # Check if this collector is already running
        with self._lock:
            if self._running_collectors.get(collector_id, False):
                logger.warning(
                    f"{collector_id} skipped - previous run still in progress. "
                    f"This may indicate the eero API is slow or unresponsive."
                )
                return {
                    "success": False,
                    "error": "Previous run still in progress",
                    "skipped": True,
                }
            self._running_collectors[collector_id] = True

        try:
            # Submit the work to the thread pool with timeout
            future = self._executor.submit(func)
            try:
                result = future.result(timeout=timeout)
                return result
            except FuturesTimeoutError:
                logger.error(
                    f"{collector_id} TIMEOUT after {timeout}s - "
                    f"eero API may be unresponsive. Thread may continue in background."
                )
                # Note: cancel() only prevents queued tasks from starting,
                # it cannot stop an already-running thread
                future.cancel()
                return {
                    "success": False,
                    "error": f"Operation timed out after {timeout} seconds",
                    "timeout": True,
                }
        finally:
            # Always clear the running flag so next scheduled run can proceed
            with self._lock:
                self._running_collectors[collector_id] = False

    def stop(self) -> None:
        """Stop the scheduler and cleanup resources."""
        if self.scheduler and self.scheduler.running:
            logger.info("Stopping collector scheduler")
            self.scheduler.shutdown()
            self.scheduler = None

        # Shutdown the thread pool executor, waiting for in-flight operations
        # to complete to avoid data corruption from interrupted transactions
        if hasattr(self, '_executor'):
            logger.info("Shutting down collector thread pool (waiting for in-flight tasks)")
            self._executor.shutdown(wait=True)

    def run_all_collectors_now(self) -> None:
        """Trigger immediate collection run for all collectors."""
        logger.info("Running all collectors immediately")
        self._run_device_collector()
        self._run_network_collector()
        self._run_speedtest_collector()
        self._run_routing_collector()

    def _run_device_collector(self) -> None:
        """Run the device collector with timeout protection."""
        collector_id = "device_collector"

        def _do_collect():
            with get_db_context() as db:
                client = EeroClientWrapper(db)
                collector = DeviceCollector(db, client)
                return collector.run()

        try:
            result = self._run_with_timeout(collector_id, _do_collect)

            if result.get("skipped"):
                # Don't record as failure if skipped due to already running
                return

            if result.get("success"):
                logger.info(
                    f"Device collection complete: {result.get('items_collected')} devices"
                )
                self._record_success(collector_id)

                # Only run side effects if collection completed successfully (not timed out)
                # These run outside the timeout wrapper to avoid background execution on timeout
                with get_db_context() as db:
                    client = EeroClientWrapper(db)
                    # Retry auth-dependent migrations after first successful authentication
                    self._retry_auth_migrations_if_needed(client)

                # Update DNS hosts file after successful device collection
                try:
                    from src.services.dns_service import update_dns_on_device_change
                    update_dns_on_device_change()
                except Exception as dns_error:
                    logger.error(f"DNS update failed: {dns_error}", exc_info=True)
            else:
                error = result.get('error', 'Unknown error')
                if result.get("timeout"):
                    logger.error(f"Device collection timed out: {error}")
                else:
                    logger.error(f"Device collection failed: {error}")
                self._record_failure(collector_id, error)

        except Exception as e:
            logger.error(f"Device collector error: {e}", exc_info=True)
            self._record_failure(collector_id, str(e))

    def _run_network_collector(self) -> None:
        """Run the network collector with timeout protection."""
        collector_id = "network_collector"

        def _do_collect():
            with get_db_context() as db:
                client = EeroClientWrapper(db)
                collector = NetworkCollector(db, client)
                return collector.run()

        try:
            result = self._run_with_timeout(collector_id, _do_collect)

            if result.get("skipped"):
                return

            if result.get("success"):
                logger.info("Network collection complete")
                self._record_success(collector_id)
            else:
                error = result.get('error', 'Unknown error')
                if result.get("timeout"):
                    logger.error(f"Network collection timed out: {error}")
                else:
                    logger.error(f"Network collection failed: {error}")
                self._record_failure(collector_id, error)

        except Exception as e:
            logger.error(f"Network collector error: {e}", exc_info=True)
            self._record_failure(collector_id, str(e))

    def _run_speedtest_collector(self) -> None:
        """Run the speedtest collector with timeout protection."""
        collector_id = "speedtest_collector"

        def _do_collect():
            with get_db_context() as db:
                client = EeroClientWrapper(db)
                collector = SpeedtestCollector(db, client)
                return collector.run()

        try:
            result = self._run_with_timeout(collector_id, _do_collect)

            if result.get("skipped"):
                return

            if result.get("success"):
                items = result.get("items_collected", 0)
                if items > 0:
                    logger.info(f"Speedtest collection complete: {items} new results")
                self._record_success(collector_id)
            else:
                error = result.get('error', 'Unknown error')
                if result.get("timeout"):
                    logger.error(f"Speedtest collection timed out: {error}")
                self._record_failure(collector_id, error)

        except Exception as e:
            logger.error(f"Speedtest collector error: {e}", exc_info=True)
            self._record_failure(collector_id, str(e))

    def _run_routing_collector(self) -> None:
        """Run the routing collector with timeout protection."""
        collector_id = "routing_collector"

        def _do_collect():
            with get_db_context() as db:
                client = EeroClientWrapper(db)
                collector = RoutingCollector(db, client)
                return collector.run()

        try:
            result = self._run_with_timeout(collector_id, _do_collect)

            if result.get("skipped"):
                return

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
                error = result.get('error', 'Unknown error')
                if result.get("timeout"):
                    logger.error(f"Routing collection timed out: {error}")
                else:
                    logger.error(f"Routing collection failed: {error}")
                self._record_failure(collector_id, error)

        except Exception as e:
            logger.error(f"Routing collector error: {e}", exc_info=True)
            self._record_failure(collector_id, str(e))

    def _run_database_cleanup(self) -> None:
        """Run database cleanup to remove old records."""
        try:
            from src.config import get_settings
            from src.utils.cleanup import run_all_cleanup_tasks

            settings = get_settings()

            with get_db_context() as db:
                # Use configured retention days
                result = run_all_cleanup_tasks(db, retention_days=settings.data_retention_raw_days)

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
        with self._lock:
            running_collectors = dict(self._running_collectors)

        for collector_id, failures in self._consecutive_failures.items():
            is_running = running_collectors.get(collector_id, False)
            # Health is based on failure count only - running is a normal state
            is_healthy = failures < self._max_consecutive_failures

            if failures == 0:
                collector_status = "healthy"
            elif failures < self._max_consecutive_failures:
                collector_status = "degraded"
            elif failures < self._max_consecutive_failures * 2:
                collector_status = "critical"
            else:
                collector_status = "failed"

            status[collector_id] = {
                "healthy": is_healthy,
                "consecutive_failures": failures,
                "currently_running": is_running,
                "status": collector_status
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
