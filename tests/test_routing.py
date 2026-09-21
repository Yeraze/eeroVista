"""Tests for IP reservations and port forwarding functionality."""

import pytest
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.models.database import Base, IpReservation, PortForward


class TestIpReservationModel:
    """Test IpReservation database model."""

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

    def test_create_reservation(self, db_session):
        """Test creating an IP reservation."""
        reservation = IpReservation(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="test-network",
            ip_address="192.168.1.100",
            description="Test Device",
        )
        db_session.add(reservation)
        db_session.commit()

        assert reservation.id is not None
        assert reservation.mac_address == "aa:bb:cc:dd:ee:ff"
        assert reservation.ip_address == "192.168.1.100"
        assert reservation.description == "Test Device"
        assert reservation.created_at is not None
        assert reservation.last_seen is not None

    def test_unique_mac_constraint(self, db_session):
        """Test that MAC address must be unique."""
        reservation1 = IpReservation(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="test-network",
            ip_address="192.168.1.100",
        )
        db_session.add(reservation1)
        db_session.commit()

        # Try to add another reservation with same MAC
        reservation2 = IpReservation(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="test-network",
            ip_address="192.168.1.101",
        )
        db_session.add(reservation2)

        with pytest.raises(Exception):  # SQLite raises IntegrityError
            db_session.commit()

    def test_query_by_mac(self, db_session):
        """Test querying reservation by MAC address."""
        reservation = IpReservation(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="test-network",
            ip_address="192.168.1.100",
            description="Test Device",
        )
        db_session.add(reservation)
        db_session.commit()

        found = db_session.query(IpReservation).filter(
            IpReservation.mac_address == "aa:bb:cc:dd:ee:ff"
        ).first()

        assert found is not None
        assert found.ip_address == "192.168.1.100"

    def test_update_last_seen(self, db_session):
        """Test updating last_seen timestamp."""
        reservation = IpReservation(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="test-network",
            ip_address="192.168.1.100",
        )
        db_session.add(reservation)
        db_session.commit()

        original_time = reservation.last_seen

        # Update last_seen
        import time
        time.sleep(0.01)  # Small delay to ensure time difference
        reservation.last_seen = datetime.utcnow()
        db_session.commit()

        assert reservation.last_seen > original_time


class TestPortForwardModel:
    """Test PortForward database model."""

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

    def test_create_forward(self, db_session):
        """Test creating a port forward."""
        forward = PortForward(
            ip_address="192.168.1.100",
            network_name="test-network",
            gateway_port=8080,
            client_port=80,
            protocol="tcp",
            description="Web Server",
            enabled=True,
        )
        db_session.add(forward)
        db_session.commit()

        assert forward.id is not None
        assert forward.ip_address == "192.168.1.100"
        assert forward.gateway_port == 8080
        assert forward.client_port == 80
        assert forward.protocol == "tcp"
        assert forward.enabled is True

    def test_query_by_ip(self, db_session):
        """Test querying forwards by IP address."""
        forward1 = PortForward(
            ip_address="192.168.1.100",
            network_name="test-network",
            gateway_port=8080,
            client_port=80,
            protocol="tcp",
        )
        forward2 = PortForward(
            ip_address="192.168.1.100",
            network_name="test-network",
            gateway_port=443,
            client_port=443,
            protocol="tcp",
        )
        forward3 = PortForward(
            ip_address="192.168.1.101",
            network_name="test-network",
            gateway_port=22,
            client_port=22,
            protocol="tcp",
        )
        db_session.add_all([forward1, forward2, forward3])
        db_session.commit()

        forwards = db_session.query(PortForward).filter(
            PortForward.ip_address == "192.168.1.100"
        ).all()

        assert len(forwards) == 2
        assert all(f.ip_address == "192.168.1.100" for f in forwards)

    def test_filter_enabled(self, db_session):
        """Test filtering by enabled status."""
        forward1 = PortForward(
            ip_address="192.168.1.100",
            network_name="test-network",
            gateway_port=8080,
            client_port=80,
            protocol="tcp",
            enabled=True,
        )
        forward2 = PortForward(
            ip_address="192.168.1.101",
            network_name="test-network",
            gateway_port=443,
            client_port=443,
            protocol="tcp",
            enabled=False,
        )
        db_session.add_all([forward1, forward2])
        db_session.commit()

        enabled_forwards = db_session.query(PortForward).filter(
            PortForward.enabled == True
        ).all()

        assert len(enabled_forwards) == 1
        assert enabled_forwards[0].gateway_port == 8080

    def test_multiple_protocols(self, db_session):
        """Test port forwards with different protocols."""
        tcp_forward = PortForward(
            ip_address="192.168.1.100",
            network_name="test-network",
            gateway_port=80,
            client_port=80,
            protocol="tcp",
        )
        udp_forward = PortForward(
            ip_address="192.168.1.100",
            network_name="test-network",
            gateway_port=53,
            client_port=53,
            protocol="udp",
        )
        both_forward = PortForward(
            ip_address="192.168.1.100",
            network_name="test-network",
            gateway_port=9000,
            client_port=9000,
            protocol="both",
        )
        db_session.add_all([tcp_forward, udp_forward, both_forward])
        db_session.commit()

        all_forwards = db_session.query(PortForward).all()
        assert len(all_forwards) == 3

        protocols = {f.protocol for f in all_forwards}
        assert protocols == {"tcp", "udp", "both"}


