"""Tests for bandwidth accumulation logic."""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.collectors.device_collector import DeviceCollector
from src.models.database import Base, DailyBandwidth, Device


@pytest.fixture
def db_session():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def mock_eero_client():
    """Create a mock Eero client."""
    mock_client = MagicMock()
    mock_client.get_profiles.return_value = []
    return mock_client


@pytest.fixture
def device_collector(db_session, mock_eero_client):
    """Create a DeviceCollector instance for testing."""
    # BaseCollector.__init__ expects (db, eero_client)
    return DeviceCollector(db_session, mock_eero_client)


class TestBandwidthAccumulation:
    """Tests for bandwidth accumulation calculations."""

    def test_bandwidth_calculation_correct_formula(self, device_collector, db_session):
        """Test that bandwidth is calculated correctly: (Mbps * seconds) / 8 = MB."""
        today = date.today()

        # First collection - no previous time, should just store the rate
        timestamp1 = datetime.utcnow()
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=10.0,  # 10 Mbps
            bandwidth_up_mbps=5.0,  # 5 Mbps
            timestamp=timestamp1,
        )

        record = (
            db_session.query(DailyBandwidth)
            .filter(DailyBandwidth.device_id == None, DailyBandwidth.date == today)
            .first()
        )

        assert record is not None
        assert record.download_mb == 0.0  # No accumulation yet
        assert record.upload_mb == 0.0  # No accumulation yet
        assert record.last_collection_time == timestamp1

        # Second collection 30 seconds later
        timestamp2 = timestamp1 + timedelta(seconds=30)
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=10.0,  # 10 Mbps
            bandwidth_up_mbps=5.0,  # 5 Mbps
            timestamp=timestamp2,
        )

        db_session.refresh(record)

        # Expected: (10 Mbps * 30 seconds) / 8 = 37.5 MB download
        # Expected: (5 Mbps * 30 seconds) / 8 = 18.75 MB upload
        assert record.download_mb == pytest.approx(37.5)
        assert record.upload_mb == pytest.approx(18.75)
        assert record.last_collection_time == timestamp2

    def test_skip_accumulation_when_bandwidth_is_none(self, device_collector, db_session):
        """Test that accumulation is skipped when bandwidth values are None."""
        today = date.today()
        timestamp = datetime.utcnow()

        # Call with None values
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=None,
            bandwidth_up_mbps=5.0,
            timestamp=timestamp,
        )

        # Should not create a record
        record = (
            db_session.query(DailyBandwidth)
            .filter(DailyBandwidth.device_id == None, DailyBandwidth.date == today)
            .first()
        )
        assert record is None

        # Call with both None
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=None,
            bandwidth_up_mbps=None,
            timestamp=timestamp,
        )

        record = (
            db_session.query(DailyBandwidth)
            .filter(DailyBandwidth.device_id == None, DailyBandwidth.date == today)
            .first()
        )
        assert record is None

    def test_handle_zero_bandwidth(self, device_collector, db_session):
        """Test that zero bandwidth values are handled correctly."""
        today = date.today()
        timestamp1 = datetime.utcnow()

        # First collection with zero bandwidth
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=0.0,
            bandwidth_up_mbps=0.0,
            timestamp=timestamp1,
        )

        record = (
            db_session.query(DailyBandwidth)
            .filter(DailyBandwidth.device_id == None, DailyBandwidth.date == today)
            .first()
        )

        assert record is not None
        assert record.download_mb == 0.0
        assert record.upload_mb == 0.0

        # Second collection 30 seconds later with zero bandwidth
        timestamp2 = timestamp1 + timedelta(seconds=30)
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=0.0,
            bandwidth_up_mbps=0.0,
            timestamp=timestamp2,
        )

        db_session.refresh(record)

        # Should still accumulate 0 MB
        assert record.download_mb == 0.0
        assert record.upload_mb == 0.0

    def test_daily_rollover(self, device_collector, db_session):
        """Test that new records are created for new days."""
        # Create record for today
        today = date.today()
        timestamp_today = datetime.combine(today, datetime.min.time())

        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=10.0,
            bandwidth_up_mbps=5.0,
            timestamp=timestamp_today,
        )

        # Simulate next day
        tomorrow = today + timedelta(days=1)
        with patch("src.collectors.device_collector.date") as mock_date:
            mock_date.today.return_value = tomorrow
            timestamp_tomorrow = datetime.combine(tomorrow, datetime.min.time())

            device_collector._update_bandwidth_accumulation(
                device_id=None,
                bandwidth_down_mbps=10.0,
                bandwidth_up_mbps=5.0,
                timestamp=timestamp_tomorrow,
            )

        # Should have two separate records
        records = db_session.query(DailyBandwidth).filter(
            DailyBandwidth.device_id == None
        ).all()
        assert len(records) == 2
        assert records[0].date == today
        assert records[1].date == tomorrow

    def test_per_device_tracking(self, device_collector, db_session):
        """Test that per-device bandwidth is tracked separately from network-wide."""
        # Create a device
        device = Device(
            mac_address="00:11:22:33:44:55",
            hostname="Test Device",
        )
        db_session.add(device)
        db_session.commit()

        today = date.today()
        timestamp1 = datetime.utcnow()

        # Track device bandwidth
        device_collector._update_bandwidth_accumulation(
            device_id=device.id,
            bandwidth_down_mbps=10.0,
            bandwidth_up_mbps=5.0,
            timestamp=timestamp1,
        )

        # Track network-wide bandwidth
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=20.0,
            bandwidth_up_mbps=10.0,
            timestamp=timestamp1,
        )

        # Should have two separate records
        device_record = (
            db_session.query(DailyBandwidth)
            .filter(
                DailyBandwidth.device_id == device.id, DailyBandwidth.date == today
            )
            .first()
        )
        network_record = (
            db_session.query(DailyBandwidth)
            .filter(DailyBandwidth.device_id == None, DailyBandwidth.date == today)
            .first()
        )

        assert device_record is not None
        assert network_record is not None
        assert device_record.id != network_record.id

    def test_multiple_accumulations_same_day(self, device_collector, db_session):
        """Test that multiple accumulations on the same day are added together."""
        today = date.today()
        base_time = datetime.utcnow()

        # First accumulation
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=10.0,
            bandwidth_up_mbps=5.0,
            timestamp=base_time,
        )

        # Second accumulation 30 seconds later
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=10.0,
            bandwidth_up_mbps=5.0,
            timestamp=base_time + timedelta(seconds=30),
        )

        # Third accumulation 30 seconds after that
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=10.0,
            bandwidth_up_mbps=5.0,
            timestamp=base_time + timedelta(seconds=60),
        )

        record = (
            db_session.query(DailyBandwidth)
            .filter(DailyBandwidth.device_id == None, DailyBandwidth.date == today)
            .first()
        )

        # Should have accumulated 2 intervals worth of data
        # (10 Mbps * 30 sec / 8) + (10 Mbps * 30 sec / 8) = 37.5 + 37.5 = 75 MB
        assert record.download_mb == pytest.approx(75.0)
        assert record.upload_mb == pytest.approx(37.5)

    def test_unique_constraint_prevents_duplicates(self, db_session):
        """Test that UniqueConstraint prevents duplicate device+date records."""
        from sqlalchemy.exc import IntegrityError

        today = date.today()

        # Create first record
        record1 = DailyBandwidth(
            device_id=None,
            date=today,
            download_mb=10.0,
            upload_mb=5.0,
        )
        db_session.add(record1)
        db_session.commit()

        # Try to create duplicate - should raise IntegrityError
        record2 = DailyBandwidth(
            device_id=None,
            date=today,
            download_mb=20.0,
            upload_mb=10.0,
        )
        db_session.add(record2)

        with pytest.raises(IntegrityError):
            db_session.flush()  # flush() triggers the constraint check

    def test_varying_bandwidth_rates(self, device_collector, db_session):
        """Test accumulation with varying bandwidth rates over time."""
        today = date.today()
        base_time = datetime.utcnow()

        # Start with high bandwidth
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=100.0,
            bandwidth_up_mbps=50.0,
            timestamp=base_time,
        )

        # Drop to medium after 30 seconds
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=50.0,
            bandwidth_up_mbps=25.0,
            timestamp=base_time + timedelta(seconds=30),
        )

        # Drop to low after another 30 seconds
        device_collector._update_bandwidth_accumulation(
            device_id=None,
            bandwidth_down_mbps=10.0,
            bandwidth_up_mbps=5.0,
            timestamp=base_time + timedelta(seconds=60),
        )

        record = (
            db_session.query(DailyBandwidth)
            .filter(DailyBandwidth.device_id == None, DailyBandwidth.date == today)
            .first()
        )

        # First interval: (100 * 30 / 8) = 375 MB
        # Second interval: (50 * 30 / 8) = 187.5 MB
        # Total: 562.5 MB
        assert record.download_mb == pytest.approx(562.5)
        assert record.upload_mb == pytest.approx(281.25)
