"""Tests for bandwidth summary report service."""

import pytest
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, DailyBandwidth, Device
from src.services.bandwidth_report_service import (
    _get_period_range,
    _mb_to_gb,
    get_bandwidth_summary,
)


class TestPeriodRange:
    """Test period date calculations."""

    def test_week_offset_0_starts_monday(self):
        start, end, label = _get_period_range("week", 0)
        assert start.weekday() == 0  # Monday
        assert end.weekday() == 6  # Sunday
        assert (end - start).days == 6

    def test_week_offset_1_is_previous_week(self):
        start_current, _, _ = _get_period_range("week", 0)
        start_prev, end_prev, _ = _get_period_range("week", 1)
        assert start_prev == start_current - timedelta(weeks=1)

    def test_month_offset_0_is_current_month(self):
        today = date.today()
        start, end, label = _get_period_range("month", 0)
        assert start.year == today.year
        assert start.month == today.month
        assert start.day == 1

    def test_month_end_is_last_day(self):
        start, end, _ = _get_period_range("month", 0)
        # End should be last day of the month
        next_month_start = date(
            start.year + (1 if start.month == 12 else 0),
            1 if start.month == 12 else start.month + 1,
            1,
        )
        assert end == next_month_start - timedelta(days=1)

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            _get_period_range("day", 0)


class TestMbToGb:
    def test_conversion(self):
        assert _mb_to_gb(1024) == 1.0
        assert _mb_to_gb(512) == 0.5
        assert _mb_to_gb(0) == 0.0


class TestBandwidthSummary:
    """Test full bandwidth summary generation."""

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
    def devices(self, db_session):
        d1 = Device(
            mac_address="aa:bb:cc:dd:ee:01",
            network_name="net",
            hostname="Gaming-PC",
        )
        d2 = Device(
            mac_address="aa:bb:cc:dd:ee:02",
            network_name="net",
            hostname="iPhone",
        )
        db_session.add_all([d1, d2])
        db_session.commit()
        return d1, d2

    def _add_daily(self, db_session, device_id, day, down_mb, up_mb):
        db_session.add(DailyBandwidth(
            network_name="net",
            device_id=device_id,
            date=day,
            download_mb=down_mb,
            upload_mb=up_mb,
        ))

    def test_empty_data_returns_zeros(self, db_session):
        result = get_bandwidth_summary(db_session, "net", "week", 0)
        assert result["total_download_gb"] == 0
        assert result["total_upload_gb"] == 0
        assert result["top_devices"] == []
        assert result["daily_breakdown"] == []
        assert result["peak_day"] is None

    def test_summary_with_data(self, db_session, devices):
        d1, d2 = devices
        # Add data for current week
        start, end, _ = _get_period_range("week", 0)

        for i in range(min(3, (end - start).days + 1)):
            day = start + timedelta(days=i)
            self._add_daily(db_session, d1.id, day, 10240, 2048)  # 10GB down, 2GB up
            self._add_daily(db_session, d2.id, day, 5120, 1024)   # 5GB down, 1GB up

        db_session.commit()

        result = get_bandwidth_summary(db_session, "net", "week", 0)
        assert result["total_download_gb"] > 0
        assert result["total_upload_gb"] > 0
        assert len(result["top_devices"]) == 2
        assert len(result["daily_breakdown"]) >= 1
        # Gaming-PC should be top consumer
        assert result["top_devices"][0]["hostname"] == "Gaming-PC"

    def test_top_devices_have_percentages(self, db_session, devices):
        d1, d2 = devices
        start, _, _ = _get_period_range("week", 0)

        self._add_daily(db_session, d1.id, start, 7680, 1024)  # 7.5GB + 1GB
        self._add_daily(db_session, d2.id, start, 2560, 512)   # 2.5GB + 0.5GB
        db_session.commit()

        result = get_bandwidth_summary(db_session, "net", "week", 0)
        total_pct = sum(d["pct_of_total"] for d in result["top_devices"])
        assert abs(total_pct - 100.0) < 1.0  # Should sum to ~100%

    def test_period_comparison(self, db_session, devices):
        d1, _ = devices
        current_start, _, _ = _get_period_range("week", 0)
        prev_start, _, _ = _get_period_range("week", 1)

        # Previous week: 5GB
        self._add_daily(db_session, d1.id, prev_start, 5120, 0)
        # Current week: 10GB (100% increase)
        self._add_daily(db_session, d1.id, current_start, 10240, 0)
        db_session.commit()

        result = get_bandwidth_summary(db_session, "net", "week", 0)
        assert result["change_vs_previous"]["download_pct"] == 100.0

    def test_daily_breakdown_sorted(self, db_session, devices):
        d1, _ = devices
        start, _, _ = _get_period_range("week", 0)

        # Add in reverse order
        for i in range(min(3, 7)):
            day = start + timedelta(days=2 - i if i < 3 else i)
            self._add_daily(db_session, d1.id, start + timedelta(days=i), 1024, 512)
        db_session.commit()

        result = get_bandwidth_summary(db_session, "net", "week", 0)
        dates = [d["date"] for d in result["daily_breakdown"]]
        assert dates == sorted(dates)
