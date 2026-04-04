"""Tests for src/collectors/network_collector.py - NetworkCollector."""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, NetworkMetric
from src.collectors.network_collector import NetworkCollector


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def mock_client():
    client = Mock()
    client.is_authenticated.return_value = True
    return client


def _make_network(name: str) -> dict:
    return {"name": name}


def _make_network_client(
    status: str = "connected",
    guest_enabled: bool = False,
    connection_mode: str = "automatic",
) -> Mock:
    nc = Mock()
    nc.networks = {
        "status": status,
        "guest_network": {"enabled": guest_enabled},
        "connection": {"mode": connection_mode},
    }
    return nc


# ---------------------------------------------------------------------------
# collect() – top-level dispatch
# ---------------------------------------------------------------------------

class TestNetworkCollectorCollect:
    def test_returns_zero_when_no_networks(self, db_session, mock_client):
        mock_client.get_networks.return_value = []
        collector = NetworkCollector(db_session, mock_client)
        result = collector.collect()
        assert result["items_collected"] == 0
        assert result["errors"] == 1

    def test_returns_zero_when_networks_is_none(self, db_session, mock_client):
        mock_client.get_networks.return_value = None
        collector = NetworkCollector(db_session, mock_client)
        result = collector.collect()
        assert result["items_collected"] == 0

    def test_processes_dict_networks(self, db_session, mock_client):
        mock_client.get_networks.return_value = [_make_network("HomeNet")]
        mock_client.get_devices.return_value = []
        mock_client.get_network_client.return_value = _make_network_client()
        collector = NetworkCollector(db_session, mock_client)
        result = collector.collect()
        assert result["items_collected"] == 1
        assert result["networks"] == 1

    def test_processes_pydantic_model_networks(self, db_session, mock_client):
        """Networks returned as objects with .name attribute."""
        net = Mock()
        net.name = "OfficeNet"
        mock_client.get_networks.return_value = [net]
        mock_client.get_devices.return_value = []
        mock_client.get_network_client.return_value = _make_network_client()
        collector = NetworkCollector(db_session, mock_client)
        result = collector.collect()
        assert result["networks"] == 1

    def test_skips_network_with_no_name(self, db_session, mock_client):
        mock_client.get_networks.return_value = [{"name": None}]
        collector = NetworkCollector(db_session, mock_client)
        result = collector.collect()
        assert result["networks"] == 0

    def test_handles_multiple_networks(self, db_session, mock_client):
        mock_client.get_networks.return_value = [
            _make_network("Net1"),
            _make_network("Net2"),
        ]
        mock_client.get_devices.return_value = []
        mock_client.get_network_client.return_value = _make_network_client()
        collector = NetworkCollector(db_session, mock_client)
        result = collector.collect()
        assert result["networks"] == 2
        assert result["items_collected"] == 2

    def test_accumulates_errors_per_network(self, db_session, mock_client):
        mock_client.get_networks.return_value = [
            _make_network("GoodNet"),
            _make_network("BadNet"),
        ]
        mock_client.get_devices.return_value = []

        def get_nc(network_name):
            if network_name == "BadNet":
                raise RuntimeError("API failure")
            return _make_network_client()

        mock_client.get_network_client.side_effect = get_nc
        collector = NetworkCollector(db_session, mock_client)
        result = collector.collect()
        assert result["errors"] == 1
        assert result["networks"] == 1  # Only GoodNet succeeded

    def test_returns_error_when_get_networks_raises(self, db_session, mock_client):
        mock_client.get_networks.side_effect = RuntimeError("network down")
        collector = NetworkCollector(db_session, mock_client)
        result = collector.collect()
        assert result["items_collected"] == 0
        assert result["errors"] == 1


# ---------------------------------------------------------------------------
# _collect_for_network()
# ---------------------------------------------------------------------------

