"""Tests for the health API routes (src/api/health/routes.py)."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.models.database import (
    Base,
    Config,
    Device,
    DeviceConnection,
    EeroNode,
    EeroNodeMetric,
    IpReservation,
    NetworkMetric,
    PortForward,
    Speedtest,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_engine():
    """Create a fresh in-memory SQLite engine for testing.

    Uses StaticPool so that every session (including those created inside
    get_db_context() during the request) shares the same underlying connection
    and therefore sees the same tables and rows.  Without StaticPool each new
    connection to 'sqlite:///:memory:' is an independent empty database, which
    causes 'no such table' errors when route handlers open their own session.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session_factory(db_engine):
    """Return a sessionmaker bound to the in-memory engine."""
    return sessionmaker(bind=db_engine)


@pytest.fixture(autouse=True)
def override_db_engine(db_engine, db_session_factory):
    """Point the global database module at the test engine for every test.

    This ensures that get_db_context() calls inside route handlers open
    sessions on the same StaticPool in-memory database that the test uses,
    so they see the tables and rows created by the test fixtures.
    """
    import src.utils.database as db_module
    original_engine = db_module._engine
    original_factory = db_module._SessionLocal
    db_module._engine = db_engine
    db_module._SessionLocal = db_session_factory
    yield
    db_module._engine = original_engine
    db_module._SessionLocal = original_factory


@pytest.fixture
def db_session(db_session_factory):
    """Create an in-memory SQLite database session for testing."""
    session = db_session_factory()
    yield session
    session.close()


@pytest.fixture
def mock_client():
    """Return a mock EeroClientWrapper that reports as authenticated."""
    client = MagicMock()
    client.is_authenticated.return_value = True
    client.get_networks.return_value = [{"name": "test-network", "url": None, "nickname_label": None, "created": None}]
    return client


def make_db_ctx_patcher(session_factory):
    """
    Return a context-manager factory compatible with get_db_context().

    Routes call  ``with get_db_context() as db:``  so we need a callable that
    returns an object with __enter__/__exit__.  Using side_effect (not
    return_value) avoids the stale mock-return-value problem when the same
    patch is used across multiple ``with`` blocks inside one route.
    """
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _ctx


@pytest.fixture
def sample_data(db_session):
    """Populate the in-memory DB with a representative set of records."""
    # Network metric
    net_metric = NetworkMetric(
        timestamp=datetime.now(timezone.utc),
        network_name="test-network",
        total_devices=5,
        total_devices_online=3,
        wan_status="online",
        guest_network_enabled=False,
        connection_mode="automatic",
    )
    db_session.add(net_metric)

    # Speedtest
    speedtest = Speedtest(
        timestamp=datetime.now(timezone.utc),
        network_name="test-network",
        download_mbps=200.0,
        upload_mbps=100.0,
        latency_ms=10.5,
        jitter_ms=2.1,
        server_location="New York",
        isp="Comcast",
    )
    db_session.add(speedtest)

    # Eero node (gateway)
    node = EeroNode(
        eero_id="eero-001",
        network_name="test-network",
        location="Living Room",
        model="eero Pro 6E",
        is_gateway=True,
        os_version="6.17.0",
        update_available=False,
        mac_address="AA:BB:CC:DD:EE:01",
    )
    db_session.add(node)
    db_session.commit()  # commit so node.id is populated

    # Node metric
    node_metric = EeroNodeMetric(
        timestamp=datetime.now(timezone.utc),
        eero_node_id=node.id,
        status="online",
        connected_device_count=3,
        connected_wired_count=1,
        connected_wireless_count=2,
        mesh_quality_bars=5,
        uptime_seconds=172800,
    )
    db_session.add(node_metric)

    # Device
    device = Device(
        mac_address="11:22:33:44:55:66",
        network_name="test-network",
        hostname="test-laptop",
        nickname="My Laptop",
        device_type="laptop",
        manufacturer="Dell",
        aliases=json.dumps(["laptop", "work-machine"]),
    )
    db_session.add(device)
    db_session.commit()

    # Device connection (connected)
    connection = DeviceConnection(
        timestamp=datetime.now(timezone.utc),
        network_name="test-network",
        device_id=device.id,
        is_connected=True,
        connection_type="wireless",
        signal_strength=-50,
        bandwidth_down_mbps=50.0,
        bandwidth_up_mbps=20.0,
        eero_node_id=node.id,
        ip_address="192.168.1.100",
    )
    db_session.add(connection)

    # IP reservation
    reservation = IpReservation(
        network_name="test-network",
        mac_address="11:22:33:44:55:66",
        ip_address="192.168.1.100",
        description="My Laptop",
    )
    db_session.add(reservation)

    # Port forward
    port_forward = PortForward(
        network_name="test-network",
        ip_address="192.168.1.100",
        gateway_port=8080,
        client_port=80,
        protocol="tcp",
        description="Web server",
        enabled=True,
    )
    db_session.add(port_forward)

    # Config entry
    config = Config(
        key="last_collection_device",
        value=datetime.now(timezone.utc).isoformat(),
    )
    db_session.add(config)

    db_session.commit()

    return {
        "net_metric": net_metric,
        "speedtest": speedtest,
        "node": node,
        "node_metric": node_metric,
        "device": device,
        "connection": connection,
        "reservation": reservation,
        "port_forward": port_forward,
    }


