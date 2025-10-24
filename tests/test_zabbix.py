"""Tests for Zabbix integration endpoints."""

from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.zabbix import parse_item_key
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
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}  # Allow cross-thread access for TestClient
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sample_zabbix_data(db_session):
    """Create sample data for Zabbix testing."""
    network_name = "TestNetwork"

    # Create devices
    device1 = Device(
        network_name=network_name,
        mac_address="AA:BB:CC:DD:EE:FF",
        hostname="Test-iPhone",
        nickname="John's iPhone",
        device_type="phone",
    )
    device2 = Device(
        network_name=network_name,
        mac_address="11:22:33:44:55:66",
        hostname="Test-Laptop",
        nickname="Work Laptop",
        device_type="laptop_computer",
    )
    db_session.add_all([device1, device2])

    # Create nodes
    node1 = EeroNode(
        network_name=network_name,
        eero_id="node_123",
        location="Living Room",
        model="eero Pro 6E",
        is_gateway=True,
    )
    node2 = EeroNode(
        network_name=network_name,
        eero_id="node_456",
        location="Bedroom",
        model="eero Beacon",
        is_gateway=False,
    )
    db_session.add_all([node1, node2])
    db_session.commit()

    # Create network metric
    network_metric = NetworkMetric(
        network_name=network_name,
        timestamp=datetime.utcnow(),
        total_devices=10,
        total_devices_online=7,
        wan_status="online",
    )
    db_session.add(network_metric)

    # Create speedtest
    speedtest = Speedtest(
        network_name=network_name,
        timestamp=datetime.utcnow(),
        download_mbps=150.5,
        upload_mbps=50.2,
        latency_ms=12.3,
    )
    db_session.add(speedtest)

    # Create device connections
    conn1 = DeviceConnection(
        network_name=network_name,
        timestamp=datetime.utcnow(),
        device_id=device1.id,
        is_connected=True,
        signal_strength=-45,
        bandwidth_down_mbps=25.5,
        bandwidth_up_mbps=10.2,
        eero_node_id=node1.id,
    )
    conn2 = DeviceConnection(
        network_name=network_name,
        timestamp=datetime.utcnow(),
        device_id=device2.id,
        is_connected=False,
        eero_node_id=node2.id,
    )
    db_session.add_all([conn1, conn2])

    # Create node metrics
    node_metric1 = EeroNodeMetric(
        timestamp=datetime.utcnow(),
        eero_node_id=node1.id,
        status="online",
        connected_device_count=5,
        mesh_quality_bars=5,
    )
    node_metric2 = EeroNodeMetric(
        timestamp=datetime.utcnow(),
        eero_node_id=node2.id,
        status="online",
        connected_device_count=2,
        mesh_quality_bars=3,
    )
    db_session.add_all([node_metric1, node_metric2])

    db_session.commit()

    return {
        "device1": device1,
        "device2": device2,
        "node1": node1,
        "node2": node2,
    }


