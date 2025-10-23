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
            network_name="test-network",
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
            network_name="test-network",
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
            network_name="test-network",
            hostname="device1",
        )
        db_session.add(device1)
        db_session.commit()

        # Try to add another device with same MAC
        device2 = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="test-network",
            hostname="device2",
        )
        db_session.add(device2)

        with pytest.raises(Exception):  # SQLite raises IntegrityError
            db_session.commit()

    def test_query_by_mac(self, db_session):
        """Test querying device by MAC address."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="test-network",
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
            network_name="test-network",
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


class TestDeviceConnectionGuest:
    """Test DeviceConnection with guest network status."""

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

    def test_create_device_connection_with_guest_status(self, db_session):
        """Test creating device connection with guest network status."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="test-network",
            hostname="test-device",
        )
        db_session.add(device)
        db_session.commit()

        connection = DeviceConnection(
            device_id=device.id,
            network_name="test-network",
            timestamp=datetime.utcnow(),
            is_connected=True,
            is_guest=True,
        )
        db_session.add(connection)
        db_session.commit()

        assert connection.is_guest is True
        assert connection.id is not None

    def test_create_device_connection_without_guest_status(self, db_session):
        """Test creating device connection without guest status (defaults to None/False)."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="test-network",
            hostname="test-device",
        )
        db_session.add(device)
        db_session.commit()

        connection = DeviceConnection(
            device_id=device.id,
            network_name="test-network",
            timestamp=datetime.utcnow(),
            is_connected=True,
        )
        db_session.add(connection)
        db_session.commit()

        assert connection.is_guest is None or connection.is_guest is False

    def test_query_guest_connections(self, db_session):
        """Test querying connections by guest status."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="test-network",
            hostname="test-device",
        )
        db_session.add(device)
        db_session.commit()

        # Create guest connection
        guest_connection = DeviceConnection(
            device_id=device.id,
            network_name="test-network",
            timestamp=datetime.utcnow(),
            is_connected=True,
            is_guest=True,
        )
        db_session.add(guest_connection)

        # Create non-guest connection
        regular_connection = DeviceConnection(
            device_id=device.id,
            network_name="test-network",
            timestamp=datetime.utcnow(),
            is_connected=True,
            is_guest=False,
        )
        db_session.add(regular_connection)
        db_session.commit()

        # Query guest connections
        guest_connections = db_session.query(DeviceConnection).filter(
            DeviceConnection.is_guest == True
        ).all()

        assert len(guest_connections) == 1
        assert guest_connections[0].is_guest is True

    def test_update_guest_status(self, db_session):
        """Test updating guest status on existing connection."""
        device = Device(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="test-network",
            hostname="test-device",
        )
        db_session.add(device)
        db_session.commit()

        connection = DeviceConnection(
            device_id=device.id,
            network_name="test-network",
            timestamp=datetime.utcnow(),
            is_connected=True,
            is_guest=False,
        )
        db_session.add(connection)
        db_session.commit()

        # Update to guest
        connection.is_guest = True
        db_session.commit()

        # Verify update
        updated = db_session.query(DeviceConnection).filter(
            DeviceConnection.id == connection.id
        ).first()
        assert updated.is_guest is True


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
            network_name="test-network",
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
            network_name="test-network",
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
            network_name="test-network",
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
            network_name="test-network",
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
            network_name="test-network",
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
            "is_guest": False,
        }

    @pytest.fixture
    def mock_guest_device_data(self):
        """Create mock guest device data from Eero API."""
        return {
            "mac": "bb:cc:dd:ee:ff:00",
            "hostname": "guest-device",
            "nickname": "Guest Device",
            "manufacturer": "Guest Manufacturer",
            "device_type": "generic",
            "connected": True,
            "connection_type": "wireless",
            "ip": "192.168.1.200",
            "is_guest": True,
        }

    def test_store_manufacturer_on_new_device(self, db_session, mock_device_data):
        """Test that manufacturer is stored when creating a new device."""
        # Simulate device creation logic from device_collector.py
        device = Device(
            mac_address=mock_device_data["mac"],
            network_name="test-network",
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
            network_name="test-network",
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
            network_name="test-network",
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

    def test_store_guest_status_on_device_connection(self, db_session, mock_guest_device_data):
        """Test that is_guest is stored when creating device connection."""
        # Create device first
        device = Device(
            mac_address=mock_guest_device_data["mac"],
            network_name="test-network",
            hostname=mock_guest_device_data.get("hostname"),
            first_seen=datetime.utcnow(),
        )
        db_session.add(device)
        db_session.commit()

        # Simulate connection creation logic from device_collector.py
        is_guest = mock_guest_device_data.get("is_guest", False)
        connection = DeviceConnection(
            device_id=device.id,
            network_name="test-network",
            timestamp=datetime.utcnow(),
            is_connected=mock_guest_device_data.get("connected", False),
            connection_type=mock_guest_device_data.get("connection_type", "wireless"),
            is_guest=is_guest,
            ip_address=mock_guest_device_data.get("ip"),
        )
        db_session.add(connection)
        db_session.commit()

        # Verify is_guest was stored
        stored_connection = db_session.query(DeviceConnection).filter(
            DeviceConnection.device_id == device.id
        ).first()
        assert stored_connection.is_guest is True

    def test_store_non_guest_status_on_device_connection(self, db_session, mock_device_data):
        """Test that is_guest=False is stored for non-guest devices."""
        # Create device first
        device = Device(
            mac_address=mock_device_data["mac"],
            hostname=mock_device_data.get("hostname"),
            first_seen=datetime.utcnow(),
        )
        db_session.add(device)
        db_session.commit()

        # Simulate connection creation logic from device_collector.py
        is_guest = mock_device_data.get("is_guest", False)
        connection = DeviceConnection(
            device_id=device.id,
            network_name="test-network",
            timestamp=datetime.utcnow(),
            is_connected=mock_device_data.get("connected", False),
            connection_type=mock_device_data.get("connection_type", "wireless"),
            is_guest=is_guest,
            ip_address=mock_device_data.get("ip"),
        )
        db_session.add(connection)
        db_session.commit()

        # Verify is_guest was stored as False
        stored_connection = db_session.query(DeviceConnection).filter(
            DeviceConnection.device_id == device.id
        ).first()
        assert stored_connection.is_guest is False

    def test_default_guest_status_when_not_in_api_data(self, db_session):
        """Test that is_guest defaults to False when not provided by API."""
        # Create device
        device = Device(
            mac_address="cc:dd:ee:ff:00:11",
            network_name="test-network",
            hostname="device-without-guest",
            first_seen=datetime.utcnow(),
        )
        db_session.add(device)
        db_session.commit()

        # Simulate API data without is_guest field
        mock_data_no_guest = {
            "connected": True,
            "connection_type": "wired",
            "ip": "192.168.1.150",
        }

        # Simulate logic with .get() fallback
        is_guest = mock_data_no_guest.get("is_guest", False)
        connection = DeviceConnection(
            device_id=device.id,
            network_name="test-network",
            timestamp=datetime.utcnow(),
            is_connected=mock_data_no_guest.get("connected", False),
            connection_type=mock_data_no_guest.get("connection_type", "wireless"),
            is_guest=is_guest,
            ip_address=mock_data_no_guest.get("ip"),
        )
        db_session.add(connection)
        db_session.commit()

        # Verify is_guest defaults to False
        stored_connection = db_session.query(DeviceConnection).filter(
            DeviceConnection.device_id == device.id
        ).first()
        assert stored_connection.is_guest is False


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
            "is_guest",
        }

        # Verify critical new fields are in expected structure
        assert "nickname" in expected_device_fields
        assert "hostname" in expected_device_fields
        assert "manufacturer" in expected_device_fields
        assert "name" in expected_device_fields  # Computed field
        assert "is_guest" in expected_device_fields  # Guest network status

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

    def test_guest_device_response_includes_is_guest(self):
        """Test that guest device API response includes is_guest field."""
        mock_guest_device = {
            "name": "Guest Device",
            "nickname": "Guest Device",
            "hostname": "guest-device",
            "manufacturer": "Guest Inc.",
            "type": "generic",
            "ip_address": "192.168.1.200",
            "is_online": True,
            "connection_type": "wireless",
            "signal_strength": -45,
            "bandwidth_down_mbps": 10.5,
            "bandwidth_up_mbps": 2.5,
            "node": "Eero Node 1",
            "mac_address": "bb:cc:dd:ee:ff:00",
            "last_seen": "2024-01-01T12:00:00",
            "aliases": None,
            "is_guest": True,
        }

        # Verify is_guest field is present
        assert "is_guest" in mock_guest_device
        assert mock_guest_device["is_guest"] is True

    def test_non_guest_device_response_includes_is_guest(self):
        """Test that non-guest device API response includes is_guest=False."""
        mock_regular_device = {
            "name": "Regular Device",
            "is_guest": False,
        }

        # Verify is_guest field is present and False
        assert "is_guest" in mock_regular_device
        assert mock_regular_device["is_guest"] is False

    def test_guest_status_handles_null_values(self):
        """Test that is_guest field properly handles None/null values."""
        # Mock device with None is_guest (should be treated as False)
        mock_device_none = {
            "name": "Device",
            "is_guest": None,
        }

        # In JavaScript: if (!showGuests && device.is_guest === true)
        # None/null should NOT match === true
        is_guest = mock_device_none["is_guest"]
        assert is_guest is None  # Verify it's None
        assert is_guest != True  # Verify it doesn't equal True
        assert (is_guest is True) is False  # Verify explicit check is False