# ---------------------------------------------------------------------------
# Helper to build a TestClient with dependencies overridden
# ---------------------------------------------------------------------------


def make_client(mock_eero_client, db_session_override):
    """
    Return a FastAPI TestClient with get_eero_client and get_db overridden.

    The routes use two injection strategies:
    - FastAPI Depends(get_eero_client) / Depends(get_db)  -> override via app.dependency_overrides
    - get_db_context() context manager called directly inside route bodies -> patch via unittest.mock
    """
    from src.main import app
    from src.api.health.models import get_eero_client
    from src.utils.database import get_db

    app.dependency_overrides[get_eero_client] = lambda: mock_eero_client
    app.dependency_overrides[get_db] = lambda: db_session_override

    client = TestClient(app, raise_server_exceptions=False)
    yield client

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Tests for GET /api/health."""

    def test_health_returns_200(self, mock_client, db_session):
        """Health endpoint should return 200 with core keys."""
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_scheduler = MagicMock()
        mock_scheduler.get_health_status.return_value = {
            "device_collector": {"healthy": True},
        }

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with (
                patch("src.api.health.routes.get_db_context") as mock_db_ctx,
                patch("src.scheduler.jobs.get_scheduler") as mock_get_sched,
            ):
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None
                mock_get_sched.return_value = mock_scheduler

                client = TestClient(app)
                response = client.get("/api/health")

            assert response.status_code == 200
            data = response.json()
            assert "status" in data
            assert "version" in data
            assert "uptime_seconds" in data
            assert "database" in data
            assert "eero_api" in data
        finally:
            app.dependency_overrides.clear()

    def test_health_authenticated_eero_status(self, mock_client, db_session):
        """When eero client is authenticated, eero_api should be 'authenticated'."""
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.is_authenticated.return_value = True
        mock_scheduler = MagicMock()
        mock_scheduler.get_health_status.return_value = {}

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with (
                patch("src.api.health.routes.get_db_context") as mock_db_ctx,
                patch("src.scheduler.jobs.get_scheduler") as mock_get_sched,
            ):
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None
                mock_get_sched.return_value = mock_scheduler

                client = TestClient(app)
                response = client.get("/api/health")

            assert response.json()["eero_api"] == "authenticated"
        finally:
            app.dependency_overrides.clear()

    def test_health_unhealthy_collector_degrades_status(self, mock_client, db_session):
        """When a collector is unhealthy, overall status should be 'degraded'."""
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_scheduler = MagicMock()
        mock_scheduler.get_health_status.return_value = {
            "device_collector": {"healthy": False},
        }

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with (
                patch("src.api.health.routes.get_db_context") as mock_db_ctx,
                patch("src.scheduler.jobs.get_scheduler") as mock_get_sched,
            ):
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None
                mock_get_sched.return_value = mock_scheduler

                client = TestClient(app)
                response = client.get("/api/health")

            assert response.json()["status"] == "degraded"
        finally:
            app.dependency_overrides.clear()

    def test_health_db_error_degrades_status(self, mock_client, db_session):
        """Database failure should degrade overall status."""
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_scheduler = MagicMock()
        mock_scheduler.get_health_status.return_value = {}

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with (
                patch("src.api.health.routes.get_db_context") as mock_db_ctx,
                patch("src.scheduler.jobs.get_scheduler") as mock_get_sched,
            ):
                mock_db_ctx.return_value.__enter__.side_effect = Exception("DB down")
                mock_get_sched.return_value = mock_scheduler

                client = TestClient(app)
                response = client.get("/api/health")

            data = response.json()
            assert data["database"] == "error"
            assert data["status"] == "degraded"
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/networks
# ---------------------------------------------------------------------------


class TestNetworksEndpoint:
    """Tests for GET /api/networks."""

    def _setup(self, app, mock_client, db_session):
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session

    def test_networks_returns_list(self, mock_client, db_session):
        from src.main import app

        self._setup(app, mock_client, db_session)
        try:
            client = TestClient(app)
            response = client.get("/api/networks")
            assert response.status_code == 200
            data = response.json()
            assert "networks" in data
            assert "count" in data
            assert data["count"] == 1
            assert data["networks"][0]["name"] == "test-network"
        finally:
            app.dependency_overrides.clear()

    def test_networks_not_authenticated_returns_401(self, mock_client, db_session):
        from src.main import app

        mock_client.is_authenticated.return_value = False
        self._setup(app, mock_client, db_session)
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/networks")
            assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_networks_empty_returns_zero_count(self, mock_client, db_session):
        from src.main import app

        mock_client.get_networks.return_value = []
        self._setup(app, mock_client, db_session)
        try:
            client = TestClient(app)
            response = client.get("/api/networks")
            data = response.json()
            assert data["count"] == 0
            assert data["networks"] == []
        finally:
            app.dependency_overrides.clear()

    def test_networks_exception_returns_500(self, mock_client, db_session):
        from src.main import app

        mock_client.get_networks.side_effect = RuntimeError("boom")
        self._setup(app, mock_client, db_session)
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/networks")
            assert response.status_code == 500
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/dashboard-stats
# ---------------------------------------------------------------------------


class TestDashboardStatsEndpoint:
    """Tests for GET /api/dashboard-stats."""

    def test_dashboard_stats_with_data(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/dashboard-stats")

            assert response.status_code == 200
            data = response.json()
            assert data["devices_total"] == 5
            assert data["devices_online"] == 3
            assert data["wan_status"] == "online"
        finally:
            app.dependency_overrides.clear()

    def test_dashboard_stats_no_network_returns_zeroes(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/dashboard-stats")

            assert response.status_code == 200
            data = response.json()
            assert data["devices_total"] == 0
            assert data["wan_status"] == "unknown"
        finally:
            app.dependency_overrides.clear()

    def test_dashboard_stats_empty_db(self, mock_client, db_session):
        """When there's no data for the network, should return zeroes."""
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/dashboard-stats")

            assert response.status_code == 200
            data = response.json()
            assert data["last_update"] is None
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/network/summary
# ---------------------------------------------------------------------------


