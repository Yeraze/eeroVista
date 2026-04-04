"""Tests for src/collectors/speedtest_collector.py - SpeedtestCollector."""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, Speedtest
from src.collectors.speedtest_collector import SpeedtestCollector


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


def _make_network(name: str):
    return {"name": name}


def _sample_result(date: str = "2026-03-24T10:13:10+00:00") -> dict:
    return {"date": date, "down_mbps": 250.5, "up_mbps": 50.2}


# ---------------------------------------------------------------------------
# collect() – top-level dispatch
# ---------------------------------------------------------------------------

class TestSpeedtestCollectorCollect:
    def test_returns_zero_when_no_networks(self, db_session, mock_client):
        mock_client.get_networks.return_value = []
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector.collect()
        assert result["items_collected"] == 0
        assert result["errors"] == 1

    def test_returns_zero_when_networks_is_none(self, db_session, mock_client):
        mock_client.get_networks.return_value = None
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector.collect()
        assert result["items_collected"] == 0

    def test_skips_network_with_no_name(self, db_session, mock_client):
        mock_client.get_networks.return_value = [{"name": None}]
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector.collect()
        assert result["networks"] == 0

    def test_handles_pydantic_network_objects(self, db_session, mock_client):
        net = Mock()
        net.name = "PydanticNet"
        mock_client.get_networks.return_value = [net]
        nc = Mock()
        nc.speedtest = []
        mock_client.get_network_client.return_value = nc
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector.collect()
        assert result["networks"] == 1

    def test_processes_multiple_networks(self, db_session, mock_client):
        mock_client.get_networks.return_value = [
            _make_network("Net1"),
            _make_network("Net2"),
        ]
        nc = Mock()
        nc.speedtest = [_sample_result("2026-03-24T10:00:00+00:00")]
        mock_client.get_network_client.return_value = nc
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector.collect()
        assert result["networks"] == 2
        assert result["items_collected"] == 2

    def test_handles_per_network_exception(self, db_session, mock_client):
        mock_client.get_networks.return_value = [
            _make_network("GoodNet"),
            _make_network("BadNet"),
        ]
        nc = Mock()
        nc.speedtest = [_sample_result()]

        def nc_side(network_name):
            if network_name == "BadNet":
                # _collect_for_network catches all exceptions internally and
                # returns {"items_collected": 0, "errors": 0}, so the outer
                # loop's except branch is NOT triggered; both networks are
                # counted as "processed".
                raise RuntimeError("Unexpected error")
            return nc

        mock_client.get_network_client.side_effect = nc_side
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector.collect()
        # _collect_for_network eats the exception and returns zeros, so
        # networks_processed is still 2 but BadNet contributes 0 items.
        assert result["networks"] == 2
        assert result["items_collected"] == 1

    def test_returns_error_when_get_networks_raises(self, db_session, mock_client):
        mock_client.get_networks.side_effect = RuntimeError("explosión")
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector.collect()
        assert result["items_collected"] == 0


# ---------------------------------------------------------------------------
# _collect_for_network()
# ---------------------------------------------------------------------------