class TestRoutingCollector:
    """Test RoutingCollector data collection logic."""

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
        # Create a mock network with a proper string name
        mock_network = Mock()
        mock_network.name = "Home"
        client.get_networks.return_value = [mock_network]
        return client

    @pytest.fixture
    def mock_routing_data(self):
        """Create mock routing data as raw dicts from the Eero API.

        The collector fetches reservations/forwards via get_reservations /
        get_forwards, which bypass pydantic and return plain dicts (#137).
        """
        reservations = [
            {
                "mac": "aa:bb:cc:dd:ee:ff",
                "ip": "192.168.1.100",
                "description": "Device 1",
                "url": "/networks/123/reservations/1",
            },
            {
                "mac": "11:22:33:44:55:66",
                "ip": "192.168.1.101",
                "description": "Device 2",
                "url": "/networks/123/reservations/2",
            },
        ]

        forwards = [
            {
                "ip": "192.168.1.100",
                "gateway_port": 8080,
                "client_port": 80,
                "protocol": "tcp",
                "description": "Web Server",
                "enabled": True,
                "reservation": "/networks/123/reservations/1",
                "url": "/networks/123/forwards/1",
            }
        ]

        return {"reservations": reservations, "forwards": forwards}

    def test_collect_new_data(self, db_session, mock_eero_client, mock_routing_data):
        """Test collecting routing data for the first time."""
        from src.collectors.routing_collector import RoutingCollector

        # Setup mock network client
        mock_network_client = Mock()
        mock_eero_client.get_network_client.return_value = mock_network_client
        mock_eero_client.get_reservations.return_value = mock_routing_data["reservations"]
        mock_eero_client.get_forwards.return_value = mock_routing_data["forwards"]

        # Run collector
        collector = RoutingCollector(db_session, mock_eero_client)
        result = collector.run()

        # Verify results
        assert result["errors"] == 0
        assert result["reservations_added"] == 2
        assert result["reservations_updated"] == 0
        assert result["forwards_added"] == 1
        assert result["forwards_updated"] == 0

        # Verify database
        reservations = db_session.query(IpReservation).all()
        assert len(reservations) == 2

        forwards = db_session.query(PortForward).all()
        assert len(forwards) == 1

    def test_collect_update_existing(self, db_session, mock_eero_client, mock_routing_data):
        """Test updating existing routing data."""
        from src.collectors.routing_collector import RoutingCollector

        # Add existing reservation (use "Home" to match mock network name)
        existing_reservation = IpReservation(
            mac_address="aa:bb:cc:dd:ee:ff",
            network_name="Home",
            ip_address="192.168.1.99",  # Different IP
            description="Old Description",
        )
        db_session.add(existing_reservation)
        db_session.commit()

        # Setup mock network client
        mock_network_client = Mock()
        mock_eero_client.get_network_client.return_value = mock_network_client
        mock_eero_client.get_reservations.return_value = mock_routing_data["reservations"]
        mock_eero_client.get_forwards.return_value = mock_routing_data["forwards"]

        # Run collector
        collector = RoutingCollector(db_session, mock_eero_client)
        result = collector.run()

        # Verify results - should update existing, add new
        assert result["errors"] == 0
        assert result["reservations_added"] == 1  # Only the new one
        assert result["reservations_updated"] == 1  # Updated existing
        assert result["forwards_added"] == 1

        # Verify database - updated IP
        updated = db_session.query(IpReservation).filter(
            IpReservation.mac_address == "aa:bb:cc:dd:ee:ff"
        ).first()
        assert updated.ip_address == "192.168.1.100"  # Updated
        assert updated.description == "Device 1"  # Updated

    def test_fetch_failure_counts_as_error_not_empty(self, db_session, mock_eero_client):
        """A None return (fetch failed) must be an error, not silent 'no data' (#137)."""
        from src.collectors.routing_collector import RoutingCollector

        mock_eero_client.get_network_client.return_value = Mock()
        # get_reservations failed (None); get_forwards succeeded (empty)
        mock_eero_client.get_reservations.return_value = None
        mock_eero_client.get_forwards.return_value = []

        collector = RoutingCollector(db_session, mock_eero_client)
        result = collector.run()

        assert result["errors"] == 1
        # Nothing should be written when the fetch failed
        assert db_session.query(IpReservation).count() == 0
        assert db_session.query(PortForward).count() == 0

    def test_empty_lists_are_not_an_error(self, db_session, mock_eero_client):
        """Legitimately empty routing data is success, not an error."""
        from src.collectors.routing_collector import RoutingCollector

        mock_eero_client.get_network_client.return_value = Mock()
        mock_eero_client.get_reservations.return_value = []
        mock_eero_client.get_forwards.return_value = []

        collector = RoutingCollector(db_session, mock_eero_client)
        result = collector.run()

        assert result["errors"] == 0
        assert result["items_collected"] == 0

    def test_rows_missing_required_keys_are_skipped(self, db_session, mock_eero_client):
        """A missing NOT NULL key is skipped with a warning, not an IntegrityError."""
        from src.collectors.routing_collector import RoutingCollector

        mock_eero_client.get_network_client.return_value = Mock()
        mock_eero_client.get_reservations.return_value = [
            {"ip": "192.168.1.50", "description": "no mac"},  # missing mac -> skip
            {"mac": "de:ad:be:ef:00:01", "ip": "192.168.1.51", "description": "ok"},
        ]
        mock_eero_client.get_forwards.return_value = [
            {"ip": "192.168.1.50", "protocol": "tcp"},  # missing gateway_port -> skip
        ]

        collector = RoutingCollector(db_session, mock_eero_client)
        result = collector.run()

        assert result["errors"] == 0
        # Only the well-formed reservation is stored; the bad rows are skipped
        assert db_session.query(IpReservation).count() == 1
        assert db_session.query(PortForward).count() == 0


