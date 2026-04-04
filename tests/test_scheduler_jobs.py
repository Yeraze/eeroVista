"""Tests for scheduler/jobs.py - Background job scheduler."""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, call, patch

import pytest


@pytest.fixture
def scheduler():
    """Create a CollectorScheduler instance with mocked settings."""
    with patch("src.scheduler.jobs.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(
            collection_interval_devices=30,
            collection_interval_network=60,
            notification_check_interval=60,
            data_retention_raw_days=7,
        )
        from src.scheduler.jobs import CollectorScheduler

        sched = CollectorScheduler()
        yield sched
        # Cleanup executor
        sched._executor.shutdown(wait=False)


class TestCollectorSchedulerInit:
    """Tests for CollectorScheduler initialization."""

    def test_scheduler_is_none_initially(self, scheduler):
        assert scheduler.scheduler is None

    def test_running_collectors_initialized(self, scheduler):
        expected_keys = {
            "device_collector",
            "network_collector",
            "speedtest_collector",
            "routing_collector",
            "notification_checker",
        }
        assert set(scheduler._running_collectors.keys()) == expected_keys
        assert all(v is False for v in scheduler._running_collectors.values())

    def test_consecutive_failures_initialized_to_zero(self, scheduler):
        assert all(v == 0 for v in scheduler._consecutive_failures.values())

    def test_migrations_retried_is_false_initially(self, scheduler):
        assert scheduler._migrations_retried is False

    def test_has_thread_pool_executor(self, scheduler):
        assert scheduler._executor is not None
        assert isinstance(scheduler._executor, ThreadPoolExecutor)

    def test_has_lock(self, scheduler):
        assert scheduler._lock is not None
        assert isinstance(scheduler._lock, type(threading.Lock()))


class TestRunWithTimeout:
    """Tests for _run_with_timeout method."""

    def test_runs_function_successfully(self, scheduler):
        def my_func():
            return {"success": True, "items_collected": 5}

        result = scheduler._run_with_timeout("test_collector", my_func, timeout=10)
        assert result["success"] is True
        assert result["items_collected"] == 5

    def test_skips_if_collector_already_running(self, scheduler):
        # Mark the collector as running
        scheduler._running_collectors["device_collector"] = True

        def my_func():
            return {"success": True}

        result = scheduler._run_with_timeout("device_collector", my_func, timeout=5)
        assert result.get("skipped") is True
        assert result["success"] is False

    def test_clears_running_flag_after_completion(self, scheduler):
        def my_func():
            return {"success": True}

        scheduler._run_with_timeout("device_collector", my_func, timeout=10)
        assert scheduler._running_collectors["device_collector"] is False

    def test_clears_running_flag_on_exception(self, scheduler):
        def failing_func():
            raise RuntimeError("Simulated failure")

        with pytest.raises(RuntimeError):
            scheduler._run_with_timeout("device_collector", failing_func, timeout=10)

        assert scheduler._running_collectors["device_collector"] is False

    def test_handles_timeout(self, scheduler):
        import time

        def slow_func():
            time.sleep(10)  # Sleep longer than timeout
            return {"success": True}

        result = scheduler._run_with_timeout("device_collector", slow_func, timeout=1)
        assert result.get("timeout") is True
        assert result["success"] is False

    def test_returns_error_on_timeout(self, scheduler):
        import time

        def slow_func():
            time.sleep(10)
            return {"success": True}

        result = scheduler._run_with_timeout("network_collector", slow_func, timeout=1)
        assert "timed out" in result["error"].lower()


class TestRecordSuccess:
    """Tests for _record_success method."""

    def test_resets_failure_count_to_zero(self, scheduler):
        scheduler._consecutive_failures["device_collector"] = 3
        scheduler._record_success("device_collector")
        assert scheduler._consecutive_failures["device_collector"] == 0

    def test_no_error_when_failures_were_zero(self, scheduler):
        scheduler._consecutive_failures["device_collector"] = 0
        scheduler._record_success("device_collector")
        assert scheduler._consecutive_failures["device_collector"] == 0

    def test_handles_unknown_collector_id(self, scheduler):
        # Unknown collector_id - should not raise
        scheduler._record_success("unknown_collector")