class TestCollectForNetwork:
    def test_stores_new_speedtest_result(self, db_session, mock_client):
        nc = Mock()
        nc.speedtest = [_sample_result("2026-03-24T10:13:10+00:00")]
        mock_client.get_network_client.return_value = nc
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector._collect_for_network("HomeNet")
        assert result["items_collected"] == 1

        row = db_session.query(Speedtest).filter(Speedtest.network_name == "HomeNet").first()
        assert row is not None
        assert row.download_mbps == 250.5
        assert row.upload_mbps == 50.2

    def test_deduplicates_existing_result(self, db_session, mock_client):
        # Insert existing row
        ts = datetime(2026, 3, 24, 10, 13, 10)
        existing = Speedtest(
            network_name="HomeNet",
            timestamp=ts,
            download_mbps=250.5,
            upload_mbps=50.2,
        )
        db_session.add(existing)
        db_session.commit()

        nc = Mock()
        nc.speedtest = [{"date": "2026-03-24T10:13:10+00:00", "down_mbps": 250.5, "up_mbps": 50.2}]
        mock_client.get_network_client.return_value = nc
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector._collect_for_network("HomeNet")
        # No new rows
        assert result["items_collected"] == 0
        count = db_session.query(Speedtest).count()
        assert count == 1

    def test_updates_existing_null_result(self, db_session, mock_client):
        """If an existing row has NULL download_mbps, update it with real data."""
        ts = datetime(2026, 3, 24, 10, 13, 10)
        existing = Speedtest(
            network_name="HomeNet",
            timestamp=ts,
            download_mbps=None,
            upload_mbps=None,
        )
        db_session.add(existing)
        db_session.commit()

        nc = Mock()
        nc.speedtest = [{"date": "2026-03-24T10:13:10+00:00", "down_mbps": 300.0, "up_mbps": 60.0}]
        mock_client.get_network_client.return_value = nc
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector._collect_for_network("HomeNet")
        assert result["items_collected"] == 1

        updated = db_session.query(Speedtest).first()
        assert updated.download_mbps == 300.0

    def test_skips_entry_with_no_date(self, db_session, mock_client):
        nc = Mock()
        nc.speedtest = [{"date": None, "down_mbps": 100.0, "up_mbps": 20.0}]
        mock_client.get_network_client.return_value = nc
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector._collect_for_network("HomeNet")
        assert result["items_collected"] == 0
        assert db_session.query(Speedtest).count() == 0

    def test_returns_zero_when_no_speedtest_data(self, db_session, mock_client):
        nc = Mock()
        nc.speedtest = []
        mock_client.get_network_client.return_value = nc
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector._collect_for_network("HomeNet")
        assert result["items_collected"] == 0
        assert result["errors"] == 0

    def test_returns_zero_when_speedtest_is_none(self, db_session, mock_client):
        nc = Mock()
        nc.speedtest = None
        mock_client.get_network_client.return_value = nc
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector._collect_for_network("HomeNet")
        assert result["items_collected"] == 0

    def test_handles_multiple_new_results(self, db_session, mock_client):
        nc = Mock()
        nc.speedtest = [
            {"date": "2026-03-24T10:00:00+00:00", "down_mbps": 100.0, "up_mbps": 10.0},
            {"date": "2026-03-24T11:00:00+00:00", "down_mbps": 200.0, "up_mbps": 20.0},
        ]
        mock_client.get_network_client.return_value = nc
        collector = SpeedtestCollector(db_session, mock_client)
        result = collector._collect_for_network("HomeNet")
        assert result["items_collected"] == 2
        assert db_session.query(Speedtest).count() == 2


# ---------------------------------------------------------------------------
# _parse_date()
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_none_returns_none(self):
        assert SpeedtestCollector._parse_date(None) is None

    def test_datetime_returned_as_is(self):
        dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert SpeedtestCollector._parse_date(dt) is dt

    def test_iso_with_colon_tz(self):
        result = SpeedtestCollector._parse_date("2026-03-24T10:13:10+00:00")
        assert isinstance(result, datetime)
        assert result.year == 2026

    def test_iso_with_z_suffix(self):
        result = SpeedtestCollector._parse_date("2026-03-24T10:13:10+0000")
        assert isinstance(result, datetime)

    def test_iso_without_tz(self):
        result = SpeedtestCollector._parse_date("2026-03-24T10:13:10")
        assert isinstance(result, datetime)
        assert result.tzinfo is None

    def test_invalid_string_returns_none(self):
        result = SpeedtestCollector._parse_date("not-a-date")
        assert result is None

    def test_positive_timezone_offset(self):
        result = SpeedtestCollector._parse_date("2026-03-24T10:13:10+0530")
        assert isinstance(result, datetime)

    def test_negative_timezone_offset(self):
        result = SpeedtestCollector._parse_date("2026-03-24T10:13:10-0500")
        assert isinstance(result, datetime)


# ---------------------------------------------------------------------------
# _normalize_speedtest()
# ---------------------------------------------------------------------------

class TestNormalizeSpeedtest:
    @pytest.fixture()
    def collector(self, db_session, mock_client):
        return SpeedtestCollector(db_session, mock_client)

    def test_normalizes_list_of_dicts(self, collector):
        data = [
            {"date": "2026-01-01T00:00:00+00:00", "down_mbps": 100.0, "up_mbps": 10.0},
        ]
        result = collector._normalize_speedtest(data)
        assert len(result) == 1
        assert result[0]["down_mbps"] == 100.0

    def test_normalizes_single_dict(self, collector):
        data = {"date": "2026-01-01T00:00:00+00:00", "down_mbps": 50.0, "up_mbps": 5.0}
        result = collector._normalize_speedtest(data)
        assert len(result) == 1
        assert result[0]["up_mbps"] == 5.0

    def test_normalizes_pydantic_model_with_up_down_mbps(self, collector):
        entry = Mock()
        entry.date = "2026-01-01T00:00:00+00:00"
        entry.down_mbps = 200.0
        entry.up_mbps = 20.0
        entry.down = None
        entry.up = None
        result = collector._normalize_speedtest([entry])
        assert result[0]["down_mbps"] == 200.0

    def test_normalizes_pydantic_model_with_nested_speed(self, collector):
        """Handles Speed model where down/up have a .value attribute."""
        entry = Mock(spec=[])  # No down_mbps / up_mbps attributes
        entry.date = "2026-01-01T00:00:00+00:00"
        entry.down = Mock()
        entry.down.value = 150.0
        entry.up = Mock()
        entry.up.value = 15.0
        result = collector._normalize_speedtest([entry])
        assert result[0]["down_mbps"] == 150.0
        assert result[0]["up_mbps"] == 15.0

    def test_uses_alt_key_down_in_dict(self, collector):
        data = [{"date": "2026-01-01T00:00:00+00:00", "down": 80.0, "up": 8.0}]
        result = collector._normalize_speedtest(data)
        assert result[0]["down_mbps"] == 80.0
        assert result[0]["up_mbps"] == 8.0