class TestZabbixDiscovery:
    """Tests for Zabbix Low-Level Discovery endpoints."""

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_device_discovery_returns_json(self, mock_db_context, db_session, sample_zabbix_data):
        """Test that device discovery returns valid JSON."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/devices")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_device_discovery_has_data_key(self, mock_db_context, db_session, sample_zabbix_data):
        """Test that device discovery response has 'data' key."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/devices")

        json_data = response.json()
        assert "data" in json_data
        assert isinstance(json_data["data"], list)

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_device_discovery_includes_required_macros(self, mock_db_context, db_session, sample_zabbix_data):
        """Test that device discovery includes all required LLD macros."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/devices")

        json_data = response.json()
        assert len(json_data["data"]) > 0, "Expected at least one device in discovery data"
        device = json_data["data"][0]
        assert "{#MAC}" in device
        assert "{#HOSTNAME}" in device
        assert "{#NICKNAME}" in device
        assert "{#TYPE}" in device
        assert "{#IP}" in device
        assert "{#CONNECTION_TYPE}" in device

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_node_discovery_returns_json(self, mock_db_context, db_session, sample_zabbix_data):
        """Test that node discovery returns valid JSON."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/nodes")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_node_discovery_has_data_key(self, mock_db_context, db_session, sample_zabbix_data):
        """Test that node discovery response has 'data' key."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/nodes")

        json_data = response.json()
        assert "data" in json_data
        assert isinstance(json_data["data"], list)

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_node_discovery_includes_required_macros(self, mock_db_context, db_session, sample_zabbix_data):
        """Test that node discovery includes all required LLD macros."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/nodes")

        json_data = response.json()
        assert len(json_data["data"]) > 0, "Expected at least one node in discovery data"
        node = json_data["data"][0]
        assert "{#NODE_ID}" in node
        assert "{#NODE_NAME}" in node
        assert "{#NODE_MODEL}" in node
        assert "{#IS_GATEWAY}" in node
        assert "{#MAC}" in node
        assert "{#FIRMWARE}" in node

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_node_discovery_gateway_flag_is_string(self, mock_db_context, db_session, sample_zabbix_data):
        """Test that IS_GATEWAY is returned as string '0' or '1'."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/nodes")

        json_data = response.json()
        assert len(json_data["data"]) > 0, "Expected at least one node in discovery data"
        for node in json_data["data"]:
            assert node["{#IS_GATEWAY}"] in ["0", "1"]


class TestZabbixDataEndpoint:
    """Tests for Zabbix data endpoint."""

    def test_data_endpoint_requires_item_parameter(self):
        """Test that data endpoint requires 'item' query parameter."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data")

        # Should return 422 for missing required parameter
        assert response.status_code == 422

    def test_data_endpoint_returns_json_with_value_and_timestamp(self):
        """Test that data endpoint returns value and timestamp."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=network.devices.total")

        if response.status_code == 200:
            json_data = response.json()
            assert "value" in json_data
            assert "timestamp" in json_data

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_network_devices_total_metric(self, mock_db_context, db_session, sample_zabbix_data):
        """Test network.devices.total metric."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=network.devices.total")

        assert response.status_code == 200
        json_data = response.json()
        assert json_data["value"] == 10
        assert "timestamp" in json_data

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_network_devices_online_metric(self, mock_db_context, db_session, sample_zabbix_data):
        """Test network.devices.online metric."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=network.devices.online")

        assert response.status_code == 200
        json_data = response.json()
        assert json_data["value"] == 7
        assert "timestamp" in json_data

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_network_status_metric(self, mock_db_context, db_session, sample_zabbix_data):
        """Test network.status metric."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=network.status")

        assert response.status_code == 200
        json_data = response.json()
        assert json_data["value"] == 1  # online
        assert "timestamp" in json_data

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_speedtest_download_metric(self, mock_db_context, db_session, sample_zabbix_data):
        """Test speedtest.download metric."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=speedtest.download")

        assert response.status_code == 200
        json_data = response.json()
        assert json_data["value"] == 150.5
        assert "timestamp" in json_data

    def test_device_metric_requires_mac_address(self):
        """Test that device metrics require MAC address identifier."""
        from src.main import app

        # Mock network retrieval
        mock_network = type('obj', (object,), {'name': 'TestNetwork'})()
        with patch('src.api.zabbix.EeroClientWrapper') as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.get_networks.return_value = [mock_network]

            client = TestClient(app)
            response = client.get("/api/zabbix/data?item=device.connected")

            # Should return 400 for missing identifier
            assert response.status_code == 400
            assert "MAC address" in response.json()["detail"]

    def test_node_metric_requires_node_id(self):
        """Test that node metrics require node ID identifier."""
        from src.main import app

        # Mock network retrieval
        mock_network = type('obj', (object,), {'name': 'TestNetwork'})()
        with patch('src.api.zabbix.EeroClientWrapper') as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.get_networks.return_value = [mock_network]

            client = TestClient(app)
            response = client.get("/api/zabbix/data?item=node.status")

            # Should return 400 for missing identifier
            assert response.status_code == 400
            assert "node ID" in response.json()["detail"]

    def test_invalid_item_returns_404(self):
        """Test that invalid item key returns 404."""
        from src.main import app

        # Mock network retrieval
        mock_network = type('obj', (object,), {'name': 'TestNetwork'})()
        with patch('src.api.zabbix.EeroClientWrapper') as mock_client_class:
            mock_client = mock_client_class.return_value
            mock_client.get_networks.return_value = [mock_network]

            client = TestClient(app)
            response = client.get("/api/zabbix/data?item=invalid.metric.name")

            assert response.status_code == 404
            assert "not found or not supported" in response.json()["detail"]


class TestZabbixItemKeyParsing:
    """Tests for Zabbix item key parsing."""

    def test_parse_simple_item_key(self):
        """Test parsing item key without identifier."""
        metric_name, identifier = parse_item_key("network.devices.total")

        assert metric_name == "network.devices.total"
        assert identifier is None

    def test_parse_item_key_with_identifier(self):
        """Test parsing item key with identifier."""
        metric_name, identifier = parse_item_key("device.connected[AA:BB:CC:DD:EE:FF]")

        assert metric_name == "device.connected"
        assert identifier == "AA:BB:CC:DD:EE:FF"

    def test_parse_item_key_with_numeric_identifier(self):
        """Test parsing item key with numeric identifier."""
        metric_name, identifier = parse_item_key("node.status[12345]")

        assert metric_name == "node.status"
        assert identifier == "12345"

    def test_parse_item_key_with_underscores(self):
        """Test parsing item key with underscores."""
        metric_name, identifier = parse_item_key("device.bandwidth.down[AA:BB:CC:DD:EE:FF]")

        assert metric_name == "device.bandwidth.down"
        assert identifier == "AA:BB:CC:DD:EE:FF"

    def test_parse_invalid_item_key(self):
        """Test parsing invalid item key."""
        metric_name, identifier = parse_item_key("invalid[key")

        # Should return the original string and None
        assert metric_name == "invalid[key"
        assert identifier is None


class TestZabbixDeviceMetrics:
    """Tests for Zabbix device-specific metrics."""

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_device_connected_metric(self, mock_db_context, db_session, sample_zabbix_data):
        """Test device.connected[MAC] metric."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        mac = sample_zabbix_data["device1"].mac_address
        response = client.get(f"/api/zabbix/data?item=device.connected[{mac}]")

        assert response.status_code == 200
        json_data = response.json()
        assert json_data["value"] == 1  # connected
        assert "timestamp" in json_data

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_device_signal_metric(self, mock_db_context, db_session, sample_zabbix_data):
        """Test device.signal[MAC] metric."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        mac = sample_zabbix_data["device1"].mac_address
        response = client.get(f"/api/zabbix/data?item=device.signal[{mac}]")

        assert response.status_code == 200
        json_data = response.json()
        assert json_data["value"] == -45
        assert "timestamp" in json_data

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_device_bandwidth_down_metric(self, mock_db_context, db_session, sample_zabbix_data):
        """Test device.bandwidth.down[MAC] metric."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        mac = sample_zabbix_data["device1"].mac_address
        response = client.get(f"/api/zabbix/data?item=device.bandwidth.down[{mac}]")

        assert response.status_code == 200
        json_data = response.json()
        assert json_data["value"] == 25.5
        assert "timestamp" in json_data

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_device_bandwidth_up_metric(self, mock_db_context, db_session, sample_zabbix_data):
        """Test device.bandwidth.up[MAC] metric."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        mac = sample_zabbix_data["device1"].mac_address
        response = client.get(f"/api/zabbix/data?item=device.bandwidth.up[{mac}]")

        assert response.status_code == 200
        json_data = response.json()
        assert json_data["value"] == 10.2
        assert "timestamp" in json_data

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_device_not_found(self, mock_db_context, db_session, sample_zabbix_data):
        """Test device metric with non-existent MAC."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=device.connected[FF:FF:FF:FF:FF:FF]")

        assert response.status_code == 404
        assert "Device not found" in response.json()["detail"]