class TestRecordFailure:
    """Tests for _record_failure method."""

    def test_increments_failure_count(self, scheduler):
        initial = scheduler._consecutive_failures["device_collector"]
        scheduler._record_failure("device_collector", "API timeout")
        assert scheduler._consecutive_failures["device_collector"] == initial + 1

    def test_multiple_failures_accumulate(self, scheduler):
        for i in range(5):
            scheduler._record_failure("device_collector", f"Error {i}")
        assert scheduler._consecutive_failures["device_collector"] == 5

    def test_initializes_unknown_collector(self, scheduler):
        scheduler._record_failure("new_collector", "Some error")
        assert scheduler._consecutive_failures["new_collector"] == 1

    def test_logs_health_alert_at_threshold(self, scheduler):
        scheduler._max_consecutive_failures = 3
        # Fill up to threshold minus one
        for i in range(2):
            scheduler._record_failure("device_collector", "error")
        # This should trigger the health alert log
        with patch("src.scheduler.jobs.logger") as mock_logger:
            scheduler._record_failure("device_collector", "critical error")
            # logger.error should have been called for the HEALTH ALERT
            error_calls = [str(c) for c in mock_logger.error.call_args_list]
            assert any("HEALTH ALERT" in c for c in error_calls)

    def test_logs_periodic_reminder_beyond_threshold(self, scheduler):
        scheduler._max_consecutive_failures = 3
        # Set failures to exactly 10 (5th multiple after threshold)
        scheduler._consecutive_failures["device_collector"] = 9
        with patch("src.scheduler.jobs.logger") as mock_logger:
            scheduler._record_failure("device_collector", "still broken")
            # At 10 failures (10 % 5 == 0), should log a periodic reminder
            error_calls = [str(c) for c in mock_logger.error.call_args_list]
            assert any("HEALTH ALERT" in c or "still failing" in c for c in error_calls)


class TestGetHealthStatus:
    """Tests for get_health_status method."""

    def test_returns_dict_with_all_collectors(self, scheduler):
        status = scheduler.get_health_status()
        assert "device_collector" in status
        assert "network_collector" in status
        assert "speedtest_collector" in status
        assert "routing_collector" in status
        assert "notification_checker" in status

    def test_healthy_when_no_failures(self, scheduler):
        status = scheduler.get_health_status()
        assert status["device_collector"]["healthy"] is True
        assert status["device_collector"]["status"] == "healthy"
        assert status["device_collector"]["consecutive_failures"] == 0

    def test_degraded_status_with_one_failure(self, scheduler):
        scheduler._consecutive_failures["device_collector"] = 1
        status = scheduler.get_health_status()
        assert status["device_collector"]["status"] == "degraded"
        assert status["device_collector"]["healthy"] is True  # Below threshold

    def test_critical_status_at_threshold(self, scheduler):
        scheduler._max_consecutive_failures = 3
        scheduler._consecutive_failures["device_collector"] = 3
        status = scheduler.get_health_status()
        assert status["device_collector"]["healthy"] is False
        assert status["device_collector"]["status"] == "critical"

    def test_failed_status_above_double_threshold(self, scheduler):
        scheduler._max_consecutive_failures = 3
        scheduler._consecutive_failures["device_collector"] = 6  # double threshold
        status = scheduler.get_health_status()
        assert status["device_collector"]["status"] == "failed"

    def test_reports_currently_running(self, scheduler):
        scheduler._running_collectors["device_collector"] = True
        status = scheduler.get_health_status()
        assert status["device_collector"]["currently_running"] is True


class TestStop:
    """Tests for stop method."""

    def test_stop_when_scheduler_is_none(self, scheduler):
        scheduler.scheduler = None
        # Should not raise
        scheduler.stop()

    def test_stop_shuts_down_running_scheduler(self, scheduler):
        mock_sched = MagicMock()
        mock_sched.running = True
        scheduler.scheduler = mock_sched

        scheduler.stop()

        mock_sched.shutdown.assert_called_once()
        assert scheduler.scheduler is None

    def test_stop_skips_non_running_scheduler(self, scheduler):
        mock_sched = MagicMock()
        mock_sched.running = False
        scheduler.scheduler = mock_sched

        scheduler.stop()

        mock_sched.shutdown.assert_not_called()