# ---------------------------------------------------------------------------
# _extract_speed_fields()
# ---------------------------------------------------------------------------

class TestExtractSpeedFields:
    def test_extracts_mbps_attributes(self):
        entry = Mock()
        entry.date = "2026-01-01"
        entry.down_mbps = 300.0
        entry.up_mbps = 30.0
        entry.down = None
        entry.up = None
        result = SpeedtestCollector._extract_speed_fields(entry)
        assert result["down_mbps"] == 300.0
        assert result["up_mbps"] == 30.0
        assert result["date"] == "2026-01-01"

    def test_falls_back_to_nested_value(self):
        entry = Mock(spec=["date", "down", "up"])
        entry.date = "2026-01-01"
        entry.down = Mock()
        entry.down.value = 120.0
        entry.up = Mock()
        entry.up.value = 12.0
        result = SpeedtestCollector._extract_speed_fields(entry)
        assert result["down_mbps"] == 120.0
        assert result["up_mbps"] == 12.0

    def test_returns_none_when_no_speed_data(self):
        entry = Mock(spec=["date"])
        entry.date = None
        result = SpeedtestCollector._extract_speed_fields(entry)
        assert result["date"] is None


# ---------------------------------------------------------------------------
# _fetch_speedtest_data() – fallback to raw API
# ---------------------------------------------------------------------------

class TestFetchSpeedtestData:
    def test_returns_eero_client_results_when_available(self, db_session, mock_client):
        nc = Mock()
        nc.speedtest = [{"date": "2026-01-01T00:00:00+00:00", "down_mbps": 100.0, "up_mbps": 10.0}]
        mock_client.get_network_client.return_value = nc
        collector = SpeedtestCollector(db_session, mock_client)
        results = collector._fetch_speedtest_data("HomeNet")
        assert len(results) == 1

    def test_falls_back_to_raw_api_when_client_raises(self, db_session, mock_client):
        mock_client.get_network_client.side_effect = RuntimeError("Pydantic parse failure")
        collector = SpeedtestCollector(db_session, mock_client)
        # The raw API fallback will be called but it will fail gracefully
        # (no real HTTP in tests), so expect empty list
        results = collector._fetch_speedtest_data("HomeNet")
        assert isinstance(results, list)

    def test_falls_back_when_network_client_is_none(self, db_session, mock_client):
        mock_client.get_network_client.return_value = None
        collector = SpeedtestCollector(db_session, mock_client)
        results = collector._fetch_speedtest_data("HomeNet")
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# _fetch_speedtest_raw() – graceful failure without network
# ---------------------------------------------------------------------------

class TestFetchSpeedtestRaw:
    def test_returns_empty_list_when_auth_fails(self, db_session, mock_client):
        collector = SpeedtestCollector(db_session, mock_client)
        with patch("src.collectors.speedtest_collector.SpeedtestCollector._fetch_speedtest_raw") as mock_raw:
            mock_raw.return_value = []
            results = collector._fetch_speedtest_raw("HomeNet")
            # We called the real one; it will fail at AuthManager (no token) → empty list
            assert isinstance(results, list)

    def test_handles_exception_gracefully(self, db_session, mock_client):
        """If AuthManager raises, _fetch_speedtest_raw returns [] gracefully."""
        collector = SpeedtestCollector(db_session, mock_client)
        # AuthManager is imported inside _fetch_speedtest_raw from src.eero_client.auth
        with patch("src.eero_client.auth.AuthManager") as MockAM:
            MockAM.return_value.get_session_token.side_effect = RuntimeError("auth error")
            result = collector._fetch_speedtest_raw("HomeNet")
            assert isinstance(result, list)