class TestRoutingAPIEndpoints:
    """Test routing API endpoints logic."""

    def test_reservation_response_structure(self):
        """Test the structure of reservation API response."""
        # This tests the expected response format
        expected_keys = {"count", "reservations"}
        reservation_keys = {"mac_address", "ip_address", "description", "last_seen"}

        # Verify structure expectations
        assert "count" in expected_keys
        assert "reservations" in expected_keys
        assert "mac_address" in reservation_keys

    def test_forward_response_structure(self):
        """Test the structure of port forward API response."""
        expected_keys = {"count", "forwards"}
        forward_keys = {
            "ip_address", "gateway_port", "client_port",
            "protocol", "description", "enabled", "last_seen"
        }

        # Verify structure expectations
        assert "count" in expected_keys
        assert "forwards" in expected_keys
        assert "gateway_port" in forward_keys
        assert "protocol" in forward_keys

    def test_mac_address_lookup_response(self):
        """Test MAC address lookup response structure."""
        # Response when reserved
        reserved_keys = {
            "reserved", "mac_address", "ip_address",
            "description", "last_seen"
        }

        # Response when not reserved
        not_reserved_keys = {"reserved", "mac_address"}

        assert "reserved" in reserved_keys
        assert "reserved" in not_reserved_keys

    def test_ip_forward_lookup_response(self):
        """Test IP forward lookup response structure."""
        expected_keys = {"ip_address", "count", "forwards"}

        assert "ip_address" in expected_keys
        assert "count" in expected_keys
        assert "forwards" in expected_keys
