"""Tests for health analytics API endpoints (src/api/health/analytics.py)."""

import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.models.database import (
    Base,
    DailyBandwidth,
    Device,
    DeviceConnection,
    DeviceGroup,
    DeviceGroupMember,
    EeroNode,
    EeroNodeMetric,
    NetworkMetric,
)


# ---------------------------------------------------------------------------
# Low-level DB fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_session():
    """In-memory SQLite database session for tests.

    Uses StaticPool so the same in-memory database connection is shared
    across all threads (including FastAPI's async worker threads inside
    TestClient).  Without this, SQLite would create a fresh, empty DB for
    every new connection, causing "no such table" errors.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# TestClient fixtures
# ---------------------------------------------------------------------------


def _make_test_client(db_session, networks=None, raise_exc=False):
    """Build a fully-patched TestClient.

    Patches:
    - ``src.main.init_database`` / ``ensure_data_directory`` / ``get_scheduler``
      so the lifespan does not touch the filesystem or start background jobs.
    - ``src.api.health.analytics.get_db_context`` to use the in-memory session.
    - The ``get_eero_client`` FastAPI dependency to return a mock that reports
      *networks*.  Pass an empty list to simulate "no networks".
    """
    from src.main import app
    from src.api.health.models import get_eero_client

    # Build mock eero client
    mock_eero = MagicMock()
    if networks is None:
        net = MagicMock()
        net.name = "test-net"
        mock_eero.get_networks.return_value = [net]
    else:
        mock_eero.get_networks.return_value = networks

    @contextmanager
    def _db_ctx():
        yield db_session

    app.dependency_overrides[get_eero_client] = lambda: mock_eero

    stack = (
        patch("src.api.health.analytics.get_db_context", side_effect=_db_ctx),
        patch("src.main.init_database"),
        patch("src.main.ensure_data_directory"),
        patch("src.main.get_scheduler"),
    )
    return stack, app


class _PatchedClient:
    """Context manager wrapping a TestClient with all required patches active."""

    def __init__(self, db_session, networks=None, raise_exc=False):
        self._db_session = db_session
        self._networks = networks
        self._raise_exc = raise_exc
        self._patches = []
        self._tc = None

    def __enter__(self):
        from src.main import app
        from src.api.health.models import get_eero_client

        mock_eero = MagicMock()
        if self._networks is None:
            net = MagicMock()
            net.name = "test-net"
            mock_eero.get_networks.return_value = [net]
        else:
            mock_eero.get_networks.return_value = self._networks

        db = self._db_session

        @contextmanager
        def _db_ctx():
            yield db

        app.dependency_overrides[get_eero_client] = lambda: mock_eero
        self._app = app

        self._patches = [
            patch("src.api.health.analytics.get_db_context", side_effect=_db_ctx),
            patch("src.main.init_database"),
            patch("src.main.ensure_data_directory"),
            patch("src.main.get_scheduler"),
        ]
        for p in self._patches:
            mock = p.start()
            # give scheduler mock reasonable start/stop methods
            if hasattr(mock, "return_value"):
                mock.return_value.start = MagicMock()
                mock.return_value.stop = MagicMock()

        self._tc = TestClient(app, raise_server_exceptions=self._raise_exc)
        self._tc.__enter__()
        return self._tc

    def __exit__(self, *args):
        self._tc.__exit__(*args)
        for p in self._patches:
            p.stop()
        self._app.dependency_overrides.clear()


@pytest.fixture()
def app_client(db_session):
    """Fully patched TestClient for the happy path (network = 'test-net')."""
    with _PatchedClient(db_session) as client:
        yield client


@pytest.fixture()
def no_network_client(db_session):
    """Fully patched TestClient where the eero client has no networks."""
    with _PatchedClient(db_session, networks=[]) as client:
        yield client


# ---------------------------------------------------------------------------
# Database data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def seed_node(db_session):
    """Insert a single EeroNode into the test DB."""
    node = EeroNode(
        eero_id="node-abc",
        network_name="test-net",
        location="Living Room",
        model="eero Pro 6E",
        is_gateway=True,
    )
    db_session.add(node)
    db_session.commit()
    db_session.refresh(node)
    return node


@pytest.fixture()
def seed_device(db_session):
    """Insert a single Device into the test DB."""
    device = Device(
        mac_address="AA:BB:CC:DD:EE:FF",
        network_name="test-net",
        hostname="test-phone",
        nickname="John's Phone",
        device_type="phone",
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    return device


# ===========================================================================
# /api/nodes/{eero_id}/restart-history
# ===========================================================================


class TestNodeRestartHistory:
    def test_node_not_found_returns_404(self, app_client):
        resp = app_client.get("/api/nodes/nonexistent/restart-history")
        assert resp.status_code == 404

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/nodes/node-abc/restart-history")
        assert resp.status_code == 404

    def test_found_node_returns_summary(self, app_client, seed_node):
        with patch(
            "src.services.node_analysis_service.get_node_restart_summary"
        ) as mock_summary:
            mock_summary.return_value = {
                "total_restarts": 2,
                "restarts": [],
                "location": "Living Room",
                "period_days": 30,
            }
            resp = app_client.get(f"/api/nodes/{seed_node.eero_id}/restart-history")
        assert resp.status_code == 200
        assert resp.json()["total_restarts"] == 2

    def test_days_capped_at_365(self, app_client, seed_node):
        with patch(
            "src.services.node_analysis_service.get_node_restart_summary"
        ) as mock_summary:
            mock_summary.return_value = {"total_restarts": 0, "restarts": [], "period_days": 365}
            resp = app_client.get(
                f"/api/nodes/{seed_node.eero_id}/restart-history?days=9999"
            )
        assert resp.status_code == 200
        called_days = mock_summary.call_args[0][3]
        assert called_days == 365

    def test_service_exception_returns_error_payload(self, app_client, seed_node):
        with patch(
            "src.services.node_analysis_service.get_node_restart_summary",
            side_effect=RuntimeError("db error"),
        ):
            resp = app_client.get(f"/api/nodes/{seed_node.eero_id}/restart-history")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert data["total_restarts"] == 0


# ===========================================================================
# /api/nodes/restart-summary
# ===========================================================================


class TestNodesRestartSummary:
    def test_no_network_returns_empty(self, no_network_client):
        resp = no_network_client.get("/api/nodes/restart-summary")
        assert resp.status_code == 200
        assert resp.json()["nodes"] == []

    def test_returns_nodes_list(self, app_client, seed_node):
        with patch(
            "src.services.node_analysis_service.get_all_nodes_restart_counts"
        ) as mock_counts:
            mock_counts.return_value = {seed_node.id: 3}
            resp = app_client.get("/api/nodes/restart-summary")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["eero_id"] == seed_node.eero_id
        assert data["nodes"][0]["restart_count"] == 3

    def test_days_capped_at_365(self, app_client, seed_node):
        with patch(
            "src.services.node_analysis_service.get_all_nodes_restart_counts",
            return_value={},
        ):
            resp = app_client.get("/api/nodes/restart-summary?days=9999")
        assert resp.status_code == 200
        assert resp.json()["period_days"] == 365

    def test_exception_returns_error_payload(self, app_client, seed_node):
        with patch(
            "src.services.node_analysis_service.get_all_nodes_restart_counts",
            side_effect=RuntimeError("boom"),
        ):
            resp = app_client.get("/api/nodes/restart-summary")
        assert resp.status_code == 200
        assert "error" in resp.json()


# ===========================================================================
# /api/network/health-score
# ===========================================================================


class TestNetworkHealthScore:
    def test_returns_score(self, app_client):
        with patch(
            "src.services.health_score_service.compute_health_score"
        ) as mock_score:
            mock_score.return_value = {"score": 95.0, "color": "green"}
            resp = app_client.get("/api/network/health-score")
        assert resp.status_code == 200
        assert resp.json()["score"] == 95.0

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/network/health-score")
        assert resp.status_code == 404

    def test_exception_returns_error_payload(self, app_client):
        with patch(
            "src.services.health_score_service.compute_health_score",
            side_effect=RuntimeError("fail"),
        ):
            resp = app_client.get("/api/network/health-score")
        assert resp.status_code == 200
        assert resp.json()["score"] is None


# ===========================================================================
# /api/network/health-history
# ===========================================================================


class TestNetworkHealthHistory:
    def test_returns_history_list(self, app_client):
        with patch(
            "src.services.health_score_service.compute_health_history"
        ) as mock_hist:
            mock_hist.return_value = [{"ts": "2025-01-01T00:00:00Z", "score": 90}]
            resp = app_client.get("/api/network/health-history")
        assert resp.status_code == 200
        assert len(resp.json()["history"]) == 1

    def test_hours_capped_at_720(self, app_client):
        with patch(
            "src.services.health_score_service.compute_health_history",
            return_value=[],
        ) as mock_hist:
            resp = app_client.get("/api/network/health-history?hours=9999")
        assert resp.status_code == 200
        called_hours = mock_hist.call_args[0][2]
        assert called_hours == 720

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/network/health-history")
        assert resp.status_code == 404

    def test_exception_returns_error_payload(self, app_client):
        with patch(
            "src.services.health_score_service.compute_health_history",
            side_effect=RuntimeError("oops"),
        ):
            resp = app_client.get("/api/network/health-history")
        assert resp.status_code == 200
        assert "error" in resp.json()


# ===========================================================================
# /api/network/uptime
# ===========================================================================


class TestNetworkUptime:
    def test_returns_uptime(self, app_client):
        with patch(
            "src.services.isp_reliability_service.get_uptime_stats"
        ) as mock_stats:
            mock_stats.return_value = {"uptime_24h": 99.9, "uptime_7d": 98.5}
            resp = app_client.get("/api/network/uptime")
        assert resp.status_code == 200
        assert resp.json()["uptime_24h"] == 99.9

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/network/uptime")
        assert resp.status_code == 404

    def test_exception_returns_error_payload(self, app_client):
        with patch(
            "src.services.isp_reliability_service.get_uptime_stats",
            side_effect=RuntimeError("db gone"),
        ):
            resp = app_client.get("/api/network/uptime")
        assert resp.status_code == 200
        assert "error" in resp.json()


# ===========================================================================
# /api/network/outages
# ===========================================================================


class TestNetworkOutages:
    def test_returns_outages(self, app_client):
        with patch("src.services.isp_reliability_service.detect_outages") as mock_out, \
             patch("src.services.isp_reliability_service.get_daily_uptime") as mock_du:
            mock_out.return_value = [{"start": "2025-01-01T00:00:00Z", "duration_minutes": 5}]
            mock_du.return_value = [{"date": "2025-01-01", "uptime_pct": 99.7}]
            resp = app_client.get("/api/network/outages")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["outages"]) == 1
        assert data["period_days"] == 30

    def test_days_capped_at_365(self, app_client):
        with patch("src.services.isp_reliability_service.detect_outages", return_value=[]), \
             patch("src.services.isp_reliability_service.get_daily_uptime", return_value=[]):
            resp = app_client.get("/api/network/outages?days=9999")
        assert resp.status_code == 200
        assert resp.json()["period_days"] == 365

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/network/outages")
        assert resp.status_code == 404

    def test_exception_returns_error_payload(self, app_client):
        with patch(
            "src.services.isp_reliability_service.detect_outages",
            side_effect=RuntimeError("fail"),
        ):
            resp = app_client.get("/api/network/outages")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert data["outages"] == []


# ===========================================================================
# /api/devices/{mac_address}/signal-history
# ===========================================================================


class TestDeviceSignalHistory:
    def test_returns_history(self, app_client):
        with patch(
            "src.services.signal_analysis_service.get_signal_history"
        ) as mock_hist:
            mock_hist.return_value = {
                "history": [{"ts": "2025-01-01T00:00:00Z", "signal": -55}],
                "stats": {"avg": -55},
                "trend": "stable",
            }
            resp = app_client.get("/api/devices/AA:BB:CC:DD:EE:FF/signal-history")
        assert resp.status_code == 200
        assert len(resp.json()["history"]) == 1

    def test_hours_capped_at_720(self, app_client):
        with patch(
            "src.services.signal_analysis_service.get_signal_history",
            return_value={"history": [], "stats": None, "trend": "unknown"},
        ) as mock_hist:
            resp = app_client.get(
                "/api/devices/AA:BB:CC:DD:EE:FF/signal-history?hours=9999"
            )
        assert resp.status_code == 200
        called_hours = mock_hist.call_args[0][3]
        assert called_hours == 720

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/devices/AA:BB:CC:DD:EE:FF/signal-history")
        assert resp.status_code == 404

    def test_exception_returns_error_payload(self, app_client):
        with patch(
            "src.services.signal_analysis_service.get_signal_history",
            side_effect=RuntimeError("crash"),
        ):
            resp = app_client.get("/api/devices/AA:BB:CC:DD:EE:FF/signal-history")
        assert resp.status_code == 200
        assert "error" in resp.json()


# ===========================================================================
# /api/devices/signal-summary
# ===========================================================================


class TestDevicesSignalSummary:
    def test_returns_summary(self, app_client):
        with patch(
            "src.services.signal_analysis_service.get_signal_summary"
        ) as mock_sum:
            mock_sum.return_value = {"excellent": 3, "good": 5, "fair": 1, "poor": 0}
            resp = app_client.get("/api/devices/signal-summary")
        assert resp.status_code == 200
        assert resp.json()["excellent"] == 3

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/devices/signal-summary")
        assert resp.status_code == 404

    def test_exception_returns_error_payload(self, app_client):
        with patch(
            "src.services.signal_analysis_service.get_signal_summary",
            side_effect=RuntimeError("db error"),
        ):
            resp = app_client.get("/api/devices/signal-summary")
        assert resp.status_code == 200
        assert "error" in resp.json()


# ===========================================================================
# /api/speedtest/analysis
# ===========================================================================


class TestSpeedtestAnalysis:
    def test_returns_analysis(self, app_client):
        with patch(
            "src.services.speedtest_analysis_service.get_speedtest_analysis"
        ) as mock_an:
            mock_an.return_value = {
                "avg_download": 200.0,
                "avg_upload": 50.0,
                "tests": [],
            }
            resp = app_client.get("/api/speedtest/analysis")
        assert resp.status_code == 200
        assert resp.json()["avg_download"] == 200.0

    def test_days_capped_at_365(self, app_client):
        with patch(
            "src.services.speedtest_analysis_service.get_speedtest_analysis",
            return_value={},
        ) as mock_an:
            resp = app_client.get("/api/speedtest/analysis?days=9999")
        assert resp.status_code == 200
        called_days = mock_an.call_args[0][2]
        assert called_days == 365

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/speedtest/analysis")
        assert resp.status_code == 404

    def test_exception_returns_error_payload(self, app_client):
        with patch(
            "src.services.speedtest_analysis_service.get_speedtest_analysis",
            side_effect=RuntimeError("timeout"),
        ):
            resp = app_client.get("/api/speedtest/analysis")
        assert resp.status_code == 200
        assert "error" in resp.json()


# ===========================================================================
# /api/devices/{mac_address}/bandwidth-heatmap
# ===========================================================================


class TestDeviceBandwidthHeatmap:
    def test_returns_heatmap(self, app_client):
        with patch(
            "src.services.bandwidth_heatmap_service.get_bandwidth_heatmap"
        ) as mock_hm:
            mock_hm.return_value = {"buckets": [], "days": 7}
            resp = app_client.get("/api/devices/AA:BB:CC:DD:EE:FF/bandwidth-heatmap")
        assert resp.status_code == 200

    def test_days_capped_at_14(self, app_client):
        with patch(
            "src.services.bandwidth_heatmap_service.get_bandwidth_heatmap",
            return_value={},
        ) as mock_hm:
            resp = app_client.get(
                "/api/devices/AA:BB:CC:DD:EE:FF/bandwidth-heatmap?days=99"
            )
        assert resp.status_code == 200
        called_days = mock_hm.call_args[0][3]
        assert called_days == 14

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/devices/AA:BB:CC:DD:EE:FF/bandwidth-heatmap")
        assert resp.status_code == 404

    def test_exception_returns_error_payload(self, app_client):
        with patch(
            "src.services.bandwidth_heatmap_service.get_bandwidth_heatmap",
            side_effect=RuntimeError("heatmap fail"),
        ):
            resp = app_client.get("/api/devices/AA:BB:CC:DD:EE:FF/bandwidth-heatmap")
        assert resp.status_code == 200
        assert "error" in resp.json()


# ===========================================================================
# /api/devices/{mac_address}/activity-pattern
# ===========================================================================


class TestDeviceActivityPattern:
    def test_returns_pattern(self, app_client):
        with patch(
            "src.services.activity_pattern_service.get_activity_pattern"
        ) as mock_pat:
            mock_pat.return_value = {"matrix": [[0] * 24] * 7}
            resp = app_client.get("/api/devices/AA:BB:CC:DD:EE:FF/activity-pattern")
        assert resp.status_code == 200

    def test_days_capped_at_30(self, app_client):
        with patch(
            "src.services.activity_pattern_service.get_activity_pattern",
            return_value={},
        ) as mock_pat:
            resp = app_client.get(
                "/api/devices/AA:BB:CC:DD:EE:FF/activity-pattern?days=99"
            )
        assert resp.status_code == 200
        called_days = mock_pat.call_args[0][3]
        assert called_days == 30

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/devices/AA:BB:CC:DD:EE:FF/activity-pattern")
        assert resp.status_code == 404

    def test_exception_returns_error_payload(self, app_client):
        with patch(
            "src.services.activity_pattern_service.get_activity_pattern",
            side_effect=RuntimeError("pattern fail"),
        ):
            resp = app_client.get("/api/devices/AA:BB:CC:DD:EE:FF/activity-pattern")
        assert resp.status_code == 200
        assert "error" in resp.json()


# ===========================================================================
# /api/nodes/load-analysis
# ===========================================================================


class TestNodesLoadAnalysis:
    def test_returns_load_analysis(self, app_client):
        with patch(
            "src.services.load_analysis_service.get_load_analysis"
        ) as mock_la:
            mock_la.return_value = {"nodes": [], "hours": 24}
            resp = app_client.get("/api/nodes/load-analysis")
        assert resp.status_code == 200

    def test_hours_capped_at_720(self, app_client):
        with patch(
            "src.services.load_analysis_service.get_load_analysis",
            return_value={},
        ) as mock_la:
            resp = app_client.get("/api/nodes/load-analysis?hours=9999")
        assert resp.status_code == 200
        called_hours = mock_la.call_args[0][2]
        assert called_hours == 720

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/nodes/load-analysis")
        assert resp.status_code == 404

    def test_exception_returns_error_payload(self, app_client):
        with patch(
            "src.services.load_analysis_service.get_load_analysis",
            side_effect=RuntimeError("load fail"),
        ):
            resp = app_client.get("/api/nodes/load-analysis")
        assert resp.status_code == 200
        assert "error" in resp.json()


# ===========================================================================
# /api/network/guest-usage
# ===========================================================================


class TestGuestNetworkUsage:
    def test_returns_guest_usage_empty(self, app_client):
        resp = app_client.get("/api/network/guest-usage")
        assert resp.status_code == 200
        data = resp.json()
        assert "guest_device_count" in data
        assert data["guest_device_count"] == 0

    def test_hours_parameter_accepted(self, app_client):
        resp = app_client.get("/api/network/guest-usage?hours=48")
        assert resp.status_code == 200
        assert resp.json()["hours"] == 48

    def test_hours_capped_at_720(self, app_client):
        resp = app_client.get("/api/network/guest-usage?hours=9999")
        assert resp.status_code == 200
        assert resp.json()["hours"] == 720

    def test_with_guest_device(self, app_client, db_session):
        device = Device(
            mac_address="GG:HH:II:JJ:KK:LL",
            network_name="test-net",
            hostname="guest-phone",
            device_type="phone",
        )
        db_session.add(device)
        db_session.commit()
        db_session.refresh(device)

        conn = DeviceConnection(
            timestamp=datetime.now(timezone.utc),
            network_name="test-net",
            device_id=device.id,
            is_connected=True,
            is_guest=True,
            bandwidth_down_mbps=5.0,
            bandwidth_up_mbps=1.0,
        )
        db_session.add(conn)
        db_session.commit()

        resp = app_client.get("/api/network/guest-usage")
        assert resp.status_code == 200
        assert resp.json()["guest_device_count"] >= 1

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/network/guest-usage")
        assert resp.status_code == 404

    def test_pct_of_total_with_bandwidth(self, app_client, db_session):
        """Guest and non-guest percentages must add up to 100."""
        device_main = Device(
            mac_address="11:22:33:44:55:66",
            network_name="test-net",
            hostname="main-device",
        )
        device_guest = Device(
            mac_address="AA:BB:CC:DD:11:22",
            network_name="test-net",
            hostname="guest-device",
        )
        db_session.add_all([device_main, device_guest])
        db_session.commit()

        now = datetime.now(timezone.utc)
        db_session.add(DeviceConnection(
            timestamp=now,
            network_name="test-net",
            device_id=device_main.id,
            is_connected=True,
            is_guest=False,
            bandwidth_down_mbps=10.0,
            bandwidth_up_mbps=2.0,
        ))
        db_session.add(DeviceConnection(
            timestamp=now,
            network_name="test-net",
            device_id=device_guest.id,
            is_connected=True,
            is_guest=True,
            bandwidth_down_mbps=5.0,
            bandwidth_up_mbps=1.0,
        ))
        db_session.commit()

        resp = app_client.get("/api/network/guest-usage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["guest_pct_of_total"] > 0
        assert data["non_guest_pct_of_total"] > 0
        assert abs(data["guest_pct_of_total"] + data["non_guest_pct_of_total"] - 100.0) < 1.0

    def test_pct_zero_when_no_bandwidth(self, app_client):
        """guest_pct_of_total should be 0 when no bandwidth data exists."""
        resp = app_client.get("/api/network/guest-usage")
        data = resp.json()
        assert data["guest_pct_of_total"] == 0
        assert data["non_guest_pct_of_total"] == 100


# ===========================================================================
# /api/reports/bandwidth-summary
# ===========================================================================


class TestBandwidthSummaryReport:
    def test_returns_weekly_summary(self, app_client):
        with patch(
            "src.services.bandwidth_report_service.get_bandwidth_summary"
        ) as mock_bw:
            mock_bw.return_value = {"total_download_mb": 5000.0, "total_upload_mb": 1000.0}
            resp = app_client.get("/api/reports/bandwidth-summary?period=week")
        assert resp.status_code == 200

    def test_returns_monthly_summary(self, app_client):
        with patch(
            "src.services.bandwidth_report_service.get_bandwidth_summary"
        ) as mock_bw:
            mock_bw.return_value = {"total_download_mb": 20000.0}
            resp = app_client.get("/api/reports/bandwidth-summary?period=month")
        assert resp.status_code == 200

    def test_invalid_period_returns_400(self, app_client):
        resp = app_client.get("/api/reports/bandwidth-summary?period=year")
        assert resp.status_code == 400

    def test_offset_parameter_capped_at_52(self, app_client):
        with patch(
            "src.services.bandwidth_report_service.get_bandwidth_summary",
            return_value={},
        ) as mock_bw:
            resp = app_client.get(
                "/api/reports/bandwidth-summary?period=week&offset=100"
            )
        assert resp.status_code == 200
        called_offset = mock_bw.call_args[0][3]
        assert called_offset == 52

    def test_no_network_returns_404(self, no_network_client):
        resp = no_network_client.get("/api/reports/bandwidth-summary?period=week")
        assert resp.status_code == 404

    def test_exception_returns_error_payload(self, app_client):
        with patch(
            "src.services.bandwidth_report_service.get_bandwidth_summary",
            side_effect=RuntimeError("report fail"),
        ):
            resp = app_client.get("/api/reports/bandwidth-summary?period=week")
        assert resp.status_code == 200
        assert "error" in resp.json()


# ===========================================================================
# /api/devices/{mac_address}/bandwidth-total
# ===========================================================================


class TestDeviceBandwidthTotal:
    def test_device_not_found_returns_404(self, app_client):
        resp = app_client.get("/api/devices/FF:FF:FF:FF:FF:FF/bandwidth-total")
        assert resp.status_code == 404

    def test_days_below_1_returns_400(self, app_client):
        resp = app_client.get(
            "/api/devices/AA:BB:CC:DD:EE:FF/bandwidth-total?days=0"
        )
        assert resp.status_code == 400

    def test_days_above_90_returns_400(self, app_client):
        resp = app_client.get(
            "/api/devices/AA:BB:CC:DD:EE:FF/bandwidth-total?days=91"
        )
        assert resp.status_code == 400

    def test_returns_totals_no_records(self, app_client, seed_device):
        resp = app_client.get(
            f"/api/devices/{seed_device.mac_address}/bandwidth-total?days=7"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["totals"]["download_mb"] == 0.0
        assert data["totals"]["upload_mb"] == 0.0
        assert len(data["daily_breakdown"]) == 7

    def test_returns_totals_with_records(self, app_client, db_session, seed_device):
        today = date.today()
        db_session.add(DailyBandwidth(
            network_name="test-net",
            device_id=seed_device.id,
            date=today,
            download_mb=1024.0,
            upload_mb=512.0,
        ))
        db_session.commit()

        resp = app_client.get(
            f"/api/devices/{seed_device.mac_address}/bandwidth-total?days=7"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["totals"]["download_mb"] == 1024.0
        assert data["totals"]["upload_mb"] == 512.0
        assert data["totals"]["total_mb"] == 1536.0

    def test_daily_breakdown_fills_zeros_for_missing_days(self, app_client, seed_device):
        resp = app_client.get(
            f"/api/devices/{seed_device.mac_address}/bandwidth-total?days=3"
        )
        assert resp.status_code == 200
        breakdown = resp.json()["daily_breakdown"]
        assert len(breakdown) == 3
        for entry in breakdown:
            assert "date" in entry
            assert "download_mb" in entry

    def test_today_is_marked_incomplete(self, app_client, db_session, seed_device):
        today = date.today()
        db_session.add(DailyBandwidth(
            network_name="test-net",
            device_id=seed_device.id,
            date=today,
            download_mb=100.0,
            upload_mb=50.0,
        ))
        db_session.commit()

        resp = app_client.get(
            f"/api/devices/{seed_device.mac_address}/bandwidth-total?days=1"
        )
        data = resp.json()
        assert data["daily_breakdown"][0]["is_incomplete"] is True

    def test_no_network_returns_404(self, no_network_client, seed_device):
        resp = no_network_client.get(
            f"/api/devices/{seed_device.mac_address}/bandwidth-total"
        )
        assert resp.status_code == 404

    def test_response_structure(self, app_client, seed_device):
        resp = app_client.get(
            f"/api/devices/{seed_device.mac_address}/bandwidth-total"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "device" in data
        assert "period" in data
        assert "totals" in data
        assert "daily_breakdown" in data
        assert data["device"]["mac_address"] == seed_device.mac_address

    def test_device_name_fallback_chain(self, app_client, db_session):
        """Device name falls back through nickname -> hostname -> manufacturer -> mac."""
        # Device with only manufacturer (no nickname/hostname)
        device = Device(
            mac_address="CC:CC:CC:CC:CC:CC",
            network_name="test-net",
            manufacturer="Apple",
        )
        db_session.add(device)
        db_session.commit()

        resp = app_client.get(
            f"/api/devices/{device.mac_address}/bandwidth-total?days=1"
        )
        assert resp.status_code == 200
        assert resp.json()["device"]["name"] == "Apple"


# ===========================================================================
# /api/network/bandwidth-total
# ===========================================================================


class TestNetworkBandwidthTotal:
    def test_returns_totals_no_records(self, app_client):
        resp = app_client.get("/api/network/bandwidth-total?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totals"]["download_mb"] == 0.0
        assert len(data["daily_breakdown"]) == 7

    def test_days_below_1_returns_400(self, app_client):
        resp = app_client.get("/api/network/bandwidth-total?days=0")
        assert resp.status_code == 400

    def test_days_above_90_returns_400(self, app_client):
        resp = app_client.get("/api/network/bandwidth-total?days=91")
        assert resp.status_code == 400

    def test_with_daily_records(self, app_client, db_session, seed_device):
        today = date.today()
        db_session.add(DailyBandwidth(
            network_name="test-net",
            device_id=seed_device.id,
            date=today,
            download_mb=2000.0,
            upload_mb=500.0,
        ))
        db_session.commit()

        resp = app_client.get("/api/network/bandwidth-total?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totals"]["download_mb"] >= 2000.0

    def test_no_network_returns_empty_payload(self, no_network_client):
        resp = no_network_client.get("/api/network/bandwidth-total")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totals"]["download_mb"] == 0
        assert data["daily_breakdown"] == []

    def test_response_structure(self, app_client):
        resp = app_client.get("/api/network/bandwidth-total")
        assert resp.status_code == 200
        data = resp.json()
        assert "period" in data
        assert "totals" in data
        assert "daily_breakdown" in data

    def test_daily_breakdown_length_matches_days(self, app_client):
        for days in (1, 7, 30):
            resp = app_client.get(f"/api/network/bandwidth-total?days={days}")
            assert resp.status_code == 200
            assert len(resp.json()["daily_breakdown"]) == days


# ===========================================================================
# /api/network/bandwidth-top-devices
# ===========================================================================


class TestNetworkBandwidthTopDevices:
    def test_returns_empty_with_no_data(self, app_client):
        resp = app_client.get("/api/network/bandwidth-top-devices")
        assert resp.status_code == 200
        data = resp.json()
        assert "devices" in data
        assert "other" in data

    def test_days_below_1_returns_400(self, app_client):
        resp = app_client.get("/api/network/bandwidth-top-devices?days=0")
        assert resp.status_code == 400

    def test_days_above_90_returns_400(self, app_client):
        resp = app_client.get("/api/network/bandwidth-top-devices?days=91")
        assert resp.status_code == 400

    def test_limit_below_1_returns_400(self, app_client):
        resp = app_client.get("/api/network/bandwidth-top-devices?limit=0")
        assert resp.status_code == 400

    def test_limit_above_20_returns_400(self, app_client):
        resp = app_client.get("/api/network/bandwidth-top-devices?limit=21")
        assert resp.status_code == 400

    def test_no_network_returns_empty_payload(self, no_network_client):
        resp = no_network_client.get("/api/network/bandwidth-top-devices")
        assert resp.status_code == 200
        assert resp.json()["devices"] == []

    def test_with_device_data(self, app_client, db_session, seed_device):
        today = date.today()
        db_session.add(DailyBandwidth(
            network_name="test-net",
            device_id=seed_device.id,
            date=today,
            download_mb=500.0,
            upload_mb=100.0,
        ))
        db_session.commit()

        resp = app_client.get("/api/network/bandwidth-top-devices?days=7&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["devices"]) >= 1
        assert data["devices"][0]["total_mb"] > 0

    def test_grouped_devices_aggregated(self, app_client, db_session):
        device_a = Device(
            mac_address="D1:D1:D1:D1:D1:D1",
            network_name="test-net",
            hostname="laptop-wifi",
        )
        device_b = Device(
            mac_address="D2:D2:D2:D2:D2:D2",
            network_name="test-net",
            hostname="laptop-eth",
        )
        db_session.add_all([device_a, device_b])
        db_session.commit()

        group = DeviceGroup(network_name="test-net", name="My Laptop")
        db_session.add(group)
        db_session.commit()

        db_session.add(DeviceGroupMember(group_id=group.id, device_id=device_a.id))
        db_session.add(DeviceGroupMember(group_id=group.id, device_id=device_b.id))
        db_session.commit()

        today = date.today()
        db_session.add(DailyBandwidth(
            network_name="test-net",
            device_id=device_a.id,
            date=today,
            download_mb=300.0,
            upload_mb=60.0,
        ))
        db_session.add(DailyBandwidth(
            network_name="test-net",
            device_id=device_b.id,
            date=today,
            download_mb=200.0,
            upload_mb=40.0,
        ))
        db_session.commit()

        resp = app_client.get("/api/network/bandwidth-top-devices?days=7")
        assert resp.status_code == 200
        data = resp.json()
        group_entry = next(
            (d for d in data["devices"] if d.get("name") == "My Laptop"), None
        )
        assert group_entry is not None
        assert group_entry["total_mb"] == pytest.approx(600.0, abs=1.0)

    def test_response_includes_other_category(self, app_client):
        resp = app_client.get("/api/network/bandwidth-top-devices")
        data = resp.json()
        assert "other" in data
        assert "device_count" in data["other"]
        assert "total_mb" in data["other"]

    def test_daily_arrays_length_matches_days(self, app_client, db_session, seed_device):
        today = date.today()
        db_session.add(DailyBandwidth(
            network_name="test-net",
            device_id=seed_device.id,
            date=today,
            download_mb=100.0,
            upload_mb=20.0,
        ))
        db_session.commit()

        days = 5
        resp = app_client.get(f"/api/network/bandwidth-top-devices?days={days}")
        data = resp.json()
        for device_entry in data["devices"]:
            assert len(device_entry["daily_download"]) == days
            assert len(device_entry["daily_upload"]) == days


# ===========================================================================
# /api/network/bandwidth-hourly
# ===========================================================================


class TestNetworkBandwidthHourly:
    def test_returns_24_hour_slots(self, app_client):
        # Clear cache so we always hit the DB
        from src.api.health import analytics
        analytics._bandwidth_cache.clear()

        resp = app_client.get("/api/network/bandwidth-hourly")
        assert resp.status_code == 200
        data = resp.json()
        assert "hourly_breakdown" in data
        assert len(data["hourly_breakdown"]) == 24

    def test_no_network_returns_empty(self, no_network_client):
        resp = no_network_client.get("/api/network/bandwidth-hourly")
        assert resp.status_code == 200
        assert resp.json()["hourly_breakdown"] == []

    def test_response_structure(self, app_client):
        from src.api.health import analytics
        analytics._bandwidth_cache.clear()

        resp = app_client.get("/api/network/bandwidth-hourly")
        data = resp.json()
        assert "period" in data
        assert "totals" in data
        assert "hourly_breakdown" in data

    def test_hourly_entries_have_required_fields(self, app_client):
        from src.api.health import analytics
        analytics._bandwidth_cache.clear()

        resp = app_client.get("/api/network/bandwidth-hourly")
        breakdown = resp.json()["hourly_breakdown"]
        if breakdown:
            entry = breakdown[0]
            assert "hour" in entry
            assert "hour_label" in entry
            assert "download_mb" in entry
            assert "upload_mb" in entry

    def test_caching_returns_same_data(self, app_client):
        """Second request for the same period must return cached data."""
        from src.api.health import analytics
        analytics._bandwidth_cache.clear()

        resp1 = app_client.get("/api/network/bandwidth-hourly")
        resp2 = app_client.get("/api/network/bandwidth-hourly")
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json() == resp2.json()

    def test_with_connection_data(self, app_client, db_session, seed_device):
        from src.api.health import analytics
        analytics._bandwidth_cache.clear()

        now = datetime.now(timezone.utc)
        db_session.add(DeviceConnection(
            timestamp=now,
            network_name="test-net",
            device_id=seed_device.id,
            is_connected=True,
            bandwidth_down_mbps=10.0,
            bandwidth_up_mbps=2.0,
        ))
        db_session.commit()

        resp = app_client.get("/api/network/bandwidth-hourly")
        assert resp.status_code == 200
        data = resp.json()
        assert data["totals"]["total_mb"] >= 0

    def test_totals_aggregate_all_hours(self, app_client):
        from src.api.health import analytics
        analytics._bandwidth_cache.clear()

        resp = app_client.get("/api/network/bandwidth-hourly")
        data = resp.json()
        breakdown = data["hourly_breakdown"]
        total_dl = sum(h["download_mb"] for h in breakdown)
        total_up = sum(h["upload_mb"] for h in breakdown)
        assert data["totals"]["download_mb"] == pytest.approx(total_dl, abs=0.01)
        assert data["totals"]["upload_mb"] == pytest.approx(total_up, abs=0.01)


# ===========================================================================
# get_network_name_filter helper (models module)
# ===========================================================================


class TestGetNetworkNameFilter:
    def test_explicit_network_is_returned_directly(self):
        from src.api.health.models import get_network_name_filter

        client = MagicMock()
        result = get_network_name_filter("my-net", client)
        assert result == "my-net"
        client.get_networks.assert_not_called()

    def test_no_networks_returns_none(self):
        from src.api.health.models import get_network_name_filter

        client = MagicMock()
        client.get_networks.return_value = []
        result = get_network_name_filter(None, client)
        assert result is None

    def test_first_network_dict_returned(self):
        from src.api.health.models import get_network_name_filter

        client = MagicMock()
        client.get_networks.return_value = [
            {"name": "first-net"},
            {"name": "second-net"},
        ]
        result = get_network_name_filter(None, client)
        assert result == "first-net"

    def test_first_network_object_returned(self):
        from src.api.health.models import get_network_name_filter

        client = MagicMock()
        net = MagicMock()
        net.name = "obj-net"
        client.get_networks.return_value = [net]
        result = get_network_name_filter(None, client)
        assert result == "obj-net"

    def test_explicit_network_overrides_first_network(self):
        from src.api.health.models import get_network_name_filter

        client = MagicMock()
        net = MagicMock()
        net.name = "default-net"
        client.get_networks.return_value = [net]
        result = get_network_name_filter("explicit-net", client)
        assert result == "explicit-net"


# ===========================================================================
# Cache TTL / eviction behaviour
# ===========================================================================


class TestBandwidthCacheBehaviour:
    def test_expired_cache_entries_are_cleaned(self, app_client):
        """Expired entries should be evicted before the cache is consulted."""
        from src.api.health import analytics

        analytics._bandwidth_cache["stale-key"] = (
            {"hourly_breakdown": []},
            time.time() - 1,  # expired 1 second ago
        )
        resp = app_client.get("/api/network/bandwidth-hourly")
        assert resp.status_code == 200
        assert "stale-key" not in analytics._bandwidth_cache

    def test_valid_cache_entry_is_served(self, app_client):
        """A non-expired cache entry must be served without hitting the DB."""
        from src.api.health import analytics

        cached_payload = {
            "period": {"date": "2025-01-01", "timezone": "UTC",
                       "start_time": None, "end_time": None},
            "totals": {"download_mb": 42.0, "upload_mb": 0.0, "total_mb": 42.0},
            "hourly_breakdown": [{"hour": 0, "hour_label": "00:00",
                                  "download_mb": 42.0, "upload_mb": 0.0}] * 24,
        }
        # Use a key that matches what the endpoint will build for "test-net" today
        from datetime import date as _date
        cache_key = f"test-net_{_date.today().isoformat()}"
        analytics._bandwidth_cache[cache_key] = (
            cached_payload,
            time.time() + 9999,  # far future expiry
        )

        resp = app_client.get("/api/network/bandwidth-hourly")
        assert resp.status_code == 200
        assert resp.json()["totals"]["download_mb"] == 42.0

    def test_cache_ttl_constant_is_300(self):
        from src.api.health.models import CACHE_TTL_SECONDS

        assert CACHE_TTL_SECONDS == 300
