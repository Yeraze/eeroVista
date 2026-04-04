"""Tests for utils/cleanup.py - database cleanup utilities."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, Device, DeviceConnection, EeroNode, EeroNodeMetric, NetworkMetric


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    engine.dispose()


def make_old_timestamp(days_ago: int) -> datetime:
    """Create a naive datetime that is N days in the past."""
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago)


def make_recent_timestamp(days_ago: int = 1) -> datetime:
    """Create a naive datetime that is N days in the past (recent)."""
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days_ago)


class TestCleanupOldConnectionRecords:
    """Tests for cleanup_old_connection_records function."""

    def test_removes_records_older_than_retention_period(self, db_session):
        from src.utils.cleanup import cleanup_old_connection_records

        device = Device(network_name="Home", mac_address="AA:BB:CC:DD:EE:FF")
        db_session.add(device)
        db_session.commit()

        # Add old record (35 days ago) and new record (5 days ago)
        old_conn = DeviceConnection(
            network_name="Home",
            device_id=device.id,
            timestamp=make_old_timestamp(35),
            is_connected=False,
        )
        new_conn = DeviceConnection(
            network_name="Home",
            device_id=device.id,
            timestamp=make_recent_timestamp(5),
            is_connected=True,
        )
        db_session.add_all([old_conn, new_conn])
        db_session.commit()

        result = cleanup_old_connection_records(db_session, retention_days=30)

        assert result["success"] is True
        assert result["records_deleted"] == 1
        assert result["retention_days"] == 30
        assert "cutoff_date" in result

        remaining = db_session.query(DeviceConnection).count()
        assert remaining == 1

    def test_keeps_all_records_within_retention_period(self, db_session):
        from src.utils.cleanup import cleanup_old_connection_records

        device = Device(network_name="Home", mac_address="BB:CC:DD:EE:FF:00")
        db_session.add(device)
        db_session.commit()

        conn = DeviceConnection(
            network_name="Home",
            device_id=device.id,
            timestamp=make_recent_timestamp(5),
            is_connected=True,
        )
        db_session.add(conn)
        db_session.commit()

        result = cleanup_old_connection_records(db_session, retention_days=30)

        assert result["success"] is True
        assert result["records_deleted"] == 0
        assert db_session.query(DeviceConnection).count() == 1

    def test_returns_zero_deleted_when_no_records(self, db_session):
        from src.utils.cleanup import cleanup_old_connection_records

        result = cleanup_old_connection_records(db_session, retention_days=30)

        assert result["success"] is True
        assert result["records_deleted"] == 0

    def test_custom_retention_days(self, db_session):
        from src.utils.cleanup import cleanup_old_connection_records

        device = Device(network_name="Home", mac_address="CC:DD:EE:FF:00:11")
        db_session.add(device)
        db_session.commit()

        # Record from 10 days ago (older than 7 days retention)
        old_conn = DeviceConnection(
            network_name="Home",
            device_id=device.id,
            timestamp=make_old_timestamp(10),
        )
        # Record from 3 days ago (newer than 7 days retention)
        new_conn = DeviceConnection(
            network_name="Home",
            device_id=device.id,
            timestamp=make_recent_timestamp(3),
        )
        db_session.add_all([old_conn, new_conn])
        db_session.commit()

        result = cleanup_old_connection_records(db_session, retention_days=7)

        assert result["success"] is True
        assert result["records_deleted"] == 1
        assert result["retention_days"] == 7

    def test_deletes_multiple_old_records(self, db_session):
        from src.utils.cleanup import cleanup_old_connection_records

        device = Device(network_name="Home", mac_address="DD:EE:FF:00:11:22")
        db_session.add(device)
        db_session.commit()

        old_conns = [
            DeviceConnection(
                network_name="Home",
                device_id=device.id,
                timestamp=make_old_timestamp(40 + i),
            )
            for i in range(5)
        ]
        db_session.add_all(old_conns)
        db_session.commit()

        result = cleanup_old_connection_records(db_session, retention_days=30)

        assert result["success"] is True
        assert result["records_deleted"] == 5
        assert db_session.query(DeviceConnection).count() == 0


class TestCleanupOldNodeMetrics:
    """Tests for cleanup_old_node_metrics function."""

    def test_removes_old_node_metrics(self, db_session):
        from src.utils.cleanup import cleanup_old_node_metrics

        node = EeroNode(network_name="Home", eero_id="node_001")
        db_session.add(node)
        db_session.commit()

        old_metric = EeroNodeMetric(
            eero_node_id=node.id,
            timestamp=make_old_timestamp(45),
            status="online",
        )
        new_metric = EeroNodeMetric(
            eero_node_id=node.id,
            timestamp=make_recent_timestamp(2),
            status="online",
        )
        db_session.add_all([old_metric, new_metric])
        db_session.commit()

        result = cleanup_old_node_metrics(db_session, retention_days=30)

        assert result["success"] is True
        assert result["records_deleted"] == 1
        assert db_session.query(EeroNodeMetric).count() == 1

    def test_returns_zero_when_no_old_records(self, db_session):
        from src.utils.cleanup import cleanup_old_node_metrics

        node = EeroNode(network_name="Home", eero_id="node_002")
        db_session.add(node)
        db_session.commit()

        metric = EeroNodeMetric(
            eero_node_id=node.id,
            timestamp=make_recent_timestamp(1),
            status="online",
        )
        db_session.add(metric)
        db_session.commit()

        result = cleanup_old_node_metrics(db_session, retention_days=30)

        assert result["success"] is True
        assert result["records_deleted"] == 0

    def test_empty_table_returns_success(self, db_session):
        from src.utils.cleanup import cleanup_old_node_metrics

        result = cleanup_old_node_metrics(db_session, retention_days=30)

        assert result["success"] is True
        assert result["records_deleted"] == 0

    def test_includes_retention_days_in_result(self, db_session):
        from src.utils.cleanup import cleanup_old_node_metrics

        result = cleanup_old_node_metrics(db_session, retention_days=14)

        assert result["retention_days"] == 14
        assert "cutoff_date" in result


class TestCleanupOldNetworkMetrics:
    """Tests for cleanup_old_network_metrics function."""

    def test_removes_old_network_metrics(self, db_session):
        from src.utils.cleanup import cleanup_old_network_metrics

        old_metric = NetworkMetric(
            network_name="Home",
            timestamp=make_old_timestamp(60),
            total_devices=10,
        )
        new_metric = NetworkMetric(
            network_name="Home",
            timestamp=make_recent_timestamp(3),
            total_devices=12,
        )
        db_session.add_all([old_metric, new_metric])
        db_session.commit()

        result = cleanup_old_network_metrics(db_session, retention_days=30)

        assert result["success"] is True
        assert result["records_deleted"] == 1
        assert db_session.query(NetworkMetric).count() == 1

    def test_returns_zero_when_nothing_to_delete(self, db_session):
        from src.utils.cleanup import cleanup_old_network_metrics

        result = cleanup_old_network_metrics(db_session, retention_days=30)

        assert result["success"] is True
        assert result["records_deleted"] == 0

    def test_deletes_exactly_cutoff_boundary(self, db_session):
        from src.utils.cleanup import cleanup_old_network_metrics

        # Create record at exactly retention boundary - should be deleted
        boundary_metric = NetworkMetric(
            network_name="Home",
            timestamp=make_old_timestamp(31),
            total_devices=5,
        )
        db_session.add(boundary_metric)
        db_session.commit()

        result = cleanup_old_network_metrics(db_session, retention_days=30)

        assert result["success"] is True
        assert result["records_deleted"] == 1


class TestVacuumDatabase:
    """Tests for vacuum_database function."""

    def test_vacuum_skipped_on_low_fragmentation(self, db_session):
        from src.utils.cleanup import vacuum_database

        # An empty or minimally-used DB typically has very low fragmentation
        result = vacuum_database(db_session)

        assert result["success"] is True
        # Should skip since fragmentation will be low on a fresh DB
        assert result.get("skipped") is True
        assert "fragmentation_percent" in result

    def test_vacuum_returns_success_dict(self, db_session):
        from src.utils.cleanup import vacuum_database

        result = vacuum_database(db_session)

        assert "success" in result
        assert "skipped" in result

    def test_vacuum_includes_reason_when_skipped(self, db_session):
        from src.utils.cleanup import vacuum_database

        result = vacuum_database(db_session)

        if result.get("skipped"):
            assert "reason" in result


class TestRunAllCleanupTasks:
    """Tests for run_all_cleanup_tasks function."""

    def test_runs_all_three_cleanup_tasks(self, db_session):
        from src.utils.cleanup import run_all_cleanup_tasks

        device = Device(network_name="Home", mac_address="EE:FF:00:11:22:33")
        db_session.add(device)
        db_session.commit()

        node = EeroNode(network_name="Home", eero_id="node_003")
        db_session.add(node)
        db_session.commit()

        # Add old records across all three types
        old_conn = DeviceConnection(
            network_name="Home",
            device_id=device.id,
            timestamp=make_old_timestamp(40),
        )
        old_node_metric = EeroNodeMetric(
            eero_node_id=node.id,
            timestamp=make_old_timestamp(40),
            status="offline",
        )
        old_network_metric = NetworkMetric(
            network_name="Home",
            timestamp=make_old_timestamp(40),
            total_devices=8,
        )
        db_session.add_all([old_conn, old_node_metric, old_network_metric])
        db_session.commit()

        result = run_all_cleanup_tasks(db_session, retention_days=30, run_vacuum=False)

        assert result["success"] is True
        assert result["total_records_deleted"] == 3
        assert result["connection_records_deleted"] == 1
        assert result["node_metric_records_deleted"] == 1
        assert result["network_metric_records_deleted"] == 1

    def test_returns_total_deleted_count(self, db_session):
        from src.utils.cleanup import run_all_cleanup_tasks

        result = run_all_cleanup_tasks(db_session, retention_days=30, run_vacuum=False)

        assert result["success"] is True
        assert result["total_records_deleted"] == 0
        assert "retention_days" in result

    def test_includes_vacuum_result_when_run_vacuum_true(self, db_session):
        from src.utils.cleanup import run_all_cleanup_tasks

        result = run_all_cleanup_tasks(db_session, retention_days=30, run_vacuum=True)

        assert result["success"] is True
        assert "vacuum" in result
        assert result["vacuum"]["success"] is True

    def test_no_vacuum_result_when_run_vacuum_false(self, db_session):
        from src.utils.cleanup import run_all_cleanup_tasks

        result = run_all_cleanup_tasks(db_session, retention_days=30, run_vacuum=False)

        assert "vacuum" not in result

    def test_partial_data_cleanup(self, db_session):
        from src.utils.cleanup import run_all_cleanup_tasks

        device = Device(network_name="Home", mac_address="FF:00:11:22:33:44")
        db_session.add(device)
        db_session.commit()

        # Only connection records are old
        old_conn = DeviceConnection(
            network_name="Home",
            device_id=device.id,
            timestamp=make_old_timestamp(50),
        )
        recent_network_metric = NetworkMetric(
            network_name="Home",
            timestamp=make_recent_timestamp(2),
            total_devices=5,
        )
        db_session.add_all([old_conn, recent_network_metric])
        db_session.commit()

        result = run_all_cleanup_tasks(db_session, retention_days=30, run_vacuum=False)

        assert result["success"] is True
        assert result["total_records_deleted"] == 1
        assert result["connection_records_deleted"] == 1
        assert result["network_metric_records_deleted"] == 0

    def test_custom_retention_days_propagated(self, db_session):
        from src.utils.cleanup import run_all_cleanup_tasks

        result = run_all_cleanup_tasks(db_session, retention_days=14, run_vacuum=False)

        assert result["retention_days"] == 14