class TestZabbixNodeMetrics:
    """Tests for Zabbix node-specific metrics."""

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_node_status_metric(self, mock_db_context, db_session, sample_zabbix_data):
        """Test node.status[NODE_ID] metric."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        node_id = sample_zabbix_data["node1"].eero_id
        response = client.get(f"/api/zabbix/data?item=node.status[{node_id}]")

        assert response.status_code == 200
        json_data = response.json()
        assert json_data["value"] == 1  # online
        assert "timestamp" in json_data

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_node_devices_metric(self, mock_db_context, db_session, sample_zabbix_data):
        """Test node.devices[NODE_ID] metric."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        node_id = sample_zabbix_data["node1"].eero_id
        response = client.get(f"/api/zabbix/data?item=node.devices[{node_id}]")

        assert response.status_code == 200
        json_data = response.json()
        assert json_data["value"] == 5
        assert "timestamp" in json_data

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_node_mesh_quality_metric(self, mock_db_context, db_session, sample_zabbix_data):
        """Test node.mesh_quality[NODE_ID] metric."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        node_id = sample_zabbix_data["node1"].eero_id
        response = client.get(f"/api/zabbix/data?item=node.mesh_quality[{node_id}]")

        assert response.status_code == 200
        json_data = response.json()
        assert json_data["value"] == 5
        assert "timestamp" in json_data

    @pytest.mark.skip(reason="Integration test - requires database dependency injection")
    @patch("src.utils.database.get_db_context")
    def test_node_not_found(self, mock_db_context, db_session, sample_zabbix_data):
        """Test node metric with non-existent NODE_ID."""
        mock_db_context.return_value.__enter__.return_value = db_session
        mock_db_context.return_value.__exit__.return_value = None

        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=node.status[nonexistent_node]")

        assert response.status_code == 404
        assert "Node not found" in response.json()["detail"]


class TestZabbixDataValues:
    """Tests for Zabbix data value correctness."""

    def test_network_status_returns_binary_value(self):
        """Test that network status returns 1 or 0."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=network.status")

        if response.status_code == 200:
            json_data = response.json()
            assert json_data["value"] in [0, 1]

    def test_speedtest_values_are_numeric(self):
        """Test that speedtest values are numeric."""
        from src.main import app

        client = TestClient(app)

        for item in ["speedtest.download", "speedtest.upload", "speedtest.latency"]:
            response = client.get(f"/api/zabbix/data?item={item}")

            if response.status_code == 200:
                json_data = response.json()
                assert isinstance(json_data["value"], (int, float))

    def test_timestamp_is_iso_format(self):
        """Test that timestamp is in ISO format."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=network.devices.total")

        if response.status_code == 200:
            json_data = response.json()
            # Should be parseable as datetime
            from datetime import datetime
            try:
                datetime.fromisoformat(json_data["timestamp"])
            except ValueError:
                pytest.fail("Timestamp is not in valid ISO format")


class TestZabbixMultiNetwork:
    """Tests for multi-network functionality in Zabbix endpoints."""

    @pytest.fixture
    def multi_network_data(self, db_session):
        """Create sample data for two networks."""
        # Network 1
        device1_net1 = Device(
            network_name="Network1",
            mac_address="AA:BB:CC:DD:EE:F1",
            hostname="Device1-Net1",
        )
        node1_net1 = EeroNode(
            network_name="Network1",
            eero_id="node_net1_1",
            location="Living Room",
        )
        db_session.add_all([device1_net1, node1_net1])
        db_session.commit()

        conn1_net1 = DeviceConnection(
            network_name="Network1",
            timestamp=datetime.utcnow(),
            device_id=device1_net1.id,
            is_connected=True,
        )
        metric1_net1 = NetworkMetric(
            network_name="Network1",
            timestamp=datetime.utcnow(),
            total_devices=5,
            total_devices_online=4,
        )
        db_session.add_all([conn1_net1, metric1_net1])

        # Network 2
        device1_net2 = Device(
            network_name="Network2",
            mac_address="AA:BB:CC:DD:EE:F2",
            hostname="Device1-Net2",
        )
        node1_net2 = EeroNode(
            network_name="Network2",
            eero_id="node_net2_1",
            location="Office",
        )
        db_session.add_all([device1_net2, node1_net2])
        db_session.commit()

        conn1_net2 = DeviceConnection(
            network_name="Network2",
            timestamp=datetime.utcnow(),
            device_id=device1_net2.id,
            is_connected=True,
        )
        metric1_net2 = NetworkMetric(
            network_name="Network2",
            timestamp=datetime.utcnow(),
            total_devices=10,
            total_devices_online=8,
        )
        db_session.add_all([conn1_net2, metric1_net2])
        db_session.commit()

        return db_session

    def test_discover_devices_filters_by_network(self, multi_network_data):
        """Test that device discovery filters by network parameter."""
        from src.main import app

        # Mock the client to return both networks
        mock_net1 = type('obj', (object,), {'name': 'Network1'})()
        mock_net2 = type('obj', (object,), {'name': 'Network2'})()

        with patch('src.api.zabbix.EeroClientWrapper') as mock_client_class, \
             patch('src.api.zabbix.get_db_context') as mock_db_context:
            # Configure the mock context manager
            mock_db_context.return_value.__enter__.return_value = multi_network_data
            mock_db_context.return_value.__exit__.return_value = None
            mock_client = mock_client_class.return_value
            mock_client.get_networks.return_value = [mock_net1, mock_net2]

            client = TestClient(app)

            # Request devices for Network1
            response = client.get("/api/zabbix/discovery/devices?network=Network1")
            assert response.status_code == 200
            data = response.json()["data"]
            assert len(data) == 1
            assert data[0]["{#HOSTNAME}"] == "Device1-Net1"
            assert data[0]["{#NETWORK}"] == "Network1"

            # Request devices for Network2
            response = client.get("/api/zabbix/discovery/devices?network=Network2")
            assert response.status_code == 200
            data = response.json()["data"]
            assert len(data) == 1
            assert data[0]["{#HOSTNAME}"] == "Device1-Net2"
            assert data[0]["{#NETWORK}"] == "Network2"

    def test_discover_nodes_filters_by_network(self, multi_network_data):
        """Test that node discovery filters by network parameter."""
        from src.main import app

        # Mock the client to return both networks
        mock_net1 = type('obj', (object,), {'name': 'Network1'})()
        mock_net2 = type('obj', (object,), {'name': 'Network2'})()

        with patch('src.api.zabbix.EeroClientWrapper') as mock_client_class, \
             patch('src.api.zabbix.get_db_context') as mock_db_context:
            # Configure the mock context manager
            mock_db_context.return_value.__enter__.return_value = multi_network_data
            mock_db_context.return_value.__exit__.return_value = None
            mock_client = mock_client_class.return_value
            mock_client.get_networks.return_value = [mock_net1, mock_net2]

            client = TestClient(app)

            # Request nodes for Network1
            response = client.get("/api/zabbix/discovery/nodes?network=Network1")
            assert response.status_code == 200
            data = response.json()["data"]
            assert len(data) == 1
            assert data[0]["{#NODE_NAME}"] == "Living Room"
            assert data[0]["{#NETWORK}"] == "Network1"

            # Request nodes for Network2
            response = client.get("/api/zabbix/discovery/nodes?network=Network2")
            assert response.status_code == 200
            data = response.json()["data"]
            assert len(data) == 1
            assert data[0]["{#NODE_NAME}"] == "Office"
            assert data[0]["{#NETWORK}"] == "Network2"

    def test_metrics_filter_by_network(self, multi_network_data):
        """Test that metric data filters by network parameter."""
        from src.main import app

        # Mock the client to return both networks
        mock_net1 = type('obj', (object,), {'name': 'Network1'})()
        mock_net2 = type('obj', (object,), {'name': 'Network2'})()

        with patch('src.api.zabbix.EeroClientWrapper') as mock_client_class, \
             patch('src.api.zabbix.get_db_context') as mock_db_context:
            # Configure the mock context manager
            mock_db_context.return_value.__enter__.return_value = multi_network_data
            mock_db_context.return_value.__exit__.return_value = None
            mock_client = mock_client_class.return_value
            mock_client.get_networks.return_value = [mock_net1, mock_net2]

            client = TestClient(app)

            # Request metrics for Network1
            response = client.get("/api/zabbix/data?item=network.devices.total&network=Network1")
            assert response.status_code == 200
            assert response.json()["value"] == 5

            # Request metrics for Network2
            response = client.get("/api/zabbix/data?item=network.devices.total&network=Network2")
            assert response.status_code == 200
            assert response.json()["value"] == 10

    def test_defaults_to_first_network_when_parameter_omitted(self, multi_network_data):
        """Test backwards compatibility: defaults to first network when parameter omitted."""
        from src.main import app

        # Mock the client to return Network2 as the first network
        mock_net2 = type('obj', (object,), {'name': 'Network2'})()

        with patch('src.api.zabbix.EeroClientWrapper') as mock_client_class, \
             patch('src.api.zabbix.get_db_context') as mock_db_context:
            # Configure the mock context manager
            mock_db_context.return_value.__enter__.return_value = multi_network_data
            mock_db_context.return_value.__exit__.return_value = None
            mock_client = mock_client_class.return_value
            mock_client.get_networks.return_value = [mock_net2]

            client = TestClient(app)

            # Request without network parameter - should use first network (Network2)
            response = client.get("/api/zabbix/discovery/devices")
            assert response.status_code == 200
            data = response.json()["data"]
            assert len(data) == 1
            assert data[0]["{#NETWORK}"] == "Network2"

    def test_network_macro_included_in_discovery(self, multi_network_data):
        """Test that {#NETWORK} macro is included in all discovery responses."""
        from src.main import app

        mock_net1 = type('obj', (object,), {'name': 'Network1'})()

        with patch('src.api.zabbix.EeroClientWrapper') as mock_client_class, \
             patch('src.api.zabbix.get_db_context') as mock_db_context:
            # Configure the mock context manager
            mock_db_context.return_value.__enter__.return_value = multi_network_data
            mock_db_context.return_value.__exit__.return_value = None
            mock_client = mock_client_class.return_value
            mock_client.get_networks.return_value = [mock_net1]

            client = TestClient(app)

            # Check device discovery
            response = client.get("/api/zabbix/discovery/devices?network=Network1")
            data = response.json()["data"]
            assert all("{#NETWORK}" in item for item in data)

            # Check node discovery
            response = client.get("/api/zabbix/discovery/nodes?network=Network1")
            data = response.json()["data"]
            assert all("{#NETWORK}" in item for item in data)