class TestRunDeviceCollector:
    """Tests for _run_device_collector method."""

    def test_records_success_on_successful_run(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context") as mock_ctx, \
             patch("src.scheduler.jobs.EeroClientWrapper") as MockClient, \
             patch("src.scheduler.jobs.DeviceCollector") as MockCollector:
            mock_db = MagicMock()
            mock_ctx.return_value.__enter__.return_value = mock_db
            mock_ctx.return_value.__exit__.return_value = None

            mock_collector = MagicMock()
            mock_collector.run.return_value = {"success": True, "items_collected": 5}
            MockCollector.return_value = mock_collector

            mock_client = MagicMock()
            mock_client.is_authenticated.return_value = False
            MockClient.return_value = mock_client

            with patch("src.services.dns_service.update_dns_on_device_change", side_effect=Exception("skip")):
                scheduler._run_device_collector()

            assert scheduler._consecutive_failures["device_collector"] == 0

    def test_records_failure_on_failed_run(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context") as mock_ctx, \
             patch("src.scheduler.jobs.EeroClientWrapper") as MockClient, \
             patch("src.scheduler.jobs.DeviceCollector") as MockCollector:
            mock_db = MagicMock()
            mock_ctx.return_value.__enter__.return_value = mock_db
            mock_ctx.return_value.__exit__.return_value = None

            mock_collector = MagicMock()
            mock_collector.run.return_value = {"success": False, "error": "Auth failed"}
            MockCollector.return_value = mock_collector
            MockClient.return_value = MagicMock()

            scheduler._run_device_collector()

            assert scheduler._consecutive_failures["device_collector"] >= 1

    def test_handles_exception_gracefully(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context") as mock_ctx:
            mock_ctx.side_effect = Exception("DB connection failed")

            scheduler._run_device_collector()

            assert scheduler._consecutive_failures["device_collector"] >= 1

    def test_skipped_result_does_not_record_failure(self, scheduler):
        with patch.object(scheduler, "_run_with_timeout", return_value={"success": False, "skipped": True}):
            initial = scheduler._consecutive_failures["device_collector"]
            scheduler._run_device_collector()
            assert scheduler._consecutive_failures["device_collector"] == initial


class TestRunNetworkCollector:
    """Tests for _run_network_collector method."""

    def test_records_success_on_successful_run(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context") as mock_ctx, \
             patch("src.scheduler.jobs.EeroClientWrapper"), \
             patch("src.scheduler.jobs.NetworkCollector") as MockCollector:
            mock_ctx.return_value.__enter__.return_value = MagicMock()
            mock_ctx.return_value.__exit__.return_value = None
            MockCollector.return_value.run.return_value = {"success": True}

            scheduler._run_network_collector()

            assert scheduler._consecutive_failures["network_collector"] == 0

    def test_records_failure_on_failed_run(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context") as mock_ctx, \
             patch("src.scheduler.jobs.EeroClientWrapper"), \
             patch("src.scheduler.jobs.NetworkCollector") as MockCollector:
            mock_ctx.return_value.__enter__.return_value = MagicMock()
            mock_ctx.return_value.__exit__.return_value = None
            MockCollector.return_value.run.return_value = {"success": False, "error": "API error"}

            scheduler._run_network_collector()

            assert scheduler._consecutive_failures["network_collector"] >= 1

    def test_handles_exception_gracefully(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context") as mock_ctx:
            mock_ctx.side_effect = RuntimeError("Connection error")

            scheduler._run_network_collector()

            assert scheduler._consecutive_failures["network_collector"] >= 1

    def test_skipped_result_is_ignored(self, scheduler):
        with patch.object(scheduler, "_run_with_timeout", return_value={"success": False, "skipped": True}):
            initial = scheduler._consecutive_failures["network_collector"]
            scheduler._run_network_collector()
            assert scheduler._consecutive_failures["network_collector"] == initial


class TestRunSpeedtestCollector:
    """Tests for _run_speedtest_collector method."""

    def test_records_success_when_no_new_items(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context") as mock_ctx, \
             patch("src.scheduler.jobs.EeroClientWrapper"), \
             patch("src.scheduler.jobs.SpeedtestCollector") as MockCollector:
            mock_ctx.return_value.__enter__.return_value = MagicMock()
            mock_ctx.return_value.__exit__.return_value = None
            MockCollector.return_value.run.return_value = {"success": True, "items_collected": 0}

            scheduler._run_speedtest_collector()

            assert scheduler._consecutive_failures["speedtest_collector"] == 0

    def test_records_failure_on_failed_run(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context") as mock_ctx, \
             patch("src.scheduler.jobs.EeroClientWrapper"), \
             patch("src.scheduler.jobs.SpeedtestCollector") as MockCollector:
            mock_ctx.return_value.__enter__.return_value = MagicMock()
            mock_ctx.return_value.__exit__.return_value = None
            MockCollector.return_value.run.return_value = {"success": False, "error": "Timeout"}

            scheduler._run_speedtest_collector()

            assert scheduler._consecutive_failures["speedtest_collector"] >= 1

    def test_handles_exception_gracefully(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context", side_effect=Exception("DB error")):
            scheduler._run_speedtest_collector()
            assert scheduler._consecutive_failures["speedtest_collector"] >= 1

    def test_skipped_result_is_ignored(self, scheduler):
        with patch.object(scheduler, "_run_with_timeout", return_value={"success": False, "skipped": True}):
            initial = scheduler._consecutive_failures["speedtest_collector"]
            scheduler._run_speedtest_collector()
            assert scheduler._consecutive_failures["speedtest_collector"] == initial


class TestRunRoutingCollector:
    """Tests for _run_routing_collector method."""

    def test_records_success_on_successful_run(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context") as mock_ctx, \
             patch("src.scheduler.jobs.EeroClientWrapper"), \
             patch("src.scheduler.jobs.RoutingCollector") as MockCollector:
            mock_ctx.return_value.__enter__.return_value = MagicMock()
            mock_ctx.return_value.__exit__.return_value = None
            MockCollector.return_value.run.return_value = {
                "success": True,
                "reservations_added": 2,
                "reservations_updated": 0,
                "forwards_added": 1,
                "forwards_updated": 0,
            }

            scheduler._run_routing_collector()

            assert scheduler._consecutive_failures["routing_collector"] == 0

    def test_records_failure_on_failed_run(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context") as mock_ctx, \
             patch("src.scheduler.jobs.EeroClientWrapper"), \
             patch("src.scheduler.jobs.RoutingCollector") as MockCollector:
            mock_ctx.return_value.__enter__.return_value = MagicMock()
            mock_ctx.return_value.__exit__.return_value = None
            MockCollector.return_value.run.return_value = {"success": False, "error": "Auth error"}

            scheduler._run_routing_collector()

            assert scheduler._consecutive_failures["routing_collector"] >= 1

    def test_handles_exception_gracefully(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context", side_effect=RuntimeError("DB crash")):
            scheduler._run_routing_collector()
            assert scheduler._consecutive_failures["routing_collector"] >= 1


class TestRunNotificationChecker:
    """Tests for _run_notification_checker method."""

    def test_records_success_when_no_urls(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context") as mock_ctx, \
             patch("src.api.notifications.get_apprise_urls", return_value=[]):
            mock_ctx.return_value.__enter__.return_value = MagicMock()
            mock_ctx.return_value.__exit__.return_value = None

            scheduler._run_notification_checker()

            assert scheduler._consecutive_failures["notification_checker"] == 0

    def test_handles_exception_gracefully(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context", side_effect=Exception("crash")):
            scheduler._run_notification_checker()
            assert scheduler._consecutive_failures["notification_checker"] >= 1

    def test_skipped_result_is_ignored(self, scheduler):
        with patch.object(scheduler, "_run_with_timeout", return_value={"success": False, "skipped": True}):
            initial = scheduler._consecutive_failures["notification_checker"]
            scheduler._run_notification_checker()
            assert scheduler._consecutive_failures["notification_checker"] == initial


class TestRunDatabaseCleanup:
    """Tests for _run_database_cleanup method."""

    def test_calls_run_all_cleanup_tasks(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context") as mock_ctx, \
             patch("src.scheduler.jobs.get_settings") as mock_settings, \
             patch("src.utils.cleanup.run_all_cleanup_tasks") as mock_cleanup:
            mock_db = MagicMock()
            mock_ctx.return_value.__enter__.return_value = mock_db
            mock_ctx.return_value.__exit__.return_value = None
            mock_settings.return_value = MagicMock(data_retention_raw_days=7)
            mock_cleanup.return_value = {"success": True, "total_records_deleted": 50}

            scheduler._run_database_cleanup()

            mock_cleanup.assert_called_once()

    def test_handles_exception_gracefully(self, scheduler):
        with patch("src.scheduler.jobs.get_db_context", side_effect=Exception("DB error")):
            # Should not raise
            scheduler._run_database_cleanup()


class TestRetryAuthMigrations:
    """Tests for _retry_auth_migrations_if_needed method."""

    def test_skips_if_already_retried(self, scheduler):
        scheduler._migrations_retried = True
        mock_client = MagicMock()

        with patch("src.migrations.runner.has_pending_auth_migrations") as mock_has:
            scheduler._retry_auth_migrations_if_needed(mock_client)
            mock_has.assert_not_called()

    def test_skips_if_not_authenticated(self, scheduler):
        scheduler._migrations_retried = False
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = False

        with patch("src.migrations.runner.has_pending_auth_migrations") as mock_has:
            scheduler._retry_auth_migrations_if_needed(mock_client)
            mock_has.assert_not_called()

    def test_runs_migrations_when_authenticated_and_pending(self, scheduler):
        scheduler._migrations_retried = False
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True

        with patch("src.scheduler.jobs.has_pending_auth_migrations", return_value=True, create=True), \
             patch("src.scheduler.jobs.retry_auth_migrations", create=True) as mock_retry:
            # Use direct import patching
            with patch.dict("sys.modules", {}):
                try:
                    from src.migrations.runner import has_pending_auth_migrations, retry_auth_migrations
                    with patch("src.migrations.runner.has_pending_auth_migrations", return_value=True), \
                         patch("src.migrations.runner.retry_auth_migrations") as mock_retry:
                        scheduler._retry_auth_migrations_if_needed(mock_client)
                        # After running, _migrations_retried should be True
                except ImportError:
                    pass

    def test_sets_migrations_retried_after_running(self, scheduler):
        scheduler._migrations_retried = False
        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True

        with patch("src.migrations.runner.has_pending_auth_migrations", return_value=True), \
             patch("src.migrations.runner.retry_auth_migrations"):
            scheduler._retry_auth_migrations_if_needed(mock_client)
            assert scheduler._migrations_retried is True


class TestGetScheduler:
    """Tests for get_scheduler module-level function."""

    def test_returns_scheduler_instance(self):
        with patch("src.scheduler.jobs.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                collection_interval_devices=30,
                collection_interval_network=60,
                notification_check_interval=60,
            )
            from src.scheduler.jobs import CollectorScheduler, get_scheduler

            sched = get_scheduler()
            assert isinstance(sched, CollectorScheduler)

    def test_returns_same_instance_on_second_call(self):
        from src.scheduler.jobs import get_scheduler

        sched1 = get_scheduler()
        sched2 = get_scheduler()
        assert sched1 is sched2


class TestRunAllCollectorsNow:
    """Tests for run_all_collectors_now method."""

    def test_calls_all_collector_methods(self, scheduler):
        with patch.object(scheduler, "_run_device_collector") as mock_device, \
             patch.object(scheduler, "_run_network_collector") as mock_network, \
             patch.object(scheduler, "_run_speedtest_collector") as mock_speedtest, \
             patch.object(scheduler, "_run_routing_collector") as mock_routing:
            scheduler.run_all_collectors_now()

            mock_device.assert_called_once()
            mock_network.assert_called_once()
            mock_speedtest.assert_called_once()
            mock_routing.assert_called_once()
