"""Tests for api/web.py - Web UI routes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.web import _is_version_newer


class TestIsVersionNewer:
    """Tests for the _is_version_newer utility function."""

    def test_newer_major_version(self):
        assert _is_version_newer("3.0.0", "2.9.9") is True

    def test_newer_minor_version(self):
        assert _is_version_newer("2.5.0", "2.4.9") is True

    def test_newer_patch_version(self):
        assert _is_version_newer("2.4.5", "2.4.4") is True

    def test_same_version_is_not_newer(self):
        assert _is_version_newer("2.4.4", "2.4.4") is False

    def test_older_version_is_not_newer(self):
        assert _is_version_newer("2.4.3", "2.4.4") is False

    def test_older_major_version_is_not_newer(self):
        assert _is_version_newer("1.99.99", "2.0.0") is False

    def test_handles_two_part_version(self):
        assert _is_version_newer("3.0", "2.9.9") is True

    def test_handles_invalid_version_string(self):
        assert _is_version_newer("not-a-version", "2.4.4") is False

    def test_handles_empty_string(self):
        assert _is_version_newer("", "2.4.4") is False

    def test_handles_none_gracefully(self):
        assert _is_version_newer(None, "2.4.4") is False


def make_mock_client(authenticated: bool = True, network_name: str = "TestHome"):
    """Create a mock EeroClientWrapper."""
    mock = MagicMock()
    mock.is_authenticated.return_value = authenticated
    if authenticated:
        mock_net = MagicMock()
        mock_net.name = network_name
        mock.get_networks.return_value = [mock_net]
    else:
        mock.get_networks.return_value = None
    return mock


@pytest.fixture
def test_client():
    """Create a TestClient with mocked dependencies."""
    from src.main import app
    return TestClient(app, raise_server_exceptions=False)


class TestDashboardRoute:
    """Tests for the / (dashboard) route."""

    def test_redirects_to_setup_when_not_authenticated(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = make_mock_client(authenticated=False)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True, follow_redirects=False)
            response = client.get("/")
            assert response.status_code == 302
            assert "/setup" in response.headers["location"]
        finally:
            app.dependency_overrides.clear()

    def test_renders_dashboard_when_authenticated(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = make_mock_client(authenticated=True)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True)
            response = client.get("/")
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
        finally:
            app.dependency_overrides.clear()

    def test_dashboard_handles_dict_network(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client.get_networks.return_value = [{"name": "DictNetwork"}]
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True)
            response = client.get("/")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_dashboard_handles_empty_networks(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = MagicMock()
        mock_client.is_authenticated.return_value = True
        mock_client.get_networks.return_value = []
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True)
            response = client.get("/")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()


class TestDevicesRoute:
    """Tests for /devices route."""

    def test_redirects_to_setup_when_not_authenticated(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = make_mock_client(authenticated=False)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True, follow_redirects=False)
            response = client.get("/devices")
            assert response.status_code == 302
            assert "/setup" in response.headers["location"]
        finally:
            app.dependency_overrides.clear()

    def test_renders_devices_page_when_authenticated(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = make_mock_client(authenticated=True)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True)
            response = client.get("/devices")
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
        finally:
            app.dependency_overrides.clear()


class TestNetworkRoute:
    """Tests for /network route."""

    def test_redirects_to_setup_when_not_authenticated(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = make_mock_client(authenticated=False)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True, follow_redirects=False)
            response = client.get("/network")
            assert response.status_code == 302
        finally:
            app.dependency_overrides.clear()

    def test_renders_network_page_when_authenticated(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = make_mock_client(authenticated=True)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True)
            response = client.get("/network")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()


class TestNodesRoute:
    """Tests for /nodes route."""

    def test_redirects_to_setup_when_not_authenticated(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = make_mock_client(authenticated=False)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True, follow_redirects=False)
            response = client.get("/nodes")
            assert response.status_code == 302
        finally:
            app.dependency_overrides.clear()

    def test_renders_nodes_page_when_authenticated(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = make_mock_client(authenticated=True)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True)
            response = client.get("/nodes")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()


class TestReportsRoute:
    """Tests for /reports route."""

    def test_redirects_to_setup_when_not_authenticated(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = make_mock_client(authenticated=False)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True, follow_redirects=False)
            response = client.get("/reports")
            assert response.status_code == 302
        finally:
            app.dependency_overrides.clear()

    def test_renders_reports_page_when_authenticated(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = make_mock_client(authenticated=True)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True)
            response = client.get("/reports")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()


class TestSettingsRoute:
    """Tests for /settings route."""

    def test_redirects_to_setup_when_not_authenticated(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = make_mock_client(authenticated=False)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True, follow_redirects=False)
            response = client.get("/settings")
            assert response.status_code == 302
        finally:
            app.dependency_overrides.clear()

    def test_renders_settings_page_when_authenticated(self):
        from src.main import app
        from src.api.web import get_eero_client

        mock_client = make_mock_client(authenticated=True)
        app.dependency_overrides[get_eero_client] = lambda: mock_client

        try:
            client = TestClient(app, raise_server_exceptions=True)
            response = client.get("/settings")
            assert response.status_code == 200
        finally:
            app.dependency_overrides.clear()


class TestCheckUpdateRoute:
    """Tests for /api/check-update route."""

    def test_returns_json_on_success(self):
        from src.main import app

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v3.0.0",
            "html_url": "https://github.com/Yeraze/eeroVista/releases/tag/v3.0.0",
        }

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)

        with patch("src.api.web.httpx.AsyncClient", return_value=mock_http_client), \
             patch("src.api.web._version_check_cache", None), \
             patch("src.api.web._version_check_time", None):
            client = TestClient(app)
            response = client.get("/api/check-update")

            assert response.status_code == 200
            data = response.json()
            assert "update_available" in data
            assert "current_version" in data
            assert "latest_version" in data

    def test_returns_json_on_github_api_failure(self):
        from src.main import app

        mock_response = MagicMock()
        mock_response.status_code = 503

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)

        with patch("src.api.web.httpx.AsyncClient", return_value=mock_http_client), \
             patch("src.api.web._version_check_cache", None), \
             patch("src.api.web._version_check_time", None):
            client = TestClient(app)
            response = client.get("/api/check-update")

            assert response.status_code == 200
            data = response.json()
            assert data["update_available"] is False
            assert "error" in data

    def test_returns_json_on_exception(self):
        from src.main import app

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(side_effect=Exception("Connection refused"))
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)

        with patch("src.api.web.httpx.AsyncClient", return_value=mock_http_client), \
             patch("src.api.web._version_check_cache", None), \
             patch("src.api.web._version_check_time", None):
            client = TestClient(app)
            response = client.get("/api/check-update")

            assert response.status_code == 200
            data = response.json()
            assert data["update_available"] is False
            assert "error" in data

    def test_uses_cached_result_within_interval(self):
        from datetime import datetime
        from src.main import app

        cached_result = {
            "update_available": True,
            "current_version": "2.0.0",
            "latest_version": "3.0.0",
            "release_url": "https://github.com/example",
        }

        with patch("src.api.web._version_check_cache", cached_result), \
             patch("src.api.web._version_check_time", datetime.now()):
            client = TestClient(app)
            response = client.get("/api/check-update")

            assert response.status_code == 200
            data = response.json()
            assert data["update_available"] is True

    def test_detects_newer_version(self):
        from src.main import app
        from src import __version__

        # Use a version much higher than current
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "tag_name": "v999.0.0",
            "html_url": "https://github.com/release",
        }

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_response)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)

        with patch("src.api.web.httpx.AsyncClient", return_value=mock_http_client), \
             patch("src.api.web._version_check_cache", None), \
             patch("src.api.web._version_check_time", None):
            client = TestClient(app)
            response = client.get("/api/check-update")

            assert response.status_code == 200
            data = response.json()
            assert data["update_available"] is True
            assert data["latest_version"] == "999.0.0"
