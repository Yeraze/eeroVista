"""Tests for the MCP server (src/mcp_server)."""

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Settings
from src.mcp_server import build_mcp_server
from src.mcp_server import server as mcp_module

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

    assert Settings(mcp_path="/agent/").mcp_path == "/agent"
    with pytest.raises(ValueError):
        Settings(mcp_path="mcp")
    with pytest.raises(ValueError):
        Settings(mcp_path="/")
