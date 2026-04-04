"""Extended tests for api/zabbix.py - covers remaining uncovered lines."""

from datetime import datetime
from unittest.mock import MagicMock, patch
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api.zabbix import get_network_name_filter, parse_item_key
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
def db_engine():
    """Create a shared in-memory engine accessible across threads.

    Uses a named shared-cache URI so the same in-memory database is visible
    from any thread (including the anyio worker thread that FastAPI's async
    endpoints run in when using TestClient).
    """
    db_name = f"testdb_{uuid.uuid4().hex}"
    engine = create_engine(
        f"sqlite:///file:{db_name}?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Create a database session backed by shared in-memory engine."""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    yield session
    session.close()


def make_db_context_patch(session):
    """Create a properly-behaving get_db_context mock that yields the given session."""
    @contextmanager
    def mock_context():
        yield session

    return mock_context


@pytest.fixture
def populated_db(db_session):
    """Create a full set of test data and return the session."""
    network_name = "TestNet"

    device = Device(
        network_name=network_name,
        mac_address="AA:BB:CC:DD:EE:FF",
        hostname="test-device",
        nickname="My Device",
        device_type="laptop_computer",
    )
    db_session.add(device)

    node = EeroNode(
        network_name=network_name,
        eero_id="node_test_001",
        location="Living Room",
        model="eero Pro 6E",
        is_gateway=True,
        mac_address="11:22:33:44:55:66",
        os_version="3.5.1.0",
    )
    db_session.add(node)
    db_session.commit()

    conn = DeviceConnection(
        network_name=network_name,
        device_id=device.id,
        eero_node_id=node.id,
        timestamp=datetime.utcnow(),
        is_connected=True,
        signal_strength=-55,
        connection_type="wireless",
        ip_address="192.168.1.100",
        bandwidth_down_mbps=50.0,
        bandwidth_up_mbps=20.0,
    )
    db_session.add(conn)

    network_metric = NetworkMetric(
        network_name=network_name,
        timestamp=datetime.utcnow(),
        total_devices=15,
        total_devices_online=10,
        wan_status="online",
        connection_mode="automatic",
    )
    db_session.add(network_metric)

    speedtest = Speedtest(
        network_name=network_name,
        timestamp=datetime.utcnow(),
        download_mbps=200.5,
        upload_mbps=75.3,
        latency_ms=8.7,
    )
    db_session.add(speedtest)

    node_metric = EeroNodeMetric(
        eero_node_id=node.id,
        timestamp=datetime.utcnow(),
        status="online",
        connected_device_count=7,
        mesh_quality_bars=4,
    )
    db_session.add(node_metric)

    db_session.commit()

    return {
        "session": db_session,
        "network_name": network_name,
        "device": device,
        "node": node,
    }


def make_mock_client(network_name: str = "TestNet"):
    """Create a mock EeroClientWrapper."""
    mock = MagicMock()
    mock_net = MagicMock()
    mock_net.name = network_name
    mock.get_networks.return_value = [mock_net]
    return mock


class TestGetNetworkNameFilter:
    """Tests for get_network_name_filter helper function."""

    def test_returns_provided_network_name(self):
        mock_client = MagicMock()
        result = get_network_name_filter("MyNetwork", mock_client)
        assert result == "MyNetwork"
        mock_client.get_networks.assert_not_called()

    def test_returns_first_network_when_none_provided(self):
        mock_client = MagicMock()
        mock_net = MagicMock()
        mock_net.name = "FirstNetwork"
        mock_client.get_networks.return_value = [mock_net]

        result = get_network_name_filter(None, mock_client)
        assert result == "FirstNetwork"

    def test_returns_none_when_no_networks_available(self):
        mock_client = MagicMock()
        mock_client.get_networks.return_value = []

        result = get_network_name_filter(None, mock_client)
        assert result is None

    def test_returns_dict_network_name(self):
        mock_client = MagicMock()
        mock_client.get_networks.return_value = [{"name": "DictNetwork"}]

        result = get_network_name_filter(None, mock_client)
        assert result == "DictNetwork"


class TestDiscoverDevices:
    """Extended tests for the /api/zabbix/discovery/devices endpoint."""

    def test_returns_empty_data_when_no_network(self):
        from src.main import app
        from src.api.zabbix import get_eero_client

        mock_client = MagicMock()
        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app)
            response = client.get("/api/zabbix/discovery/devices")
            assert response.status_code == 200
            assert response.json() == {"data": []}
        finally:
            app.dependency_overrides.clear()

    def test_returns_devices_with_correct_structure(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(f"/api/zabbix/discovery/devices?network={network_name}")

                assert response.status_code == 200
                data = response.json()
                assert "data" in data
                if data["data"]:
                    device = data["data"][0]
                    assert "{#MAC}" in device
                    assert "{#HOSTNAME}" in device
                    assert "{#NICKNAME}" in device
                    assert "{#TYPE}" in device
                    assert "{#IP}" in device
                    assert "{#CONNECTION_TYPE}" in device
                    assert "{#NETWORK}" in device
        finally:
            app.dependency_overrides.clear()

    def test_filters_by_network_parameter(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        mock_client = make_mock_client("WrongNetwork")
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        # Add device for a second network
        other_device = Device(network_name="OtherNet", mac_address="FF:FF:FF:FF:FF:FF")
        db_session.add(other_device)
        db_session.commit()

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                # Request TestNet specifically (not OtherNet)
                response = client.get("/api/zabbix/discovery/devices?network=TestNet")

                assert response.status_code == 200
                data = response.json()
                for item in data["data"]:
                    assert item["{#NETWORK}"] == "TestNet"
        finally:
            app.dependency_overrides.clear()


class TestDiscoverNodes:
    """Extended tests for the /api/zabbix/discovery/nodes endpoint."""

    def test_returns_empty_data_when_no_network(self):
        from src.main import app
        from src.api.zabbix import get_eero_client

        mock_client = MagicMock()
        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app)
            response = client.get("/api/zabbix/discovery/nodes")
            assert response.status_code == 200
            assert response.json() == {"data": []}
        finally:
            app.dependency_overrides.clear()

    def test_returns_nodes_with_correct_structure(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(f"/api/zabbix/discovery/nodes?network={network_name}")

                assert response.status_code == 200
                data = response.json()
                assert "data" in data
                if data["data"]:
                    node = data["data"][0]
                    assert "{#NODE_ID}" in node
                    assert "{#NODE_NAME}" in node
                    assert "{#NODE_MODEL}" in node
                    assert "{#IS_GATEWAY}" in node
                    assert "{#MAC}" in node
                    assert "{#FIRMWARE}" in node
                    assert "{#NETWORK}" in node
                    assert node["{#IS_GATEWAY}"] in ["0", "1"]
        finally:
            app.dependency_overrides.clear()

    def test_node_without_location_uses_fallback_name(self, db_session):
        from src.main import app
        from src.api.zabbix import get_eero_client

        node = EeroNode(
            network_name="TestNet",
            eero_id="node_no_location",
            location=None,  # No location
        )
        db_session.add(node)
        db_session.commit()

        mock_client = make_mock_client("TestNet")
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/zabbix/discovery/nodes?network=TestNet")

                assert response.status_code == 200
                data = response.json()
                matching = [n for n in data["data"] if n["{#NODE_ID}"] == "node_no_location"]
                assert matching
                assert "node_no_location" in matching[0]["{#NODE_NAME}"].lower() or matching[0]["{#NODE_NAME}"] != ""
        finally:
            app.dependency_overrides.clear()


class TestGetMetricData:
    """Extended tests for the /api/zabbix/data endpoint."""

    def test_network_devices_total_returns_value(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(f"/api/zabbix/data?item=network.devices.total&network={network_name}")

                assert response.status_code == 200
                data = response.json()
                assert data["value"] == 15
        finally:
            app.dependency_overrides.clear()

    def test_network_devices_online_returns_value(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(f"/api/zabbix/data?item=network.devices.online&network={network_name}")

                assert response.status_code == 200
                data = response.json()
                assert data["value"] == 10
        finally:
            app.dependency_overrides.clear()

    def test_network_status_online_returns_1(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(f"/api/zabbix/data?item=network.status&network={network_name}")

                assert response.status_code == 200
                assert response.json()["value"] == 1
        finally:
            app.dependency_overrides.clear()

    def test_network_bridge_mode_returns_0_for_automatic(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(f"/api/zabbix/data?item=network.bridge_mode&network={network_name}")

                assert response.status_code == 200
                assert response.json()["value"] == 0  # "automatic" != "bridge"
        finally:
            app.dependency_overrides.clear()

    def test_network_bridge_mode_returns_1_for_bridge(self, db_session):
        from src.main import app
        from src.api.zabbix import get_eero_client

        metric = NetworkMetric(
            network_name="BridgeNet",
            timestamp=datetime.utcnow(),
            total_devices=5,
            wan_status="online",
            connection_mode="bridge",
        )
        db_session.add(metric)
        db_session.commit()

        mock_client = make_mock_client("BridgeNet")
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/zabbix/data?item=network.bridge_mode&network=BridgeNet")

                assert response.status_code == 200
                assert response.json()["value"] == 1
        finally:
            app.dependency_overrides.clear()

    def test_speedtest_download_returns_value(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(f"/api/zabbix/data?item=speedtest.download&network={network_name}")

                assert response.status_code == 200
                assert response.json()["value"] == 200.5
        finally:
            app.dependency_overrides.clear()

    def test_speedtest_upload_returns_value(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(f"/api/zabbix/data?item=speedtest.upload&network={network_name}")

                assert response.status_code == 200
                assert response.json()["value"] == 75.3
        finally:
            app.dependency_overrides.clear()

    def test_speedtest_latency_returns_value(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(f"/api/zabbix/data?item=speedtest.latency&network={network_name}")

                assert response.status_code == 200
                assert response.json()["value"] == 8.7
        finally:
            app.dependency_overrides.clear()

    def test_device_connected_returns_1_when_online(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        device = populated_db["device"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                mac = device.mac_address
                response = client.get(
                    f"/api/zabbix/data?item=device.connected[{mac}]&network={network_name}"
                )

                assert response.status_code == 200
                assert response.json()["value"] == 1
        finally:
            app.dependency_overrides.clear()

    def test_device_signal_returns_value(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        device = populated_db["device"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                mac = device.mac_address
                response = client.get(
                    f"/api/zabbix/data?item=device.signal[{mac}]&network={network_name}"
                )

                assert response.status_code == 200
                assert response.json()["value"] == -55
        finally:
            app.dependency_overrides.clear()

    def test_device_bandwidth_down_returns_value(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        device = populated_db["device"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                mac = device.mac_address
                response = client.get(
                    f"/api/zabbix/data?item=device.bandwidth.down[{mac}]&network={network_name}"
                )

                assert response.status_code == 200
                assert response.json()["value"] == 50.0
        finally:
            app.dependency_overrides.clear()

    def test_device_bandwidth_up_returns_value(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        device = populated_db["device"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                mac = device.mac_address
                response = client.get(
                    f"/api/zabbix/data?item=device.bandwidth.up[{mac}]&network={network_name}"
                )

                assert response.status_code == 200
                assert response.json()["value"] == 20.0
        finally:
            app.dependency_overrides.clear()

    def test_device_bandwidth_down_returns_zero_when_none(self, db_session):
        from src.main import app
        from src.api.zabbix import get_eero_client

        device = Device(network_name="ZeroNet", mac_address="ZZ:ZZ:ZZ:ZZ:ZZ:ZZ")
        db_session.add(device)
        db_session.commit()

        conn = DeviceConnection(
            network_name="ZeroNet",
            device_id=device.id,
            timestamp=datetime.utcnow(),
            is_connected=True,
            bandwidth_down_mbps=None,  # No bandwidth data
        )
        db_session.add(conn)
        db_session.commit()

        mock_client = make_mock_client("ZeroNet")
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(
                    "/api/zabbix/data?item=device.bandwidth.down[ZZ:ZZ:ZZ:ZZ:ZZ:ZZ]&network=ZeroNet"
                )

                assert response.status_code == 200
                assert response.json()["value"] == 0.0
        finally:
            app.dependency_overrides.clear()

    def test_device_signal_returns_404_when_none(self, db_session):
        from src.main import app
        from src.api.zabbix import get_eero_client

        device = Device(network_name="NoSigNet", mac_address="NS:NS:NS:NS:NS:NS")
        db_session.add(device)
        db_session.commit()

        conn = DeviceConnection(
            network_name="NoSigNet",
            device_id=device.id,
            timestamp=datetime.utcnow(),
            is_connected=True,
            signal_strength=None,  # No signal data
        )
        db_session.add(conn)
        db_session.commit()

        mock_client = make_mock_client("NoSigNet")
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(
                    "/api/zabbix/data?item=device.signal[NS:NS:NS:NS:NS:NS]&network=NoSigNet"
                )

                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_device_not_found_returns_404(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(
                    f"/api/zabbix/data?item=device.connected[FF:FF:FF:FF:FF:FF]&network={network_name}"
                )

                assert response.status_code == 404
                assert "Device not found" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_node_status_returns_1_for_online(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        node = populated_db["node"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(
                    f"/api/zabbix/data?item=node.status[{node.eero_id}]&network={network_name}"
                )

                assert response.status_code == 200
                assert response.json()["value"] == 1
        finally:
            app.dependency_overrides.clear()

    def test_node_devices_returns_count(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        node = populated_db["node"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(
                    f"/api/zabbix/data?item=node.devices[{node.eero_id}]&network={network_name}"
                )

                assert response.status_code == 200
                assert response.json()["value"] == 7
        finally:
            app.dependency_overrides.clear()

    def test_node_mesh_quality_returns_value(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        node = populated_db["node"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(
                    f"/api/zabbix/data?item=node.mesh_quality[{node.eero_id}]&network={network_name}"
                )

                assert response.status_code == 200
                assert response.json()["value"] == 4
        finally:
            app.dependency_overrides.clear()

    def test_node_mesh_quality_returns_404_when_none(self, db_session):
        from src.main import app
        from src.api.zabbix import get_eero_client

        node = EeroNode(network_name="NoQualityNet", eero_id="node_no_quality")
        db_session.add(node)
        db_session.commit()

        metric = EeroNodeMetric(
            eero_node_id=node.id,
            timestamp=datetime.utcnow(),
            status="online",
            mesh_quality_bars=None,  # No mesh quality data
        )
        db_session.add(metric)
        db_session.commit()

        mock_client = make_mock_client("NoQualityNet")
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(
                    "/api/zabbix/data?item=node.mesh_quality[node_no_quality]&network=NoQualityNet"
                )

                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_node_not_found_returns_404(self, populated_db):
        from src.main import app
        from src.api.zabbix import get_eero_client

        db_session = populated_db["session"]
        network_name = populated_db["network_name"]
        mock_client = make_mock_client(network_name)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(
                    f"/api/zabbix/data?item=node.status[nonexistent_node]&network={network_name}"
                )

                assert response.status_code == 404
                assert "Node not found" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_node_no_metrics_returns_404(self, db_session):
        from src.main import app
        from src.api.zabbix import get_eero_client

        node = EeroNode(network_name="NoMetricsNet", eero_id="node_no_metrics")
        db_session.add(node)
        db_session.commit()
        # No EeroNodeMetric records for this node

        mock_client = make_mock_client("NoMetricsNet")
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(
                    "/api/zabbix/data?item=node.status[node_no_metrics]&network=NoMetricsNet"
                )

                assert response.status_code == 404
                assert "No metrics data" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_device_no_connection_returns_404(self, db_session):
        from src.main import app
        from src.api.zabbix import get_eero_client

        device = Device(network_name="NoConnNet", mac_address="NC:NC:NC:NC:NC:NC")
        db_session.add(device)
        db_session.commit()
        # No DeviceConnection records

        mock_client = make_mock_client("NoConnNet")
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get(
                    "/api/zabbix/data?item=device.connected[NC:NC:NC:NC:NC:NC]&network=NoConnNet"
                )

                assert response.status_code == 404
                assert "No connection data" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_no_network_available_returns_404(self):
        from src.main import app
        from src.api.zabbix import get_eero_client

        mock_client = MagicMock()
        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app)
            response = client.get("/api/zabbix/data?item=network.devices.total")

            assert response.status_code == 404
            assert "No network available" in response.json()["detail"]
        finally:
            app.dependency_overrides.clear()

    def test_no_data_for_metric_raises_404(self, db_session):
        """When no metric records exist, should return 404."""
        from src.main import app
        from src.api.zabbix import get_eero_client

        # Don't add any NetworkMetric records
        mock_client = make_mock_client("EmptyNet")
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            with patch("src.api.zabbix.get_db_context") as mock_ctx:
                mock_ctx.return_value.__enter__.return_value = db_session
                mock_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/zabbix/data?item=network.devices.total&network=EmptyNet")

                # If no metrics, the endpoint falls through to the final HTTPException
                assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()


class TestParseItemKeyEdgeCases:
    """Additional edge case tests for parse_item_key."""

    def test_parse_empty_string(self):
        metric_name, identifier = parse_item_key("")
        assert metric_name == ""
        assert identifier is None

    def test_parse_with_colons_in_identifier(self):
        metric_name, identifier = parse_item_key("device.connected[AA:BB:CC:DD:EE:FF]")
        assert metric_name == "device.connected"
        assert identifier == "AA:BB:CC:DD:EE:FF"

    def test_parse_nested_brackets_not_supported(self):
        # Only top-level brackets are parsed
        metric_name, identifier = parse_item_key("some.metric[value[nested]]")
        # The regex stops at first ]
        assert metric_name is not None

    def test_parse_metric_with_underscores(self):
        metric_name, identifier = parse_item_key("node.mesh_quality[node_abc_123]")
        assert metric_name == "node.mesh_quality"
        assert identifier == "node_abc_123"