class TestNetworkSummaryEndpoint:
    """Tests for GET /api/network/summary."""

    def test_summary_with_data(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/network/summary")

            assert response.status_code == 200
            data = response.json()
            assert "nodes" in data
            assert len(data["nodes"]) >= 1
            assert data["total_devices"] == 5
        finally:
            app.dependency_overrides.clear()

    def test_summary_no_network(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/network/summary")

            assert response.status_code == 200
            data = response.json()
            assert data["nodes"] == []
            assert data["total_devices"] == 0
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/nodes
# ---------------------------------------------------------------------------


class TestNodesEndpoint:
    """Tests for GET /api/nodes."""

    def test_nodes_returns_list(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/nodes")

            assert response.status_code == 200
            data = response.json()
            assert data["total"] >= 1
            node = data["nodes"][0]
            assert node["eero_id"] == "eero-001"
            assert node["location"] == "Living Room"
            assert node["is_gateway"] is True
            assert node["status"] == "online"
        finally:
            app.dependency_overrides.clear()

    def test_nodes_no_network_returns_empty(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/nodes")

            data = response.json()
            assert data["nodes"] == []
            assert data["total"] == 0
        finally:
            app.dependency_overrides.clear()

    def test_nodes_explicit_network_param(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/nodes?network=test-network")

            assert response.status_code == 200
            data = response.json()
            assert data["total"] >= 1
        finally:
            app.dependency_overrides.clear()

    def test_nodes_without_metric_fallback(self, mock_client, db_session, sample_data):
        """Nodes without any metric should report 'unknown' status."""
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        # Add a second node with no metric
        bare_node = EeroNode(
            eero_id="eero-002",
            network_name="test-network",
            location="Bedroom",
            model="eero",
            is_gateway=False,
        )
        db_session.add(bare_node)
        db_session.commit()

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/nodes")

            data = response.json()
            node_ids = [n["eero_id"] for n in data["nodes"]]
            assert "eero-002" in node_ids
            # The bare node should have status unknown
            bare = next(n for n in data["nodes"] if n["eero_id"] == "eero-002")
            assert bare["status"] == "unknown"
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/devices
# ---------------------------------------------------------------------------


class TestDevicesEndpoint:
    """Tests for GET /api/devices."""

    def test_devices_returns_data(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/devices")

            assert response.status_code == 200
            data = response.json()
            assert "devices" in data
            assert "total" in data
        finally:
            app.dependency_overrides.clear()

    def test_devices_no_network(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/devices")

            data = response.json()
            assert data["devices"] == []
            assert data["total"] == 0
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/devices/{mac_address}/aliases  (GET + PUT)
# ---------------------------------------------------------------------------


class TestDeviceAliasesEndpoints:
    """Tests for device alias CRUD endpoints."""

    def test_get_aliases_success(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/devices/11:22:33:44:55:66/aliases")

            assert response.status_code == 200
            data = response.json()
            assert data["mac_address"] == "11:22:33:44:55:66"
            assert "laptop" in data["aliases"]
        finally:
            app.dependency_overrides.clear()

    def test_get_aliases_device_not_found(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app, raise_server_exceptions=False)
                response = client.get("/api/devices/FF:FF:FF:FF:FF:FF/aliases")

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_get_aliases_no_network(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app, raise_server_exceptions=False)
                response = client.get("/api/devices/11:22:33:44:55:66/aliases")

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_put_aliases_success(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with (
                patch("src.api.health.routes.get_db_context") as mock_db_ctx,
                patch("src.services.dns_service.update_dns_hosts"),
            ):
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.put(
                    "/api/devices/11:22:33:44:55:66/aliases",
                    json={"aliases": ["new-alias", "another"]},
                )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "new-alias" in data["aliases"]
        finally:
            app.dependency_overrides.clear()

    def test_put_aliases_invalid_alias_skipped(self, mock_client, db_session, sample_data):
        """Aliases with special characters should be silently dropped."""
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with (
                patch("src.api.health.routes.get_db_context") as mock_db_ctx,
                patch("src.services.dns_service.update_dns_hosts"),
            ):
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.put(
                    "/api/devices/11:22:33:44:55:66/aliases",
                    json={"aliases": ["valid-name", "bad alias!!", "good_one"]},
                )

            assert response.status_code == 200
            data = response.json()
            # "bad alias!!" has a space and !, should be dropped
            assert "bad alias!!" not in data["aliases"]
            assert "valid-name" in data["aliases"]
        finally:
            app.dependency_overrides.clear()

    def test_put_aliases_device_not_found(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app, raise_server_exceptions=False)
                response = client.put(
                    "/api/devices/FF:FF:FF:FF:FF:FF/aliases",
                    json={"aliases": ["test"]},
                )

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_put_aliases_no_network(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app, raise_server_exceptions=False)
                response = client.put(
                    "/api/devices/11:22:33:44:55:66/aliases",
                    json={"aliases": ["test"]},
                )

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/devices/{mac_address}/bandwidth-history
# ---------------------------------------------------------------------------


class TestDeviceBandwidthHistoryEndpoint:
    """Tests for GET /api/devices/{mac}/bandwidth-history."""

    def test_bandwidth_history_success(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/devices/11:22:33:44:55:66/bandwidth-history")

            assert response.status_code == 200
            data = response.json()
            assert data["mac_address"] == "11:22:33:44:55:66"
            assert "history" in data
            assert "data_points" in data
        finally:
            app.dependency_overrides.clear()

    def test_bandwidth_history_hours_too_small(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/devices/11:22:33:44:55:66/bandwidth-history?hours=0")
            assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()

    def test_bandwidth_history_hours_too_large(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/devices/11:22:33:44:55:66/bandwidth-history?hours=200")
            assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()

    def test_bandwidth_history_device_not_found(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app, raise_server_exceptions=False)
                response = client.get("/api/devices/FF:FF:FF:FF:FF:FF/bandwidth-history")

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()

    def test_bandwidth_history_no_network(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app, raise_server_exceptions=False)
                response = client.get("/api/devices/11:22:33:44:55:66/bandwidth-history")

            assert response.status_code == 404
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/network/bandwidth-history
# ---------------------------------------------------------------------------


class TestNetworkBandwidthHistoryEndpoint:
    """Tests for GET /api/network/bandwidth-history."""

    def test_network_bandwidth_history_success(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/network/bandwidth-history")

            assert response.status_code == 200
            data = response.json()
            assert "history" in data
            assert "hours" in data
            assert data["hours"] == 24
        finally:
            app.dependency_overrides.clear()

    def test_network_bandwidth_history_invalid_hours(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/network/bandwidth-history?hours=0")
            assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()

    def test_network_bandwidth_history_no_network(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/network/bandwidth-history")

            assert response.status_code == 200
            data = response.json()
            assert data["data_points"] == 0
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/routing/reservations
# ---------------------------------------------------------------------------


class TestRoutingReservationsEndpoint:
    """Tests for GET /api/routing/reservations."""

    def test_reservations_returns_data(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            response = client.get("/api/routing/reservations")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 1
            assert data["reservations"][0]["mac_address"] == "11:22:33:44:55:66"
            assert data["reservations"][0]["ip_address"] == "192.168.1.100"
        finally:
            app.dependency_overrides.clear()

    def test_reservations_no_network_returns_empty(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            response = client.get("/api/routing/reservations")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 0
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/routing/port-forwards
# ---------------------------------------------------------------------------


class TestRoutingPortForwardsEndpoint:
    """Tests for GET /api/routing/port-forwards."""

    def test_port_forwards_returns_data(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            response = client.get("/api/routing/port-forwards")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 1
            fwd = data["forwards"][0]
            assert fwd["gateway_port"] == 8080
            assert fwd["protocol"] == "tcp"
        finally:
            app.dependency_overrides.clear()

    def test_port_forwards_no_network_returns_empty(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            response = client.get("/api/routing/port-forwards")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 0
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/routing/reservation/{mac_address}
# ---------------------------------------------------------------------------


class TestReservationByMacEndpoint:
    """Tests for GET /api/routing/reservation/{mac_address}."""

    def test_reservation_found(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            response = client.get("/api/routing/reservation/11:22:33:44:55:66")

            assert response.status_code == 200
            data = response.json()
            assert data["reserved"] is True
            assert data["ip_address"] == "192.168.1.100"
        finally:
            app.dependency_overrides.clear()

    def test_reservation_not_found(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            response = client.get("/api/routing/reservation/AA:BB:CC:DD:EE:FF")

            assert response.status_code == 200
            data = response.json()
            assert data["reserved"] is False
        finally:
            app.dependency_overrides.clear()

    def test_reservation_no_network(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            response = client.get("/api/routing/reservation/11:22:33:44:55:66")

            assert response.status_code == 200
            data = response.json()
            assert data["reserved"] is False
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/routing/forwards/{ip_address}
# ---------------------------------------------------------------------------


class TestForwardsByIpEndpoint:
    """Tests for GET /api/routing/forwards/{ip_address}."""

    def test_forwards_by_ip_found(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            response = client.get("/api/routing/forwards/192.168.1.100")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 1
            assert data["forwards"][0]["gateway_port"] == 8080
        finally:
            app.dependency_overrides.clear()

    def test_forwards_by_ip_not_found(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            response = client.get("/api/routing/forwards/10.0.0.1")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 0
        finally:
            app.dependency_overrides.clear()

    def test_forwards_by_ip_no_network(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            response = client.get("/api/routing/forwards/192.168.1.100")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 0
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/collection-status
# ---------------------------------------------------------------------------


class TestCollectionStatusEndpoint:
    """Tests for GET /api/collection-status."""

    def test_collection_status_with_config(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/collection-status")

            assert response.status_code == 200
            data = response.json()
            assert "collections" in data
        finally:
            app.dependency_overrides.clear()

    def test_collection_status_empty_db(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/collection-status")

            assert response.status_code == 200
            data = response.json()
            # All collectors should be None when no config exists
            for key in ["device", "network", "speedtest"]:
                assert data["collections"].get(key) is None
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/network-topology
# ---------------------------------------------------------------------------


class TestNetworkTopologyEndpoint:
    """Tests for GET /api/network-topology."""

    def test_topology_returns_nodes_and_devices(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/network-topology")

            assert response.status_code == 200
            data = response.json()
            assert "nodes" in data
            assert "devices" in data
            assert "mesh_links" in data
            # Internet node always added
            node_ids = [n["id"] for n in data["nodes"]]
            assert "internet" in node_ids
        finally:
            app.dependency_overrides.clear()

    def test_topology_no_network(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/network-topology")

            assert response.status_code == 200
            data = response.json()
            assert data["nodes"] == []
            assert data["devices"] == []
        finally:
            app.dependency_overrides.clear()

    def test_topology_gateway_creates_internet_link(self, mock_client, db_session, sample_data):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/network-topology")

            data = response.json()
            link_sources = [lnk["source"] for lnk in data["mesh_links"]]
            assert "internet" in link_sources
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/firmware-update
# ---------------------------------------------------------------------------


class TestFirmwareUpdateEndpoint:
    """Tests for GET /api/firmware-update."""

    def test_firmware_update_no_update(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_firmware_update_info.return_value = None
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/firmware-update")

            assert response.status_code == 200
            data = response.json()
            assert data["has_update"] is False
        finally:
            app.dependency_overrides.clear()

    def test_firmware_update_with_update(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_firmware_update_info.return_value = {
            "has_update": True,
            "target_firmware": "6.18.0",
            "manifest_resource": "https://example.com/manifest.json",
        }
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/firmware-update")

            assert response.status_code == 200
            data = response.json()
            assert data["has_update"] is True
            assert data["target_firmware"] == "6.18.0"
        finally:
            app.dependency_overrides.clear()

    def test_firmware_update_no_network(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.get("/api/firmware-update")

            assert response.status_code == 200
            data = response.json()
            assert data["has_update"] is False
            assert "error" in data
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/database/cleanup
# ---------------------------------------------------------------------------


class TestDatabaseCleanupEndpoint:
    """Tests for POST /api/database/cleanup."""

    def test_cleanup_not_authenticated(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.is_authenticated.return_value = False
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app, raise_server_exceptions=False)
                response = client.post("/api/database/cleanup")

            assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_cleanup_no_networks(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app, raise_server_exceptions=False)
                response = client.post("/api/database/cleanup")

            assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()

    def test_cleanup_no_unauthorized_networks(self, mock_client, db_session, sample_data):
        """When all DB networks are authorized, nothing gets deleted."""
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        # sample_data already put "test-network" in DB; mock_client also returns it
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.post("/api/database/cleanup")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["removed_networks"] == []
        finally:
            app.dependency_overrides.clear()

    def test_cleanup_removes_unauthorized_network(self, mock_client, db_session):
        """When a DB network is not in the authorized list, it gets removed."""
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        # Add data for an "old-network" not in the mock_client's network list
        old_metric = NetworkMetric(
            timestamp=datetime.now(timezone.utc),
            network_name="old-network",
            total_devices=1,
            total_devices_online=0,
            wan_status="offline",
        )
        db_session.add(old_metric)
        db_session.commit()

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            with patch("src.api.health.routes.get_db_context") as mock_db_ctx:
                mock_db_ctx.return_value.__enter__.return_value = db_session
                mock_db_ctx.return_value.__exit__.return_value = None

                client = TestClient(app)
                response = client.post("/api/database/cleanup")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "old-network" in data["removed_networks"]
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: /api/support/package
# ---------------------------------------------------------------------------


class TestSupportPackageEndpoint:
    """Tests for GET /api/support/package."""

    def test_support_package_not_authenticated(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.is_authenticated.return_value = False
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/support/package")
            assert response.status_code == 401
        finally:
            app.dependency_overrides.clear()

    def test_support_package_no_networks(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/support/package")
            assert response.status_code == 400
        finally:
            app.dependency_overrides.clear()

    def test_support_package_success(self, mock_client, db_session):
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_eeros.return_value = [{"id": "e1"}]
        mock_client.get_devices.return_value = [{"mac": "aa:bb:cc:dd:ee:ff"}]
        mock_client.get_profiles.return_value = []

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            response = client.get("/api/support/package")

            assert response.status_code == 200
            data = response.json()
            assert "generated_at" in data
            assert "version" in data
            assert "networks" in data
            assert len(data["networks"]) == 1
        finally:
            app.dependency_overrides.clear()

    def test_support_package_eero_api_failure_handled(self, mock_client, db_session):
        """If sub-calls to the eero API fail, errors are recorded per-network."""
        from src.main import app
        from src.api.health.models import get_eero_client
        from src.utils.database import get_db

        mock_client.get_eeros.side_effect = RuntimeError("eero API down")
        mock_client.get_devices.return_value = []
        mock_client.get_profiles.return_value = []

        app.dependency_overrides[get_eero_client] = lambda: mock_client
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            response = client.get("/api/support/package")

            assert response.status_code == 200
            data = response.json()
            network_entry = data["networks"][0]
            assert len(network_entry["errors"]) >= 1
        finally:
            app.dependency_overrides.clear()
