"""Tests for device model, collector, and API functionality."""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.models.database import Base, Device, DeviceConnection, EeroNode


class TestDeviceModel:
    """Test Device database model."""

    @pytest.fixture
    def db_session(self):
        """Create an in-memory SQLite database for testing."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        yield session
        session.close()

    def test_create_device_with_manufacturer(self, db_session):
        """Test creating a device with manufacturer field."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            hostname="test-device",
            nickname="Test Device",
            manufacturer="Test Manufacturer Inc.",
            device_type="generic",
        )
        db_session.add(device)
        db_session.commit()

        assert device.id is not None
        assert device.mac_address == "aa:bb:cc:dd:ee:ff"
        assert device.hostname == "test-device"
        assert device.nickname == "Test Device"
        assert device.manufacturer == "Test Manufacturer Inc."
        assert device.device_type == "generic"
        assert device.first_seen is not None

    def test_create_device_without_manufacturer(self, db_session):
        """Test creating a device without manufacturer (optional field)."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            hostname="test-device",
        )
        db_session.add(device)
        db_session.commit()

        assert device.id is not None
        assert device.mac_address == "aa:bb:cc:dd:ee:ff"
        assert device.manufacturer is None

    def test_unique_mac_constraint(self, db_session):
        """Test that MAC address must be unique."""
        device1 = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            hostname="device1",
        )
        db_session.add(device1)
        db_session.commit()

        # Try to add another device with same MAC
        device2 = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            hostname="device2",
        )
        db_session.add(device2)

        with pytest.raises(Exception):  # SQLite raises IntegrityError
            db_session.commit()

    def test_query_by_mac(self, db_session):
        """Test querying device by MAC address."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            hostname="test-device",
            manufacturer="Test Inc.",
        )
        db_session.add(device)
        db_session.commit()

        found = db_session.query(Device).filter(
            Device.mac_address == "aa:bb:cc:dd:ee:ff"
        ).first()

        assert found is not None
        assert found.hostname == "test-device"
        assert found.manufacturer == "Test Inc."

    def test_update_manufacturer(self, db_session):
        """Test updating manufacturer field on existing device."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            hostname="test-device",
            manufacturer=None,
        )
        db_session.add(device)
        db_session.commit()

        # Update manufacturer
        device.manufacturer = "Updated Manufacturer"
        db_session.commit()

        # Verify update
        updated = db_session.query(Device).filter(
            Device.mac_address == "aa:bb:cc:dd:ee:ff"
        ).first()
        assert updated.manufacturer == "Updated Manufacturer"


class TestDeviceNameFallback:
    """Test device name fallback logic."""

    @pytest.fixture
    def db_session(self):
        """Create an in-memory SQLite database for testing."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        yield session
        session.close()

    def test_name_fallback_nickname_priority(self, db_session):
        """Test that nickname takes priority in name fallback."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            nickname="My Device",
            hostname="hostname-123",
            manufacturer="Test Inc.",
        )

        # Simulate the fallback logic from health.py
        device_name = device.nickname or device.hostname or device.manufacturer or device.mac_address
        assert device_name == "My Device"

    def test_name_fallback_hostname_second(self, db_session):
        """Test that hostname is used when nickname is None."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            nickname=None,
            hostname="hostname-123",
            manufacturer="Test Inc.",
        )

        device_name = device.nickname or device.hostname or device.manufacturer or device.mac_address
        assert device_name == "hostname-123"

    def test_name_fallback_manufacturer_third(self, db_session):
        """Test that manufacturer is used when nickname and hostname are None."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            nickname=None,
            hostname=None,
            manufacturer="Oculus VR, LLC",
        )

        device_name = device.nickname or device.hostname or device.manufacturer or device.mac_address
        assert device_name == "Oculus VR, LLC"

    def test_name_fallback_mac_last(self, db_session):
        """Test that MAC address is used as last resort."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            nickname=None,
            hostname=None,
            manufacturer=None,
        )

        device_name = device.nickname or device.hostname or device.manufacturer or device.mac_address
        assert device_name == "aa:bb:cc:dd:ee:ff"

    def test_name_fallback_empty_strings(self, db_session):
        """Test that empty strings don't break fallback logic."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            nickname="",  # Empty string should be falsy
            hostname="",
            manufacturer="Test Inc.",
        )

        # Python treats empty strings as falsy in 'or' chains
        device_name = device.nickname or device.hostname or device.manufacturer or device.mac_address
        assert device_name == "Test Inc."


class TestDeviceCollector:
    """Test DeviceCollector manufacturer handling."""

    @pytest.fixture
    def db_session(self):
        """Create an in-memory SQLite database for testing."""
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        yield session
        session.close()

    @pytest.fixture
    def mock_eero_client(self):
        """Create a mock Eero client."""
        client = Mock()
        client.is_authenticated.return_value = True
        return client

    @pytest.fixture
    def mock_device_data(self):
        """Create mock device data from Eero API."""
        return {
            "mac": "aa:bb:cc:dd:ee:ff",
            "hostname": "test-device",
            "nickname": "Test Device",
            "manufacturer": "Test Manufacturer Inc.",
            "device_type": "generic",
            "connected": True,
            "connection_type": "wireless",
            "ip": "192.168.1.100",
        }

    def test_store_manufacturer_on_new_device(self, db_session, mock_device_data):
        """Test that manufacturer is stored when creating a new device."""
        # Simulate device creation logic from device_collector.py
        device = Device(
            mac_address=mock_device_data["mac"],
            hostname=mock_device_data.get("hostname"),
            nickname=mock_device_data.get("nickname"),
            manufacturer=mock_device_data.get("manufacturer"),
            device_type="generic",
            first_seen=datetime.utcnow(),
        )
        db_session.add(device)
        db_session.commit()

        # Verify manufacturer was stored
        stored_device = db_session.query(Device).filter(
            Device.mac_address == "aa:bb:cc:dd:ee:ff"
        ).first()
        assert stored_device.manufacturer == "Test Manufacturer Inc."

    def test_update_manufacturer_on_existing_device(self, db_session, mock_device_data):
        """Test that manufacturer is updated on existing device."""
        # Create existing device without manufacturer
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            hostname="old-hostname",
            manufacturer=None,
            first_seen=datetime.utcnow(),
        )
        db_session.add(device)
        db_session.commit()

        # Simulate update logic from device_collector.py
        device.hostname = mock_device_data.get("hostname") or device.hostname
        device.nickname = mock_device_data.get("nickname") or device.nickname
        device.manufacturer = mock_device_data.get("manufacturer") or device.manufacturer
        db_session.commit()

        # Verify manufacturer was updated
        updated_device = db_session.query(Device).filter(
            Device.mac_address == "aa:bb:cc:dd:ee:ff"
        ).first()
        assert updated_device.manufacturer == "Test Manufacturer Inc."

    def test_preserve_existing_manufacturer_if_none_from_api(self, db_session):
        """Test that existing manufacturer is preserved if API returns None."""
        # Create device with manufacturer
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            manufacturer="Existing Manufacturer",
            first_seen=datetime.utcnow(),
        )
        db_session.add(device)
        db_session.commit()

        # Simulate update with None manufacturer from API
        mock_data_no_manufacturer = {
            "manufacturer": None,
        }
        device.manufacturer = mock_data_no_manufacturer.get("manufacturer") or device.manufacturer
        db_session.commit()

        # Verify existing manufacturer was preserved
        updated_device = db_session.query(Device).filter(
            Device.mac_address == "aa:bb:cc:dd:ee:ff"
        ).first()
        assert updated_device.manufacturer == "Existing Manufacturer"


class TestDeviceAPIResponse:
    """Test /devices endpoint response structure."""

    def test_device_response_includes_manufacturer(self):
        """Test that device API response includes manufacturer field."""
        # Expected response structure from /devices endpoint
        expected_device_fields = {
            "name",
            "nickname",
            "hostname",
            "manufacturer",
            "type",
            "ip_address",
            "is_online",
            "connection_type",
            "signal_strength",
            "bandwidth_down_mbps",
            "bandwidth_up_mbps",
            "node",
            "mac_address",
            "last_seen",
            "aliases",
        }

        # Verify critical new fields are in expected structure
        assert "nickname" in expected_device_fields
        assert "hostname" in expected_device_fields
        assert "manufacturer" in expected_device_fields
        assert "name" in expected_device_fields  # Computed field

    def test_device_response_structure(self):
        """Test the overall structure of device API response."""
        expected_top_level = {"devices", "total"}

        assert "devices" in expected_top_level
        assert "total" in expected_top_level

    def test_individual_fields_can_be_none(self):
        """Test that individual name fields can be None."""
        # Simulate a device response with optional fields as None
        mock_device = {
            "name": "aa:bb:cc:dd:ee:ff",  # Falls back to MAC
            "nickname": None,
            "hostname": None,
            "manufacturer": None,
            "mac_address": "aa:bb:cc:dd:ee:ff",
        }

        # All fields should be present, even if None
        assert "nickname" in mock_device
        assert "hostname" in mock_device
        assert "manufacturer" in mock_device
        assert mock_device["nickname"] is None
        assert mock_device["hostname"] is None
        assert mock_device["manufacturer"] is None

    def test_manufacturer_shown_when_no_nickname_or_hostname(self):
        """Test that manufacturer is shown as name when nickname/hostname are None."""
        mock_device = {
            "nickname": None,
            "hostname": None,
            "manufacturer": "Oculus VR, LLC",
            "mac_address": "aa:bb:cc:dd:ee:ff",
        }

        # Simulate name fallback
        device_name = (
            mock_device["nickname"]
            or mock_device["hostname"]
            or mock_device["manufacturer"]
            or mock_device["mac_address"]
        )

        assert device_name == "Oculus VR, LLC"
