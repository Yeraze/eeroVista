"""Tests for the MCP server (src/mcp_server)."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.transport_security import TransportSecurityMiddleware

from src.config import Settings
from src.mcp_server import build_mcp_server
from src.mcp_server import server as mcp_module
from src.mcp_server.server import _build_transport_security

# The full curated tool set the server is expected to expose.
EXPECTED_TOOLS = {
    "dashboard_stats",
    "network_summary",
    "list_devices",
    "list_nodes",
    "collection_status",
    "firmware_status",
    "health_score",
    "wan_uptime",
    "recent_outages",
    "speedtest_analysis",
    "signal_summary",
    "top_bandwidth_devices",
}


@pytest.mark.asyncio
async def test_all_curated_tools_registered():
    """The server registers exactly the curated read-only tool set."""
    mcp = build_mcp_server("/mcp")
    tools = await mcp.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_top_bandwidth_devices_schema():
    """Tools surface their optional arguments in the input schema."""
    mcp = build_mcp_server("/mcp")
    tools = await mcp.list_tools()
    top = next(t for t in tools if t.name == "top_bandwidth_devices")
    assert set(top.inputSchema.get("properties", {})) == {"days", "limit", "network"}


@pytest.mark.asyncio
async def test_tool_delegates_to_route_handler():
    """A tool call delegates to the existing route handler with the right args."""
    mcp = build_mcp_server("/mcp")

    fake_handler = AsyncMock(return_value={"ok": True})

    @contextmanager
    def fake_db_context():
        yield MagicMock()

    with patch.object(mcp_module.routes, "get_network_summary", fake_handler), patch.object(
        mcp_module, "get_db_context", fake_db_context
    ), patch.object(mcp_module, "EeroClientWrapper", MagicMock()):
        await mcp.call_tool("network_summary", {"network": "Home"})

    fake_handler.assert_awaited_once()
    assert fake_handler.await_args.kwargs["network"] == "Home"


@pytest.mark.asyncio
async def test_collection_status_called_without_client():
    """collection_status takes no client argument and is called directly."""
    mcp = build_mcp_server("/mcp")
    fake_handler = AsyncMock(return_value={"collectors": {}})

    with patch.object(mcp_module.routes, "collection_status", fake_handler):
        await mcp.call_tool("collection_status", {})

    fake_handler.assert_awaited_once_with()


def test_streamable_http_app_serves_at_root():
    """The mounted sub-app serves the MCP endpoint at its root path."""
    mcp = build_mcp_server("/mcp")
    app = mcp.streamable_http_app()
    assert "/" in [getattr(r, "path", None) for r in app.routes]


def test_mcp_config_defaults_and_validation():
    """MCP is opt-in and the mount path is validated/normalized."""
    settings = Settings()
    assert settings.mcp_enabled is False
    assert settings.mcp_path == "/mcp"
    assert settings.get_mcp_allowed_hosts() == []

    assert Settings(mcp_path="/agent/").mcp_path == "/agent"
    with pytest.raises(ValueError):
        Settings(mcp_path="mcp")
    with pytest.raises(ValueError):
        Settings(mcp_path="/")


def test_get_mcp_allowed_hosts_parsing():
    """Comma-separated allowed hosts are split and trimmed."""
    settings = Settings(mcp_allowed_hosts="eero.example.com, other.example.com ,")
    assert settings.get_mcp_allowed_hosts() == ["eero.example.com", "other.example.com"]


def test_transport_security_defaults_to_localhost_only():
    """With no configured hosts, protection is on and only localhost passes."""
    mw = TransportSecurityMiddleware(_build_transport_security([]))
    assert mw.settings.enable_dns_rebinding_protection is True
    assert mw._validate_host("localhost:8080") is True
    assert mw._validate_host("eero.example.com") is False


def test_transport_security_allows_configured_host():
    """A configured host is accepted with or without an explicit port; others are not."""
    mw = TransportSecurityMiddleware(_build_transport_security(["eero.example.com"]))
    assert mw._validate_host("eero.example.com") is True
    assert mw._validate_host("eero.example.com:443") is True
    assert mw._validate_host("localhost:8080") is True
    assert mw._validate_host("evil.example.com") is False
    assert mw._validate_origin("https://eero.example.com") is True
    # MCP clients typically send no Origin header; that must be allowed.
    assert mw._validate_origin(None) is True


def test_transport_security_wildcard_disables_protection():
    """A '*' entry trusts the proxy entirely and disables host/origin checks."""
    ts = _build_transport_security(["*"])
    assert ts.enable_dns_rebinding_protection is False
