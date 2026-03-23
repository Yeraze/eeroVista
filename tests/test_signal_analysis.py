"""Tests for signal quality analysis service."""

import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, Device, DeviceConnection, EeroNode
from src.services.signal_analysis_service import (
    _classify_signal,
    get_signal_history,
    get_signal_summary,
)


class TestClassifySignal:
    def test_excellent(self):
        assert _classify_signal(-40) == "excellent"

    def test_good(self):
        assert _classify_signal(-55) == "good"

    def test_fair(self):
        assert _classify_signal(-70) == "fair"

    def test_poor(self):
        assert _classify_signal(-80) == "poor"

    def test_boundary_excellent(self):
        assert _classify_signal(-50) == "excellent"

    def test_boundary_good(self):
        assert _classify_signal(-65) == "good"


class TestSignalHistory:
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
            hostname="TestPhone",
        )
        db_session.add(device)
        db_session.commit()
        return device, node

    def test_no_data_returns_empty(self, db_session, setup):
        result = get_signal_history(db_session, "aa:bb:cc:dd:ee:ff", "net", hours=24)
        assert result["history"] == []
        assert result["stats"] is None
        assert result["trend"] == "unknown"

    def test_device_not_found(self, db_session):
        result = get_signal_history(db_session, "ff:ff:ff:ff:ff:ff", "net", hours=24)
        assert "error" in result

    def test_with_data_returns_stats(self, db_session, setup):
        device, node = setup
        now = datetime.now(timezone.utc)

        for i in range(10):
            db_session.add(DeviceConnection(
                network_name="net",
                device_id=device.id,
                eero_node_id=node.id,
                timestamp=now - timedelta(hours=i),
                is_connected=True,
                signal_strength=-50 - i,
            ))
        db_session.commit()

        result = get_signal_history(db_session, "aa:bb:cc:dd:ee:ff", "net", hours=24)
        assert result["stats"] is not None
        assert result["stats"]["count"] == 10
        assert result["stats"]["min"] == -59
        assert result["stats"]["max"] == -50
        assert len(result["history"]) == 10
        assert result["quality_band"] in ("excellent", "good", "fair", "poor")

    def test_trend_detection_degrading(self, db_session, setup):
        device, node = setup
        now = datetime.now(timezone.utc)

        # Good signal 48-24h ago
        for i in range(5):
            db_session.add(DeviceConnection(
                network_name="net",
                device_id=device.id,
                eero_node_id=node.id,
                timestamp=now - timedelta(hours=48) + timedelta(hours=i),
                is_connected=True,
                signal_strength=-40,
            ))

        # Bad signal in last 24h
        for i in range(5):
            db_session.add(DeviceConnection(
                network_name="net",
                device_id=device.id,
                eero_node_id=node.id,
                timestamp=now - timedelta(hours=i + 1),
                is_connected=True,
                signal_strength=-60,
            ))
        db_session.commit()

        result = get_signal_history(db_session, "aa:bb:cc:dd:ee:ff", "net", hours=72)
        assert result["trend"] == "degrading"


class TestSignalSummary:
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

    def test_summary_structure(self, db_session):
        result = get_signal_summary(db_session, "net")
        assert "band_counts" in result
        assert "degrading_devices" in result
        assert "total_wireless_devices" in result
        assert result["band_counts"] == {"excellent": 0, "good": 0, "fair": 0, "poor": 0}
