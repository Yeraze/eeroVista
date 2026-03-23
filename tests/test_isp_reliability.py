"""Tests for ISP reliability service."""

import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, NetworkMetric
from src.services.isp_reliability_service import (
    detect_outages,
    get_uptime_stats,
)


class TestOutageDetection:
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

    def _add_reading(self, db_session, minutes_ago, status):
        ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        db_session.add(NetworkMetric(
            network_name="net",
            timestamp=ts,
            wan_status=status,
            total_devices=5,
            total_devices_online=5,
        ))

    def test_no_outages_all_connected(self, db_session):
        for i in range(10):
            self._add_reading(db_session, i * 5, "connected")
        db_session.commit()

        outages = detect_outages(db_session, "net", days=1)
        assert len(outages) == 0

    def test_detects_single_outage(self, db_session):
        # Connected, then offline, then connected
        self._add_reading(db_session, 30, "connected")
        self._add_reading(db_session, 25, "disconnected")
        self._add_reading(db_session, 20, "disconnected")
        self._add_reading(db_session, 15, "connected")
        self._add_reading(db_session, 10, "connected")
        db_session.commit()

        outages = detect_outages(db_session, "net", days=1)
        assert len(outages) == 1
        assert 5 <= outages[0]["duration_minutes"] <= 15

    def test_detects_multiple_outages(self, db_session):
        self._add_reading(db_session, 60, "connected")
        self._add_reading(db_session, 55, "disconnected")
        self._add_reading(db_session, 50, "connected")  # end outage 1
        self._add_reading(db_session, 30, "connected")
        self._add_reading(db_session, 25, "disconnected")
        self._add_reading(db_session, 20, "connected")  # end outage 2
        db_session.commit()

        outages = detect_outages(db_session, "net", days=1)
        assert len(outages) == 2

    def test_ongoing_outage(self, db_session):
        self._add_reading(db_session, 10, "connected")
        self._add_reading(db_session, 5, "disconnected")
        self._add_reading(db_session, 2, "disconnected")
        db_session.commit()

        outages = detect_outages(db_session, "net", days=1)
        assert len(outages) == 1
        assert outages[0].get("ongoing") is True
        assert outages[0]["end"] is None

    def test_no_data_returns_empty(self, db_session):
        outages = detect_outages(db_session, "net", days=1)
        assert outages == []


class TestUptimeStats:
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

    def test_all_connected_100_pct(self, db_session):
        now = datetime.now(timezone.utc)
        for i in range(20):
            db_session.add(NetworkMetric(
                network_name="net",
                timestamp=now - timedelta(minutes=i * 5),
                wan_status="connected",
                total_devices=5,
                total_devices_online=5,
            ))
        db_session.commit()

        stats = get_uptime_stats(db_session, "net")
        assert stats["uptime_24h_pct"] == 100.0
        assert stats["total_outages_30d"] == 0

    def test_half_offline_50_pct(self, db_session):
        now = datetime.now(timezone.utc)
        for i in range(10):
            db_session.add(NetworkMetric(
                network_name="net",
                timestamp=now - timedelta(minutes=i * 5),
                wan_status="connected" if i < 5 else "disconnected",
                total_devices=5,
                total_devices_online=5,
            ))
        db_session.commit()

        stats = get_uptime_stats(db_session, "net")
        assert stats["uptime_24h_pct"] == 50.0

    def test_no_data_returns_none(self, db_session):
        stats = get_uptime_stats(db_session, "net")
        assert stats["uptime_24h_pct"] is None
        assert stats["total_outages_30d"] == 0

    def test_stats_structure(self, db_session):
        stats = get_uptime_stats(db_session, "net")
        assert "uptime_24h_pct" in stats
        assert "uptime_7d_pct" in stats
        assert "uptime_30d_pct" in stats
        assert "total_outages_30d" in stats
        assert "total_downtime_minutes_30d" in stats
        assert "longest_outage_minutes" in stats
