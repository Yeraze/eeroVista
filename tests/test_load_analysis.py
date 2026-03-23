"""Tests for node load balancing analysis service."""

import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, Device, DeviceConnection, EeroNode, EeroNodeMetric
from src.services.load_analysis_service import get_load_analysis


class TestLoadAnalysis:
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
    def nodes(self, db_session):
        n1 = EeroNode(network_name="net", eero_id="n1", location="Living Room", is_gateway=True)
        n2 = EeroNode(network_name="net", eero_id="n2", location="Office")
        db_session.add_all([n1, n2])
        db_session.commit()
        return n1, n2

    def test_no_nodes_returns_empty(self, db_session):
        result = get_load_analysis(db_session, "net")
        assert result["imbalance_score"] == 0
        assert result["nodes"] == []

    def test_balanced_load(self, db_session, nodes):
        n1, n2 = nodes
        now = datetime.now(timezone.utc)

        # Both nodes with equal device counts
        for i in range(5):
            db_session.add(EeroNodeMetric(
                eero_node_id=n1.id,
                timestamp=now - timedelta(minutes=i * 10),
                status="online",
                connected_device_count=5,
            ))
            db_session.add(EeroNodeMetric(
                eero_node_id=n2.id,
                timestamp=now - timedelta(minutes=i * 10),
                status="online",
                connected_device_count=5,
            ))
        db_session.commit()

        result = get_load_analysis(db_session, "net")
        assert result["imbalance_score"] == 0  # Perfectly balanced
        assert len(result["nodes"]) == 2
        assert result["nodes"][0]["avg_devices"] == 5.0

    def test_imbalanced_load(self, db_session, nodes):
        n1, n2 = nodes
        now = datetime.now(timezone.utc)

        for i in range(5):
            db_session.add(EeroNodeMetric(
                eero_node_id=n1.id,
                timestamp=now - timedelta(minutes=i * 10),
                status="online",
                connected_device_count=15,
            ))
            db_session.add(EeroNodeMetric(
                eero_node_id=n2.id,
                timestamp=now - timedelta(minutes=i * 10),
                status="online",
                connected_device_count=1,
            ))
        db_session.commit()

        result = get_load_analysis(db_session, "net")
        assert result["imbalance_score"] > 0.5  # High imbalance

    def test_roaming_detection(self, db_session, nodes):
        n1, n2 = nodes
        now = datetime.now(timezone.utc)

        device = Device(mac_address="aa:bb:cc:dd:ee:ff", network_name="net", hostname="Laptop")
        db_session.add(device)
        db_session.commit()

        # Device moves from n1 to n2
        db_session.add(DeviceConnection(
            network_name="net", device_id=device.id, eero_node_id=n1.id,
            timestamp=now - timedelta(minutes=30), is_connected=True,
        ))
        db_session.add(DeviceConnection(
            network_name="net", device_id=device.id, eero_node_id=n2.id,
            timestamp=now - timedelta(minutes=20), is_connected=True,
        ))
        db_session.commit()

        result = get_load_analysis(db_session, "net")
        assert result["roaming_summary"]["total_events"] == 1
        assert result["roaming_events"][0]["from_node"] == "Living Room"
        assert result["roaming_events"][0]["to_node"] == "Office"

    def test_no_roaming_same_node(self, db_session, nodes):
        n1, _ = nodes
        now = datetime.now(timezone.utc)

        device = Device(mac_address="aa:bb:cc:dd:ee:ff", network_name="net", hostname="Static")
        db_session.add(device)
        db_session.commit()

        for i in range(3):
            db_session.add(DeviceConnection(
                network_name="net", device_id=device.id, eero_node_id=n1.id,
                timestamp=now - timedelta(minutes=i * 10), is_connected=True,
            ))
        db_session.commit()

        result = get_load_analysis(db_session, "net")
        assert result["roaming_summary"]["total_events"] == 0

    def test_structure(self, db_session, nodes):
        result = get_load_analysis(db_session, "net")
        assert "imbalance_score" in result
        assert "nodes" in result
        assert "roaming_events" in result
        assert "roaming_summary" in result
