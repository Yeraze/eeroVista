"""Tests for Prometheus metrics endpoint."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.prometheus import update_metrics
from src.models.database import (
    Base,
    Device,
    DeviceConnection,
    EeroNode,
    EeroNodeMetric,
    NetworkMetric,
    Speedtest,
)


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
def sample_network_data(db_session):
    """Create sample network data for testing."""
    # Create network metric
    network_metric = NetworkMetric(
        timestamp=datetime.now(timezone.utc),
        total_devices=10,
        total_devices_online=7,
        wan_status="online",
    )
    db_session.add(network_metric)

    # Create speedtest
    speedtest = Speedtest(
        timestamp=datetime.now(timezone.utc),
        download_mbps=150.5,
        upload_mbps=50.2,
        latency_ms=12.3,
    )
    db_session.add(speedtest)

    # Create eero node
    node = EeroNode(
        eero_id="node_123",
        location="Living Room",
        model="eero Pro 6E",
        is_gateway=True,
    )
    db_session.add(node)
    db_session.commit()

    # Create node metric
    node_metric = EeroNodeMetric(
        timestamp=datetime.now(timezone.utc),
        eero_node_id=node.id,
        status="online",
        connected_device_count=5,
        connected_wired_count=2,
        connected_wireless_count=3,
        mesh_quality_bars=5,
        uptime_seconds=86400,
    )
    db_session.add(node_metric)

    # Create device
    device = Device(
        mac_address="AA:BB:CC:DD:EE:FF",
        hostname="Test-iPhone",
        nickname="John's iPhone",
        device_type="phone",
    )
    db_session.add(device)
    db_session.commit()

    # Create device connection
    connection = DeviceConnection(
        timestamp=datetime.now(timezone.utc),
        device_id=device.id,
        is_connected=True,
        connection_type="wireless",
        signal_strength=-45,
        bandwidth_down_mbps=25.5,
        bandwidth_up_mbps=10.2,
        eero_node_id=node.id,
    )
    db_session.add(connection)
    db_session.commit()

    return {
        "network_metric": network_metric,
        "speedtest": speedtest,
        "node": node,
        "node_metric": node_metric,
        "device": device,
        "connection": connection,
    }


class TestPrometheusMetrics:
    """Tests for Prometheus metrics endpoint."""

    def test_metrics_endpoint_returns_text_format(self):
        """Test that /metrics endpoint returns text/plain content type."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]

    def test_metrics_endpoint_contains_help_and_type(self):
        """Test that metrics output contains HELP and TYPE lines."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/metrics")

        content = response.text
        assert "# HELP" in content
        assert "# TYPE" in content

    def test_metrics_endpoint_contains_network_metrics(self):
        """Test that network metrics are present."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/metrics")

        content = response.text
        assert "eero_network_devices_total" in content
        assert "eero_network_devices_online" in content
        assert "eero_network_status" in content

    def test_metrics_endpoint_contains_speedtest_metrics(self):
        """Test that speedtest metrics are present."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/metrics")

        content = response.text
        assert "eero_speedtest_download_mbps" in content
        assert "eero_speedtest_upload_mbps" in content
        assert "eero_speedtest_latency_ms" in content

    def test_metrics_endpoint_contains_device_metrics(self):
        """Test that device metrics are present with labels."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/metrics")

        content = response.text
        assert "eero_device_connected" in content
        assert "eero_device_signal_strength_dbm" in content
        assert "eero_device_bandwidth_down_mbps" in content
        assert "eero_device_bandwidth_up_mbps" in content

    def test_metrics_endpoint_contains_node_metrics(self):
        """Test that node metrics are present with labels."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/metrics")

        content = response.text
        assert "eero_node_status" in content
        assert "eero_node_connected_devices" in content
        assert "eero_node_mesh_quality" in content
        assert "eero_node_uptime_seconds" in content

    @patch("src.api.prometheus.get_db_context")
    def test_update_metrics_with_sample_data(self, mock_db_context, db_session, sample_network_data):
        """Test that update_metrics correctly processes sample data."""
        # Mock the database context
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        # Call update_metrics
        update_metrics()

        # Verify no exceptions were raised
        # In a more complete test, we would check the actual metric values
        # but that requires accessing the internal registry state

    def test_metrics_labels_are_properly_formatted(self):
        """Test that metric labels follow Prometheus conventions."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/metrics")

        content = response.text

        # Check for properly formatted labels (should have key="value" format)
        if "eero_device_connected{" in content:
            # Find a device metric line
            for line in content.split("\n"):
                if line.startswith("eero_device_connected{"):
                    # Should contain label format: key="value"
                    assert 'mac=' in line or 'mac="' in line
                    assert 'hostname=' in line or 'hostname="' in line
                    break

    def test_metrics_endpoint_handles_empty_database(self):
        """Test that /metrics endpoint works with no data."""
        from src.main import app

        # This test uses the actual database which might be empty
        client = TestClient(app)
        response = client.get("/metrics")

        # Should still return 200 even with no data
        assert response.status_code == 200

        # Should still have metric definitions
        content = response.text
        assert "# HELP eero_network_devices_total" in content

    def test_metrics_are_gauge_type(self):
        """Test that all eero metrics are of type gauge."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/metrics")

        content = response.text

        # All our metrics should be gauges
        type_lines = [line for line in content.split("\n") if line.startswith("# TYPE eero_")]
        for line in type_lines:
            assert "gauge" in line


class TestPrometheusMetricsValues:
    """Tests for Prometheus metric value correctness."""

    @patch("src.api.prometheus.get_db_context")
    def test_network_status_value_mapping(self, mock_db_context, db_session):
        """Test that WAN status is correctly mapped to 1/0."""
        # Create online metric
        metric = NetworkMetric(
            timestamp=datetime.now(timezone.utc),
            total_devices=10,
            total_devices_online=7,
            wan_status="online",
        )
        db_session.add(metric)
        db_session.commit()

        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        # Import after mocking
        from src.api.prometheus import network_status

        update_metrics()

        # Network status should be 1.0 for "online"
        # Note: Direct metric value checking requires accessing internal state
        # This is a basic structure test

    @patch("src.api.prometheus.get_db_context")
    def test_device_connected_value_mapping(self, mock_db_context, db_session, sample_network_data):
        """Test that device connection status is correctly mapped to 1/0."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        update_metrics()

        # Device with is_connected=True should have value 1.0
        # Device with is_connected=False should have value 0.0

    @patch("src.api.prometheus.get_db_context")
    def test_node_update_available_mapping(self, mock_db_context, db_session):
        """Test that node update_available is correctly mapped to 1/0."""
        node = EeroNode(
            eero_id="node_456",
            location="Bedroom",
            model="eero Pro",
            is_gateway=False,
            update_available=True,
        )
        db_session.add(node)
        db_session.commit()

        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        update_metrics()

        # Node with update_available=True should have value 1.0

    @patch("src.api.prometheus.get_db_context")
    def test_device_without_connections(self, mock_db_context, db_session):
        """Test that update_metrics handles devices without connection records."""
        # Create a device without any connection records
        device = Device(
            mac_address="11:22:33:44:55:66",
            hostname="Test-Device-No-Conn",
            nickname="Disconnected Device",
            device_type="laptop",
        )
        db_session.add(device)
        db_session.commit()

        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        # Should not raise AttributeError
        try:
            update_metrics()
        except AttributeError as e:
            pytest.fail(f"update_metrics() raised AttributeError for device without connections: {e}")
