"""Tests for src/collectors/device_collector.py - DeviceCollector."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import (
    Base,
    Device,
    DeviceConnection,
    DailyBandwidth,
    EeroNode,
    EeroNodeMetric,
)
from src.collectors.device_collector import DeviceCollector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_network(name: str) -> dict:
    return {"name": name}


def _make_eero(
    url: str = "/2.2/eeros/abc123",
    location: str = "Living Room",
    model: str = "eero Pro 6E",
    mac: str = "aa:bb:cc:dd:ee:ff",
    gateway: bool = True,
    state: str = "online",
    connection_type: str = "WIRED",
    os_version: str = "3.7.0",
    update_available: bool = False,
    connected_clients_count: int = 5,
    connected_wired_clients_count: int = 2,
    connected_wireless_clients_count: int = 3,
    mesh_quality_bars: int = None,
    last_reboot: str = None,
) -> dict:
    return {
        "url": url,
        "location": location,
        "model": model,
        "mac_address": mac,
        "gateway": gateway,
        "state": state,
        "connection_type": connection_type,
        "os_version": os_version,
        "update_available": update_available,
        "connected_clients_count": connected_clients_count,
        "connected_wired_clients_count": connected_wired_clients_count,
        "connected_wireless_clients_count": connected_wireless_clients_count,
        "mesh_quality_bars": mesh_quality_bars,
        "last_reboot": last_reboot,
        "wireless_upstream_node": None,
    }


def _make_device(
    mac: str = "11:22:33:44:55:66",
    hostname: str = "my-laptop",
    nickname: str = "My Laptop",
    manufacturer: str = "Apple Inc.",
    device_type: str = "mobile",
    connected: bool = True,
    connection_type: str = "wireless",
    ip: str = "192.168.1.50",
    is_guest: bool = False,
    usage: dict = None,
    source: dict = None,
) -> dict:
    data: dict = {
        "mac": mac,
        "hostname": hostname,
        "nickname": nickname,
        "manufacturer": manufacturer,
        "device_type": device_type,
        "connected": connected,
        "connection_type": connection_type,
        "ip": ip,
        "is_guest": is_guest,
    }
    if usage is not None:
        data["usage"] = usage
    if source is not None:
        data["source"] = source
    return data


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


@pytest.fixture()
def collector(db_session, mock_client):
    return DeviceCollector(db_session, mock_client)


# ---------------------------------------------------------------------------
# collect() – top-level dispatch
# ---------------------------------------------------------------------------

class TestDeviceCollectorCollect:
    def test_returns_zero_when_no_networks(self, db_session, mock_client):
        mock_client.get_networks.return_value = []
        collector = DeviceCollector(db_session, mock_client)
        result = collector.collect()
        assert result["items_collected"] == 0
        assert result["errors"] == 1

    def test_returns_zero_when_networks_is_none(self, db_session, mock_client):
        mock_client.get_networks.return_value = None
        collector = DeviceCollector(db_session, mock_client)
        result = collector.collect()
        assert result["items_collected"] == 0

    def test_skips_network_without_name(self, db_session, mock_client):
        mock_client.get_networks.return_value = [{"name": None}]
        collector = DeviceCollector(db_session, mock_client)
        result = collector.collect()
        assert result["networks"] == 0

    def test_processes_dict_network(self, db_session, mock_client):
        mock_client.get_networks.return_value = [_make_network("HomeNet")]
        mock_client.get_eeros.return_value = [_make_eero()]
        mock_client.get_devices.return_value = []
        mock_client.get_profiles.return_value = []
        collector = DeviceCollector(db_session, mock_client)
        result = collector.collect()
        assert result["networks"] == 1

    def test_processes_pydantic_model_network(self, db_session, mock_client):
        net = Mock()
        net.name = "OfficeNet"
        mock_client.get_networks.return_value = [net]
        mock_client.get_eeros.return_value = [_make_eero()]
        mock_client.get_devices.return_value = []
        mock_client.get_profiles.return_value = []
        collector = DeviceCollector(db_session, mock_client)
        result = collector.collect()
        assert result["networks"] == 1

    def test_accumulates_totals_across_networks(self, db_session, mock_client):
        mock_client.get_networks.return_value = [
            _make_network("Net1"),
            _make_network("Net2"),
        ]
        mock_client.get_eeros.return_value = [_make_eero()]
        mock_client.get_devices.return_value = [_make_device()]
        mock_client.get_profiles.return_value = []
        collector = DeviceCollector(db_session, mock_client)
        result = collector.collect()
        assert result["networks"] == 2
        assert result["items_collected"] == 2

    def test_handles_network_exception_gracefully(self, db_session, mock_client):
        mock_client.get_networks.return_value = [
            _make_network("GoodNet"),
            _make_network("BadNet"),
        ]
        mock_client.get_eeros.side_effect = [
            [_make_eero()],
            RuntimeError("API failure"),
        ]
        mock_client.get_devices.return_value = []
        mock_client.get_profiles.return_value = []
        collector = DeviceCollector(db_session, mock_client)
        result = collector.collect()
        assert result["errors"] >= 1

    def test_returns_error_on_get_networks_exception(self, db_session, mock_client):
        mock_client.get_networks.side_effect = RuntimeError("network error")
        collector = DeviceCollector(db_session, mock_client)
        result = collector.collect()
        assert result["items_collected"] == 0


# ---------------------------------------------------------------------------
# _collect_for_network()
# ---------------------------------------------------------------------------

class TestCollectForNetwork:
    def test_returns_error_when_no_eeros(self, db_session, mock_client):
        mock_client.get_eeros.return_value = []
        collector = DeviceCollector(db_session, mock_client)
        result = collector._collect_for_network("HomeNet")
        assert result["errors"] == 1
        assert result["items_collected"] == 0

    def test_returns_zero_when_no_devices(self, db_session, mock_client):
        mock_client.get_eeros.return_value = [_make_eero()]
        mock_client.get_devices.return_value = []
        mock_client.get_profiles.return_value = []
        collector = DeviceCollector(db_session, mock_client)
        result = collector._collect_for_network("HomeNet")
        assert result["items_collected"] == 0
        assert result["errors"] == 0

    def test_processes_device_and_stores_connection(self, db_session, mock_client):
        eero = _make_eero(url="/2.2/eeros/abc123")
        device = _make_device(
            source={"url": "/2.2/eeros/abc123", "location": "Living Room"}
        )
        mock_client.get_eeros.return_value = [eero]
        mock_client.get_devices.return_value = [device]
        mock_client.get_profiles.return_value = []
        collector = DeviceCollector(db_session, mock_client)
        result = collector._collect_for_network("HomeNet")
        assert result["items_collected"] == 1

        conn = db_session.query(DeviceConnection).first()
        assert conn is not None
        assert conn.is_connected is True

    def test_skips_non_dict_device_entries(self, db_session, mock_client):
        mock_client.get_eeros.return_value = [_make_eero()]
        mock_client.get_devices.return_value = [True, False, _make_device()]
        mock_client.get_profiles.return_value = []
        collector = DeviceCollector(db_session, mock_client)
        result = collector._collect_for_network("HomeNet")
        # Only one real dict device should be counted
        assert result["items_collected"] == 1

    def test_overlays_usage_from_profiles(self, db_session, mock_client):
        mac = "11:22:33:44:55:66"
        mock_client.get_eeros.return_value = [_make_eero()]
        mock_client.get_devices.return_value = [_make_device(mac=mac)]
        mock_client.get_profiles.return_value = [
            {
                "devices": [
                    {"mac": mac, "usage": {"down_mbps": 10.5, "up_mbps": 2.0}}
                ]
            }
        ]
        collector = DeviceCollector(db_session, mock_client)
        collector._collect_for_network("HomeNet")

        conn = db_session.query(DeviceConnection).first()
        assert conn.bandwidth_down_mbps == 10.5
        assert conn.bandwidth_up_mbps == 2.0

    def test_network_wide_bandwidth_accumulation(self, db_session, mock_client):
        """Network-wide DailyBandwidth row (device_id=None) should be created."""
        device = _make_device(usage={"down_mbps": 5.0, "up_mbps": 1.0})
        mock_client.get_eeros.return_value = [_make_eero()]
        mock_client.get_devices.return_value = [device]
        mock_client.get_profiles.return_value = []
        collector = DeviceCollector(db_session, mock_client)
        collector._collect_for_network("HomeNet")

        bw = (
            db_session.query(DailyBandwidth)
            .filter(DailyBandwidth.device_id == None)
            .first()
        )
        assert bw is not None

    def test_creates_eero_node_records(self, db_session, mock_client):
        mock_client.get_eeros.return_value = [_make_eero()]
        mock_client.get_devices.return_value = []
        mock_client.get_profiles.return_value = []
        collector = DeviceCollector(db_session, mock_client)
        collector._collect_for_network("HomeNet")

        node = db_session.query(EeroNode).first()
        assert node is not None
        assert node.location == "Living Room"

    def test_creates_eero_node_metric_records(self, db_session, mock_client):
        mock_client.get_eeros.return_value = [_make_eero()]
        mock_client.get_devices.return_value = []
        mock_client.get_profiles.return_value = []
        collector = DeviceCollector(db_session, mock_client)
        collector._collect_for_network("HomeNet")

        metric = db_session.query(EeroNodeMetric).first()
        assert metric is not None
        assert metric.status == "online"

    def test_rolls_back_on_exception(self, db_session, mock_client):
        mock_client.get_eeros.return_value = [_make_eero()]
        mock_client.get_devices.return_value = [_make_device()]
        mock_client.get_profiles.return_value = []
        collector = DeviceCollector(db_session, mock_client)

        original_commit = db_session.commit

        def bad_commit():
            raise RuntimeError("DB write error")

        db_session.commit = bad_commit
        with pytest.raises(RuntimeError):
            collector._collect_for_network("HomeNet")


# ---------------------------------------------------------------------------
# _process_eero_nodes()
# ---------------------------------------------------------------------------

class TestProcessEeroNodes:
    def test_creates_new_node(self, db_session, mock_client):
        eero = _make_eero(url="/2.2/eeros/node1", location="Kitchen")
        collector = DeviceCollector(db_session, mock_client)
        collector._process_eero_nodes([eero], "HomeNet")
        db_session.commit()

        node = db_session.query(EeroNode).filter(EeroNode.eero_id == "node1").first()
        assert node is not None
        assert node.location == "Kitchen"
        assert node.is_gateway is True

    def test_updates_existing_node(self, db_session, mock_client):
        # Pre-create node
        node = EeroNode(
            network_name="HomeNet",
            eero_id="node1",
            location="Old Location",
            model="eero 6",
        )
        db_session.add(node)
        db_session.commit()

        eero = _make_eero(url="/2.2/eeros/node1", location="New Location")
        collector = DeviceCollector(db_session, mock_client)
        collector._process_eero_nodes([eero], "HomeNet")
        db_session.commit()

        updated = db_session.query(EeroNode).filter(EeroNode.eero_id == "node1").first()
        assert updated.location == "New Location"

    def test_skips_eero_with_no_url(self, db_session, mock_client):
        eero = _make_eero(url="")
        collector = DeviceCollector(db_session, mock_client)
        node_map = collector._process_eero_nodes([eero], "HomeNet")
        assert len(node_map) == 0

    def test_returns_url_to_id_map(self, db_session, mock_client):
        eero = _make_eero(url="/2.2/eeros/node99")
        collector = DeviceCollector(db_session, mock_client)
        node_map = collector._process_eero_nodes([eero], "HomeNet")
        db_session.commit()
        assert "/2.2/eeros/node99" in node_map

    def test_location_as_dict(self, db_session, mock_client):
        eero = _make_eero(url="/2.2/eeros/node1")
        eero["location"] = {"name": "Garage"}
        collector = DeviceCollector(db_session, mock_client)
        collector._process_eero_nodes([eero], "HomeNet")
        db_session.commit()
        node = db_session.query(EeroNode).first()
        assert node.location == "Garage"

    def test_resolves_upstream_node_id(self, db_session, mock_client):
        """Satellite nodes should have their upstream_node_id resolved."""
        gateway = _make_eero(
            url="/2.2/eeros/gw",
            location="Living Room",
            gateway=True,
            connection_type="WIRED",
        )
        satellite = _make_eero(
            url="/2.2/eeros/sat",
            location="Bedroom",
            gateway=False,
            connection_type="WIRELESS",
        )
        satellite["wireless_upstream_node"] = {"name": "Living Room"}
        collector = DeviceCollector(db_session, mock_client)
        collector._process_eero_nodes([gateway, satellite], "HomeNet")
        db_session.commit()

        sat_node = db_session.query(EeroNode).filter(EeroNode.eero_id == "sat").first()
        gw_node = db_session.query(EeroNode).filter(EeroNode.eero_id == "gw").first()
        assert sat_node.upstream_node_id == gw_node.id

    def test_invalid_mesh_quality_bars_set_to_none(self, db_session, mock_client):
        eero = _make_eero(mesh_quality_bars=10)  # Out of valid range 1-5
        collector = DeviceCollector(db_session, mock_client)
        collector._process_eero_nodes([eero], "HomeNet")
        db_session.commit()
        metric = db_session.query(EeroNodeMetric).first()
        assert metric.mesh_quality_bars is None

    def test_valid_mesh_quality_bars_stored(self, db_session, mock_client):
        eero = _make_eero(mesh_quality_bars=4)
        collector = DeviceCollector(db_session, mock_client)
        collector._process_eero_nodes([eero], "HomeNet")
        db_session.commit()
        metric = db_session.query(EeroNodeMetric).first()
        assert metric.mesh_quality_bars == 4

    def test_calculates_uptime_from_last_reboot(self, db_session, mock_client):
        reboot_time = datetime.now(timezone.utc) - timedelta(hours=2)
        eero = _make_eero(last_reboot=reboot_time.isoformat())
        collector = DeviceCollector(db_session, mock_client)
        collector._process_eero_nodes([eero], "HomeNet")
        db_session.commit()
        metric = db_session.query(EeroNodeMetric).first()
        assert metric.uptime_seconds is not None
        assert metric.uptime_seconds > 0

    def test_handles_pydantic_model_eero(self, db_session, mock_client):
        """Should also handle Pydantic model (non-dict) eero objects."""
        eero = Mock()
        eero.__class__.__name__ = "EeroModel"
        eero.url = "/2.2/eeros/pydantic1"
        eero.location = Mock()
        eero.location.name = "Office"
        eero.model = "eero 6"
        eero.mac_address = "bb:bb:bb:bb:bb:bb"
        eero.gateway = True
        eero.os_version = "3.7.0"
        eero.update_available = False
        eero.state = "online"
        eero.connected_clients_count = 3
        eero.connected_wired_clients_count = 1
        eero.connected_wireless_clients_count = 2
        eero.mesh_quality_bars = 5
        eero.last_reboot = None
        eero.connection_type = "WIRED"
        eero.wireless_upstream_node = None
        eero.ethernet_status = None

        collector = DeviceCollector(db_session, mock_client)
        # Should not raise - duck-typed as non-dict
        node_map = collector._process_eero_nodes([eero], "HomeNet")
        db_session.commit()
        assert len(node_map) == 1


# ---------------------------------------------------------------------------
# _map_eero_state_to_status()
# ---------------------------------------------------------------------------

class TestMapEeroState:
    @pytest.fixture()
    def collector(self, db_session, mock_client):
        return DeviceCollector(db_session, mock_client)

    def test_online_maps_to_online(self, collector):
        assert collector._map_eero_state_to_status("online") == "online"

    def test_online_case_insensitive(self, collector):
        assert collector._map_eero_state_to_status("ONLINE") == "online"

    def test_offline_maps_to_offline(self, collector):
        assert collector._map_eero_state_to_status("offline") == "offline"

    def test_offline_case_insensitive(self, collector):
        assert collector._map_eero_state_to_status("Offline") == "offline"

    def test_unknown_state_maps_to_unknown(self, collector):
        assert collector._map_eero_state_to_status("degraded") == "unknown"

    def test_empty_state_maps_to_unknown(self, collector):
        assert collector._map_eero_state_to_status("") == "unknown"


# ---------------------------------------------------------------------------
# _process_device()
# ---------------------------------------------------------------------------

class TestProcessDevice:
    def test_skips_device_without_mac(self, db_session, mock_client):
        collector = DeviceCollector(db_session, mock_client)
        device_data = {"hostname": "no-mac"}  # No 'mac' key
        collector._process_device(device_data, {}, "HomeNet")
        assert db_session.query(Device).count() == 0

    def test_creates_new_device(self, db_session, mock_client):
        collector = DeviceCollector(db_session, mock_client)
        collector._process_device(_make_device(), {}, "HomeNet")
        db_session.flush()
        assert db_session.query(Device).count() == 1

    def test_updates_existing_device(self, db_session, mock_client):
        existing = Device(
            network_name="HomeNet",
            mac_address="11:22:33:44:55:66",
            hostname="old-name",
        )
        db_session.add(existing)
        db_session.flush()

        collector = DeviceCollector(db_session, mock_client)
        collector._process_device(
            _make_device(hostname="new-name"), {}, "HomeNet"
        )
        db_session.flush()

        updated = db_session.query(Device).first()
        assert updated.hostname == "new-name"

    def test_creates_device_connection_record(self, db_session, mock_client):
        collector = DeviceCollector(db_session, mock_client)
        collector._process_device(_make_device(), {}, "HomeNet")
        db_session.flush()
        assert db_session.query(DeviceConnection).count() == 1

    def test_sets_is_guest_on_connection(self, db_session, mock_client):
        collector = DeviceCollector(db_session, mock_client)
        collector._process_device(_make_device(is_guest=True), {}, "HomeNet")
        db_session.flush()
        conn = db_session.query(DeviceConnection).first()
        assert conn.is_guest is True

    def test_extracts_signal_strength_from_connectivity(self, db_session, mock_client):
        device = _make_device(connection_type="wireless")
        device["connectivity"] = {"signal": "-55 dBm"}
        collector = DeviceCollector(db_session, mock_client)
        collector._process_device(device, {}, "HomeNet")
        db_session.flush()
        conn = db_session.query(DeviceConnection).first()
        assert conn.signal_strength == -55

    def test_no_signal_for_wired_connection(self, db_session, mock_client):
        device = _make_device(connection_type="wired")
        device["connectivity"] = {"signal": "-55 dBm"}
        collector = DeviceCollector(db_session, mock_client)
        collector._process_device(device, {}, "HomeNet")
        db_session.flush()
        conn = db_session.query(DeviceConnection).first()
        assert conn.signal_strength is None

    def test_extracts_bandwidth_from_usage(self, db_session, mock_client):
        device = _make_device(usage={"down_mbps": 15.0, "up_mbps": 3.5})
        collector = DeviceCollector(db_session, mock_client)
        collector._process_device(device, {}, "HomeNet")
        db_session.flush()
        conn = db_session.query(DeviceConnection).first()
        assert conn.bandwidth_down_mbps == 15.0
        assert conn.bandwidth_up_mbps == 3.5

    def test_resolves_eero_node_from_source(self, db_session, mock_client):
        # Create an eero node first
        node = EeroNode(
            network_name="HomeNet",
            eero_id="node1",
            location="Living Room",
        )
        db_session.add(node)
        db_session.flush()

        eero_node_map = {"/2.2/eeros/node1": node.id}
        device = _make_device(
            source={"url": "/2.2/eeros/node1", "location": "Living Room"}
        )
        collector = DeviceCollector(db_session, mock_client)
        collector._process_device(device, eero_node_map, "HomeNet")
        db_session.flush()

        conn = db_session.query(DeviceConnection).first()
        assert conn.eero_node_id == node.id

    def test_handles_malformed_signal_string(self, db_session, mock_client):
        device = _make_device(connection_type="wireless")
        device["connectivity"] = {"signal": "bad signal"}
        collector = DeviceCollector(db_session, mock_client)
        collector._process_device(device, {}, "HomeNet")
        db_session.flush()
        conn = db_session.query(DeviceConnection).first()
        assert conn.signal_strength is None

    def test_creates_daily_bandwidth_record(self, db_session, mock_client):
        device = _make_device(usage={"down_mbps": 5.0, "up_mbps": 1.0})
        collector = DeviceCollector(db_session, mock_client)
        collector._process_device(device, {}, "HomeNet")
        db_session.flush()

        bw = db_session.query(DailyBandwidth).filter(
            DailyBandwidth.device_id != None
        ).first()
        assert bw is not None


# ---------------------------------------------------------------------------
# _guess_device_type()
# ---------------------------------------------------------------------------

class TestGuessDeviceType:
    @pytest.fixture()
    def collector(self, db_session, mock_client):
        return DeviceCollector(db_session, mock_client)

    def test_returns_device_type_field_when_present(self, collector):
        data = {"device_type": "smart_home"}
        assert collector._guess_device_type(data) == "smart_home"

    def test_guesses_mobile_for_apple_manufacturer(self, collector):
        data = {"manufacturer": "Apple Inc."}
        assert collector._guess_device_type(data) == "mobile"

    def test_guesses_mobile_for_iphone_hostname(self, collector):
        data = {"hostname": "iphone-home"}
        assert collector._guess_device_type(data) == "mobile"

    def test_guesses_mobile_for_samsung_manufacturer(self, collector):
        data = {"manufacturer": "Samsung Electronics"}
        assert collector._guess_device_type(data) == "mobile"

    def test_guesses_entertainment_for_tv_hostname(self, collector):
        # Note: "samsung" in the hostname matches mobile before "tv" matches
        # entertainment (samsung check comes first in the source). Use a
        # hostname that only triggers the tv/entertainment branch.
        data = {"hostname": "living-room-tv"}
        assert collector._guess_device_type(data) == "entertainment"

    def test_guesses_entertainment_for_roku(self, collector):
        data = {"manufacturer": "Roku Inc."}
        assert collector._guess_device_type(data) == "entertainment"

    def test_guesses_printer_for_canon(self, collector):
        data = {"manufacturer": "Canon Inc."}
        assert collector._guess_device_type(data) == "printer"

    def test_returns_unknown_for_unrecognized(self, collector):
        data = {"manufacturer": "ACME Corp"}
        assert collector._guess_device_type(data) == "unknown"

    def test_returns_unknown_for_empty_data(self, collector):
        assert collector._guess_device_type({}) == "unknown"


# ---------------------------------------------------------------------------
# _update_bandwidth_accumulation()
# ---------------------------------------------------------------------------

class TestUpdateBandwidthAccumulation:
    def test_skips_when_bandwidth_is_none(self, db_session, mock_client):
        collector = DeviceCollector(db_session, mock_client)
        collector._update_bandwidth_accumulation(
            network_name="HomeNet",
            device_id=None,
            bandwidth_down_mbps=None,
            bandwidth_up_mbps=None,
            timestamp=datetime.now(timezone.utc),
        )
        assert db_session.query(DailyBandwidth).count() == 0

    def test_creates_new_daily_bandwidth_record(self, db_session, mock_client):
        collector = DeviceCollector(db_session, mock_client)
        ts = datetime.now(timezone.utc)
        collector._update_bandwidth_accumulation(
            network_name="HomeNet",
            device_id=None,
            bandwidth_down_mbps=10.0,
            bandwidth_up_mbps=2.0,
            timestamp=ts,
        )
        db_session.flush()
        bw = db_session.query(DailyBandwidth).first()
        assert bw is not None
        assert bw.last_collection_time is not None

    def test_accumulates_bandwidth_on_second_call(self, db_session, mock_client):
        collector = DeviceCollector(db_session, mock_client)
        t1 = datetime.now(timezone.utc) - timedelta(seconds=60)
        t2 = datetime.now(timezone.utc)

        # First call – establishes baseline
        collector._update_bandwidth_accumulation("HomeNet", None, 10.0, 2.0, t1)
        db_session.flush()

        # Second call – should accumulate
        collector._update_bandwidth_accumulation("HomeNet", None, 10.0, 2.0, t2)
        db_session.flush()

        bw = db_session.query(DailyBandwidth).first()
        # Should have accumulated some MB (10 Mbps * 60s / 8 = 75 MB)
        assert bw.download_mb > 0

    def test_skips_accumulation_when_delta_exceeds_max(self, db_session, mock_client):
        """Time delta >600s should skip accumulation but still update last_collection_time."""
        collector = DeviceCollector(db_session, mock_client)
        t1 = datetime.now(timezone.utc) - timedelta(seconds=700)
        t2 = datetime.now(timezone.utc)

        collector._update_bandwidth_accumulation("HomeNet", None, 10.0, 2.0, t1)
        db_session.flush()
        bw_before = db_session.query(DailyBandwidth).first()
        download_before = bw_before.download_mb

        collector._update_bandwidth_accumulation("HomeNet", None, 10.0, 2.0, t2)
        db_session.flush()

        bw = db_session.query(DailyBandwidth).first()
        # Should NOT have accumulated
        assert bw.download_mb == download_before

    def test_logs_warning_for_large_but_acceptable_delta(self, db_session, mock_client):
        """130-600s delta: logs warning but still accumulates."""
        collector = DeviceCollector(db_session, mock_client)
        t1 = datetime.now(timezone.utc) - timedelta(seconds=130)
        t2 = datetime.now(timezone.utc)

        collector._update_bandwidth_accumulation("HomeNet", None, 5.0, 1.0, t1)
        db_session.flush()
        bw_before = db_session.query(DailyBandwidth).first()
        download_before = bw_before.download_mb

        collector._update_bandwidth_accumulation("HomeNet", None, 5.0, 1.0, t2)
        db_session.flush()

        bw = db_session.query(DailyBandwidth).first()
        # Should have accumulated (even though delta is large)
        assert bw.download_mb > download_before

    def test_handles_naive_last_collection_time(self, db_session, mock_client):
        """SQLite strips tzinfo; collector should handle naive timestamps."""
        collector = DeviceCollector(db_session, mock_client)
        t1 = datetime.now(timezone.utc) - timedelta(seconds=60)
        t2 = datetime.now(timezone.utc)

        collector._update_bandwidth_accumulation("HomeNet", None, 5.0, 1.0, t1)
        db_session.flush()

        # Manually strip tzinfo to simulate SQLite behaviour
        bw = db_session.query(DailyBandwidth).first()
        bw.last_collection_time = bw.last_collection_time.replace(tzinfo=None)
        db_session.flush()

        # Second call should not raise
        collector._update_bandwidth_accumulation("HomeNet", None, 5.0, 1.0, t2)
        db_session.flush()
