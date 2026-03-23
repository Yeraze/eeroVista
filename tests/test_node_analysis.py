"""Tests for node analysis service (restart detection)."""

import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, EeroNode, EeroNodeMetric
from src.services.node_analysis_service import (
    detect_restarts,
    get_all_nodes_restart_counts,
    get_node_restart_summary,
)


class TestNodeRestartDetection:
    """Test restart detection logic."""

    @pytest.fixture
    def db_session(self):
        """Create an in-memory SQLite database for testing."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        yield session
        session.close()

    @pytest.fixture
    def node(self, db_session):
        """Create a test node."""
        node = EeroNode(
            network_name="test-network",
            eero_id="node-001",
            location="Living Room",
            model="eero Pro 6E",
            is_gateway=True,
        )
        db_session.add(node)
        db_session.commit()
        return node

    def _add_metric(self, db_session, node, minutes_ago, uptime_seconds):
        """Helper to add a metric at a given time offset."""
        ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        metric = EeroNodeMetric(
            eero_node_id=node.id,
            timestamp=ts,
            status="online",
            uptime_seconds=uptime_seconds,
        )
        db_session.add(metric)
        db_session.commit()
        return metric

    def test_no_restarts_when_uptime_increases(self, db_session, node):
        """No restarts detected when uptime monotonically increases."""
        self._add_metric(db_session, node, 30, 1000)
        self._add_metric(db_session, node, 20, 1600)
        self._add_metric(db_session, node, 10, 2200)

        restarts = detect_restarts(db_session, node.id, days=1)
        assert len(restarts) == 0

    def test_detects_single_restart(self, db_session, node):
        """Detects a restart when uptime drops."""
        self._add_metric(db_session, node, 30, 86400)  # 1 day uptime
        self._add_metric(db_session, node, 20, 86400 + 600)
        self._add_metric(db_session, node, 10, 120)  # Restarted, only 2 min uptime

        restarts = detect_restarts(db_session, node.id, days=1)
        assert len(restarts) == 1
        assert restarts[0]["previous_uptime_seconds"] == 86400 + 600

    def test_detects_multiple_restarts(self, db_session, node):
        """Detects multiple restarts."""
        self._add_metric(db_session, node, 60, 50000)
        self._add_metric(db_session, node, 50, 100)   # restart 1
        self._add_metric(db_session, node, 40, 700)
        self._add_metric(db_session, node, 30, 60)    # restart 2
        self._add_metric(db_session, node, 20, 660)

        restarts = detect_restarts(db_session, node.id, days=1)
        assert len(restarts) == 2

    def test_no_metrics_returns_empty(self, db_session, node):
        """No metrics returns empty list."""
        restarts = detect_restarts(db_session, node.id, days=1)
        assert restarts == []

    def test_single_metric_returns_empty(self, db_session, node):
        """Single metric can't detect restarts."""
        self._add_metric(db_session, node, 10, 500)
        restarts = detect_restarts(db_session, node.id, days=1)
        assert restarts == []

    def test_respects_days_filter(self, db_session, node):
        """Only looks at metrics within the specified day range."""
        # Old restart (40 days ago) - should be excluded with days=30
        old_ts = datetime.now(timezone.utc) - timedelta(days=40)
        m1 = EeroNodeMetric(
            eero_node_id=node.id,
            timestamp=old_ts,
            status="online",
            uptime_seconds=50000,
        )
        m2 = EeroNodeMetric(
            eero_node_id=node.id,
            timestamp=old_ts + timedelta(minutes=10),
            status="online",
            uptime_seconds=100,
        )
        db_session.add_all([m1, m2])
        db_session.commit()

        restarts = detect_restarts(db_session, node.id, days=30)
        assert len(restarts) == 0

        # But should show with days=60
        restarts = detect_restarts(db_session, node.id, days=60)
        assert len(restarts) == 1

    def test_ignores_null_uptime(self, db_session, node):
        """Metrics with null uptime are filtered out."""
        self._add_metric(db_session, node, 30, 1000)
        # Add metric with null uptime
        ts = datetime.now(timezone.utc) - timedelta(minutes=20)
        metric = EeroNodeMetric(
            eero_node_id=node.id,
            timestamp=ts,
            status="online",
            uptime_seconds=None,
        )
        db_session.add(metric)
        db_session.commit()
        self._add_metric(db_session, node, 10, 1600)

        restarts = detect_restarts(db_session, node.id, days=1)
        assert len(restarts) == 0


class TestNodeRestartSummary:
    """Test restart summary generation."""

    @pytest.fixture
    def db_session(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        yield session
        session.close()

    @pytest.fixture
    def node(self, db_session):
        node = EeroNode(
            network_name="test-network",
            eero_id="node-001",
            location="Living Room",
            model="eero Pro 6E",
        )
        db_session.add(node)
        db_session.commit()
        return node

    def test_summary_no_restarts(self, db_session, node):
        summary = get_node_restart_summary(db_session, node.id, "Living Room", days=30)
        assert summary["total_restarts"] == 0
        assert summary["mean_time_between_restarts_hours"] is None
        assert summary["node_name"] == "Living Room"
        assert summary["period_days"] == 30

    def test_summary_with_restarts_computes_mtbr(self, db_session, node):
        """MTBR is computed when there are 2+ restarts."""
        now = datetime.now(timezone.utc)
        # Three restart events spread 10 hours apart
        for i, (mins, uptime) in enumerate([
            (600, 50000), (590, 100),    # restart 1 at ~590 min ago
            (300, 17400), (290, 100),    # restart 2 at ~290 min ago
            (10, 16800),                 # stable since
        ]):
            ts = now - timedelta(minutes=mins)
            m = EeroNodeMetric(
                eero_node_id=node.id,
                timestamp=ts,
                status="online",
                uptime_seconds=uptime,
            )
            db_session.add(m)
        db_session.commit()

        summary = get_node_restart_summary(db_session, node.id, "Living Room", days=30)
        assert summary["total_restarts"] == 2
        assert summary["mean_time_between_restarts_hours"] is not None
        assert summary["mean_time_between_restarts_hours"] > 0


class TestAllNodesRestartCounts:
    """Test restart counts across all nodes."""

    @pytest.fixture
    def db_session(self):
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        yield session
        session.close()

    def test_counts_across_multiple_nodes(self, db_session):
        """Get restart counts for multiple nodes."""
        now = datetime.now(timezone.utc)

        node1 = EeroNode(network_name="net", eero_id="n1", location="Room 1")
        node2 = EeroNode(network_name="net", eero_id="n2", location="Room 2")
        db_session.add_all([node1, node2])
        db_session.commit()

        # Node 1: one restart
        for mins, uptime in [(30, 5000), (20, 100), (10, 700)]:
            db_session.add(EeroNodeMetric(
                eero_node_id=node1.id,
                timestamp=now - timedelta(minutes=mins),
                status="online", uptime_seconds=uptime,
            ))

        # Node 2: no restarts
        for mins, uptime in [(30, 1000), (20, 1600), (10, 2200)]:
            db_session.add(EeroNodeMetric(
                eero_node_id=node2.id,
                timestamp=now - timedelta(minutes=mins),
                status="online", uptime_seconds=uptime,
            ))

        db_session.commit()

        counts = get_all_nodes_restart_counts(db_session, "net", days=1)
        assert counts[node1.id] == 1
        assert counts[node2.id] == 0
