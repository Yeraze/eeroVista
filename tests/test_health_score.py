"""Tests for network health score service."""

import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import (
    Base, DeviceConnection, Device, EeroNode, EeroNodeMetric, NetworkMetric,
)
from src.services.health_score_service import (
    _signal_to_score,
    compute_health_score,
)


class TestSignalToScore:
    def test_excellent_signal(self):
        assert _signal_to_score(-25) == 100.0

    def test_worst_signal(self):
        assert _signal_to_score(-95) == 0.0

    def test_mid_signal(self):
        score = _signal_to_score(-60)
        assert 40 < score < 60

    def test_boundary_best(self):
        assert _signal_to_score(-30) == 100.0

    def test_boundary_worst(self):
        assert _signal_to_score(-90) == 0.0


class TestHealthScore:
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

    def test_empty_db_returns_perfect_score(self, db_session):
        """With no data, defaults to 100 (no evidence of problems)."""
        result = compute_health_score(db_session, "net")
        assert result["score"] == 100.0
        assert result["color"] == "green"

    def test_all_online_high_score(self, db_session):
        now = datetime.now(timezone.utc)

        # Add network metrics - all connected
        for i in range(5):
            db_session.add(NetworkMetric(
                network_name="net",
                timestamp=now - timedelta(minutes=i * 10),
                wan_status="connected",
                total_devices=5,
                total_devices_online=5,
            ))

        # Add a node
        node = EeroNode(network_name="net", eero_id="n1", location="Room")
        db_session.add(node)
        db_session.commit()

        # Node metrics - online with good mesh
        for i in range(3):
            db_session.add(EeroNodeMetric(
                eero_node_id=node.id,
                timestamp=now - timedelta(minutes=i * 10),
                status="online",
                mesh_quality_bars=5,
            ))

        # Device with good signal
        device = Device(mac_address="aa:bb:cc:dd:ee:ff", network_name="net", hostname="test")
        db_session.add(device)
        db_session.commit()

        db_session.add(DeviceConnection(
            network_name="net",
            device_id=device.id,
            eero_node_id=node.id,
            timestamp=now - timedelta(minutes=5),
            is_connected=True,
            signal_strength=-40,
        ))
        db_session.commit()

        result = compute_health_score(db_session, "net")
        assert result["score"] >= 90
        assert result["color"] == "green"

    def test_wan_offline_lowers_score(self, db_session):
        now = datetime.now(timezone.utc)

        # Half connected, half disconnected
        for i in range(10):
            db_session.add(NetworkMetric(
                network_name="net",
                timestamp=now - timedelta(minutes=i * 5),
                wan_status="connected" if i < 5 else "disconnected",
                total_devices=5,
                total_devices_online=5,
            ))
        db_session.commit()

        result = compute_health_score(db_session, "net")
        # WAN score should be 50%, weighted at 30% = 15 points reduction
        assert result["score"] < 100
        assert result["components"]["wan_uptime"]["score"] == 50.0

    def test_node_offline_lowers_score(self, db_session):
        now = datetime.now(timezone.utc)

        node1 = EeroNode(network_name="net", eero_id="n1", location="Room 1")
        node2 = EeroNode(network_name="net", eero_id="n2", location="Room 2")
        db_session.add_all([node1, node2])
        db_session.commit()

        # Node1 online, Node2 offline
        db_session.add(EeroNodeMetric(
            eero_node_id=node1.id,
            timestamp=now - timedelta(minutes=5),
            status="online",
        ))
        db_session.add(EeroNodeMetric(
            eero_node_id=node2.id,
            timestamp=now - timedelta(minutes=5),
            status="offline",
        ))
        db_session.commit()

        result = compute_health_score(db_session, "net")
        assert result["components"]["node_availability"]["score"] == 50.0

    def test_score_has_correct_structure(self, db_session):
        result = compute_health_score(db_session, "net")
        assert "score" in result
        assert "color" in result
        assert "components" in result
        assert "wan_uptime" in result["components"]
        assert "node_availability" in result["components"]
        assert "mesh_quality" in result["components"]
        assert "signal_quality" in result["components"]
        for comp in result["components"].values():
            assert "score" in comp
            assert "weight" in comp
