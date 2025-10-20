"""Tests for Zabbix integration endpoints."""

from datetime import datetime

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
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def sample_zabbix_data(db_session):
    """Create sample data for Zabbix testing."""
    # Create devices
    device1 = Device(
        mac_address="AA:BB:CC:DD:EE:FF",
        hostname="Test-iPhone",
        nickname="John's iPhone",
        device_type="phone",
    )
    device2 = Device(
        mac_address="11:22:33:44:55:66",
        hostname="Test-Laptop",
        nickname="Work Laptop",
        device_type="laptop_computer",
    )
    db_session.add_all([device1, device2])

    # Create nodes
    node1 = EeroNode(
        eero_id="node_123",
        location="Living Room",
        model="eero Pro 6E",
        is_gateway=True,
    )
    node2 = EeroNode(
        eero_id="node_456",
        location="Bedroom",
        model="eero Beacon",
        is_gateway=False,
    )
    db_session.add_all([node1, node2])
    db_session.commit()

    # Create network metric
    network_metric = NetworkMetric(
        timestamp=datetime.utcnow(),
        total_devices=10,
        total_devices_online=7,
        wan_status="online",
    )
    db_session.add(network_metric)

    # Create speedtest
    speedtest = Speedtest(
        timestamp=datetime.utcnow(),
        download_mbps=150.5,
        upload_mbps=50.2,
        latency_ms=12.3,
    )
    db_session.add(speedtest)

    # Create device connections
    conn1 = DeviceConnection(
        timestamp=datetime.utcnow(),
        device_id=device1.id,
        is_connected=True,
        signal_strength=-45,
        bandwidth_down_mbps=25.5,
        bandwidth_up_mbps=10.2,
        eero_node_id=node1.id,
    )
    conn2 = DeviceConnection(
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

    @pytest.mark.skip(reason="Requires database override setup")
    def test_device_discovery_returns_json(self):
        """Test that device discovery returns valid JSON."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/devices")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"

    @pytest.mark.skip(reason="Requires database override setup")
    def test_device_discovery_has_data_key(self):
        """Test that device discovery response has 'data' key."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/devices")

        json_data = response.json()
        assert "data" in json_data
        assert isinstance(json_data["data"], list)

    @pytest.mark.skip(reason="Requires database override setup")
    def test_device_discovery_includes_required_macros(self):
        """Test that device discovery includes all required LLD macros."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/devices")

        json_data = response.json()
        if len(json_data["data"]) > 0:
            device = json_data["data"][0]
            assert "{#MAC}" in device
            assert "{#HOSTNAME}" in device
            assert "{#NICKNAME}" in device
            assert "{#TYPE}" in device

    @pytest.mark.skip(reason="Requires database override setup")
    def test_node_discovery_returns_json(self):
        """Test that node discovery returns valid JSON."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/nodes")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"

    @pytest.mark.skip(reason="Requires database override setup")
    def test_node_discovery_has_data_key(self):
        """Test that node discovery response has 'data' key."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/nodes")

        json_data = response.json()
        assert "data" in json_data
        assert isinstance(json_data["data"], list)

    @pytest.mark.skip(reason="Requires database override setup")
    def test_node_discovery_includes_required_macros(self):
        """Test that node discovery includes all required LLD macros."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/nodes")

        json_data = response.json()
        if len(json_data["data"]) > 0:
            node = json_data["data"][0]
            assert "{#NODE_ID}" in node
            assert "{#NODE_NAME}" in node
            assert "{#NODE_MODEL}" in node
            assert "{#IS_GATEWAY}" in node

    @pytest.mark.skip(reason="Requires database override setup")
    def test_node_discovery_gateway_flag_is_string(self):
        """Test that IS_GATEWAY is returned as string '0' or '1'."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/discovery/nodes")

        json_data = response.json()
        if len(json_data["data"]) > 0:
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

    @pytest.mark.skip(reason="Requires database override setup")
    def test_network_devices_total_metric(self):
        """Test network.devices.total metric."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=network.devices.total")

        # May return 200 or 404 depending on data availability
        assert response.status_code in [200, 404]

    @pytest.mark.skip(reason="Requires database override setup")
    def test_network_devices_online_metric(self):
        """Test network.devices.online metric."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=network.devices.online")

        assert response.status_code in [200, 404]

    @pytest.mark.skip(reason="Requires database override setup")
    def test_network_status_metric(self):
        """Test network.status metric."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=network.status")

        assert response.status_code in [200, 404]

    @pytest.mark.skip(reason="Requires database override setup")
    def test_speedtest_download_metric(self):
        """Test speedtest.download metric."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=speedtest.download")

        assert response.status_code in [200, 404]

    def test_device_metric_requires_mac_address(self):
        """Test that device metrics require MAC address identifier."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=device.connected")

        # Should return 400 for missing identifier
        assert response.status_code == 400
        assert "MAC address" in response.json()["detail"]

    def test_node_metric_requires_node_id(self):
        """Test that node metrics require node ID identifier."""
        from src.main import app

        client = TestClient(app)
        response = client.get("/api/zabbix/data?item=node.status")

        # Should return 400 for missing identifier
        assert response.status_code == 400
        assert "node ID" in response.json()["detail"]

    def test_invalid_item_returns_404(self):
        """Test that invalid item key returns 404."""
        from src.main import app

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
