"""Tests for device activity pattern service."""

import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, Device, DeviceConnection, EeroNode
from src.services.activity_pattern_service import get_activity_pattern


class TestActivityPattern:
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
    def setup(self, db_session):
        node = EeroNode(network_name="net", eero_id="n1", location="Room")
        db_session.add(node)
        db_session.commit()

        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="net",
            hostname="TestDevice",
        )
        db_session.add(device)
        db_session.commit()
        return device, node

    def test_device_not_found(self, db_session):
        result = get_activity_pattern(db_session, "ff:ff:ff:ff:ff:ff", "net")
        assert "error" in result

    def test_no_data_returns_empty_heatmap(self, db_session, setup):
        result = get_activity_pattern(db_session, "aa:bb:cc:dd:ee:ff", "net")
        assert result["total_readings"] == 0
        assert len(result["heatmap"]) == 7
        for row in result["heatmap"]:
            assert len(row["hours"]) == 24
            assert all(h is None for h in row["hours"])

    def test_with_data_returns_probabilities(self, db_session, setup):
        device, node = setup
        now = datetime.now(timezone.utc)

        # Add some readings - all connected
        for i in range(5):
            db_session.add(DeviceConnection(
                network_name="net",
                device_id=device.id,
                eero_node_id=node.id,
                timestamp=now - timedelta(hours=i),
                is_connected=True,
            ))
        db_session.commit()

        result = get_activity_pattern(db_session, "aa:bb:cc:dd:ee:ff", "net")
        assert result["total_readings"] == 5
        # At least some non-None values in the heatmap
        all_values = []
        for row in result["heatmap"]:
            all_values.extend(v for v in row["hours"] if v is not None)
        assert len(all_values) > 0
        # All connected readings → probability should be 1.0
        assert all(v == 1.0 for v in all_values)

    def test_relative_activity_levels(self, db_session, setup):
        """Hours with more connected readings show higher values."""
        device, node = setup
        now = datetime.now(timezone.utc)

        # Hour A: 4 connected readings (peak)
        hour_a = now.replace(hour=10, minute=0, second=0, microsecond=0)
        for i in range(4):
            db_session.add(DeviceConnection(
                network_name="net",
                device_id=device.id,
                eero_node_id=node.id,
                timestamp=hour_a + timedelta(minutes=i),
                is_connected=True,
            ))

        # Hour B: 1 connected reading (low activity)
        hour_b = now.replace(hour=3, minute=0, second=0, microsecond=0)
        db_session.add(DeviceConnection(
            network_name="net",
            device_id=device.id,
            eero_node_id=node.id,
            timestamp=hour_b,
            is_connected=True,
        ))
        db_session.commit()

        result = get_activity_pattern(db_session, "aa:bb:cc:dd:ee:ff", "net")
        dow = hour_a.weekday()
        prob_a = result["heatmap"][dow]["hours"][10]
        prob_b = result["heatmap"][dow]["hours"][3]
        # Peak hour should be 1.0, low hour should be less
        assert prob_a == 1.0
        assert prob_b == 0.25

    def test_heatmap_structure(self, db_session, setup):
        result = get_activity_pattern(db_session, "aa:bb:cc:dd:ee:ff", "net")
        assert result["heatmap"][0]["day"] == "Monday"
        assert result["heatmap"][6]["day"] == "Sunday"
