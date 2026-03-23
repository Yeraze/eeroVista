"""Tests for speedtest performance trends service."""

import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, Speedtest
from src.services.speedtest_analysis_service import get_speedtest_analysis


class TestSpeedtestAnalysis:
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

    def test_no_data_returns_defaults(self, db_session):
        result = get_speedtest_analysis(db_session, "net", days=30)
        assert result["test_count"] == 0
        assert result["avg_download_mbps"] is None
        assert result["time_of_day_pattern"] == []
        assert result["trend"] == "unknown"

    def test_with_data_returns_averages(self, db_session):
        now = datetime.now(timezone.utc)
        for i in range(10):
            db_session.add(Speedtest(
                network_name="net",
                timestamp=now - timedelta(days=i),
                download_mbps=300.0 + i,
                upload_mbps=30.0 + i,
                latency_ms=10.0 + i,
            ))
        db_session.commit()

        result = get_speedtest_analysis(db_session, "net", days=30)
        assert result["test_count"] == 10
        assert result["avg_download_mbps"] is not None
        assert 300 <= result["avg_download_mbps"] <= 310
        assert result["avg_upload_mbps"] is not None
        assert result["avg_latency_ms"] is not None

    def test_time_of_day_pattern(self, db_session):
        now = datetime.now(timezone.utc)
        # Add tests at different hours
        for hour in [8, 12, 20]:
            ts = now.replace(hour=hour, minute=0, second=0) - timedelta(days=1)
            db_session.add(Speedtest(
                network_name="net",
                timestamp=ts,
                download_mbps=300.0,
                upload_mbps=30.0,
            ))
        db_session.commit()

        result = get_speedtest_analysis(db_session, "net", days=7)
        assert len(result["time_of_day_pattern"]) >= 1

    def test_trend_stable(self, db_session):
        now = datetime.now(timezone.utc)
        for i in range(10):
            db_session.add(Speedtest(
                network_name="net",
                timestamp=now - timedelta(days=i),
                download_mbps=300.0,
                upload_mbps=30.0,
            ))
        db_session.commit()

        result = get_speedtest_analysis(db_session, "net", days=30)
        assert result["trend"] == "stable"

    def test_trend_degrading(self, db_session):
        now = datetime.now(timezone.utc)
        # First half: fast, second half: slow
        for i in range(10):
            speed = 400.0 if i >= 5 else 200.0  # older tests are faster
            db_session.add(Speedtest(
                network_name="net",
                timestamp=now - timedelta(days=i),
                download_mbps=speed,
                upload_mbps=30.0,
            ))
        db_session.commit()

        result = get_speedtest_analysis(db_session, "net", days=30)
        assert result["trend"] == "degrading"

    def test_respects_days_filter(self, db_session):
        now = datetime.now(timezone.utc)
        # Add test 60 days ago
        db_session.add(Speedtest(
            network_name="net",
            timestamp=now - timedelta(days=60),
            download_mbps=300.0,
            upload_mbps=30.0,
        ))
        # Add test 5 days ago
        db_session.add(Speedtest(
            network_name="net",
            timestamp=now - timedelta(days=5),
            download_mbps=300.0,
            upload_mbps=30.0,
        ))
        db_session.commit()

        result = get_speedtest_analysis(db_session, "net", days=30)
        assert result["test_count"] == 1  # Only the 5-day-old test

    def test_structure(self, db_session):
        result = get_speedtest_analysis(db_session, "net", days=30)
        assert "period_days" in result
        assert "test_count" in result
        assert "avg_download_mbps" in result
        assert "avg_upload_mbps" in result
        assert "avg_latency_ms" in result
        assert "time_of_day_pattern" in result
        assert "day_of_week_pattern" in result
        assert "trend" in result