class TestCollectForNetwork:
    def test_stores_network_metric_in_db(self, db_session, mock_client):
        mock_client.get_devices.return_value = [
            {"connected": True},
            {"connected": False},
        ]
        mock_client.get_network_client.return_value = _make_network_client(
            status="connected",
            guest_enabled=True,
            connection_mode="bridge",
        )
        collector = NetworkCollector(db_session, mock_client)
        collector._collect_for_network("HomeNet")

        metric = db_session.query(NetworkMetric).filter(
            NetworkMetric.network_name == "HomeNet"
        ).first()
        assert metric is not None
        assert metric.total_devices == 2
        assert metric.total_devices_online == 1
        assert metric.guest_network_enabled is True
        assert metric.wan_status == "online"
        assert metric.connection_mode == "bridge"

    def test_returns_error_when_network_client_missing(self, db_session, mock_client):
        mock_client.get_devices.return_value = []
        mock_client.get_network_client.return_value = None
        collector = NetworkCollector(db_session, mock_client)
        result = collector._collect_for_network("GhostNet")
        assert result["errors"] == 1
        assert result["items_collected"] == 0

    def test_handles_no_devices(self, db_session, mock_client):
        mock_client.get_devices.return_value = None
        mock_client.get_network_client.return_value = _make_network_client()
        collector = NetworkCollector(db_session, mock_client)
        result = collector._collect_for_network("EmptyNet")
        assert result["items_collected"] == 1
        metric = db_session.query(NetworkMetric).first()
        assert metric.total_devices == 0
        assert metric.total_devices_online == 0

    def test_handles_pydantic_device_objects(self, db_session, mock_client):
        """Devices returned as objects with .connected attribute."""
        dev1 = Mock()
        dev1.connected = True
        dev2 = Mock()
        dev2.connected = False
        mock_client.get_devices.return_value = [dev1, dev2]
        mock_client.get_network_client.return_value = _make_network_client()
        collector = NetworkCollector(db_session, mock_client)
        result = collector._collect_for_network("ModelNet")
        metric = db_session.query(NetworkMetric).first()
        assert metric.total_devices == 2
        assert metric.total_devices_online == 1

    def test_handles_missing_guest_network_key(self, db_session, mock_client):
        nc = Mock()
        nc.networks = {"status": "connected"}  # No guest_network key
        mock_client.get_devices.return_value = []
        mock_client.get_network_client.return_value = nc
        collector = NetworkCollector(db_session, mock_client)
        result = collector._collect_for_network("Net")
        metric = db_session.query(NetworkMetric).first()
        assert metric.guest_network_enabled is False

    def test_handles_missing_connection_key(self, db_session, mock_client):
        nc = Mock()
        nc.networks = {"status": "connected", "guest_network": {"enabled": False}}
        mock_client.get_devices.return_value = []
        mock_client.get_network_client.return_value = nc
        collector = NetworkCollector(db_session, mock_client)
        collector._collect_for_network("Net")
        metric = db_session.query(NetworkMetric).first()
        assert metric.connection_mode is None

    def test_raises_on_unexpected_db_error(self, db_session, mock_client):
        """_collect_for_network should re-raise after rollback."""
        mock_client.get_devices.return_value = []
        nc = _make_network_client()
        mock_client.get_network_client.return_value = nc
        collector = NetworkCollector(db_session, mock_client)
        # Force db.add to blow up
        original_add = db_session.add

        def bad_add(obj):
            if isinstance(obj, NetworkMetric):
                raise RuntimeError("DB write failure")
            original_add(obj)

        db_session.add = bad_add
        with pytest.raises(RuntimeError, match="DB write failure"):
            collector._collect_for_network("Net")


# ---------------------------------------------------------------------------
# _map_wan_status()
# ---------------------------------------------------------------------------

class TestMapWanStatus:
    @pytest.fixture()
    def collector(self, db_session, mock_client):
        return NetworkCollector(db_session, mock_client)

    def test_connected_maps_to_online(self, collector):
        assert collector._map_wan_status("connected") == "online"

    def test_connected_case_insensitive(self, collector):
        assert collector._map_wan_status("CONNECTED") == "online"

    def test_disconnected_maps_to_offline(self, collector):
        assert collector._map_wan_status("disconnected") == "offline"

    def test_disconnected_case_insensitive(self, collector):
        assert collector._map_wan_status("Disconnected") == "offline"

    def test_unknown_status_maps_to_unknown(self, collector):
        assert collector._map_wan_status("degraded") == "unknown"

    def test_empty_string_maps_to_unknown(self, collector):
        assert collector._map_wan_status("") == "unknown"
