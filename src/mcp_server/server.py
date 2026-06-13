"""MCP server definition and tool registration.

The tools delegate to the existing FastAPI route handlers in ``src.api.health``.
Each handler accepts an :class:`EeroClientWrapper` (used for network-name
resolution) and performs its own database access via ``get_db_context``. We build
a short-lived client bound to a database session that stays open for the duration
of the handler call.
"""

import logging
from typing import Any, Awaitable, Callable, Dict, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from src.api.health import analytics, routes
from src.eero_client.client import EeroClientWrapper
from src.utils.database import get_db_context

logger = logging.getLogger(__name__)

# Loopback hosts/origins are always trusted (local access and health checks).
_LOCAL_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_LOCAL_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


def _build_transport_security(allowed_hosts: list[str]) -> TransportSecuritySettings:
    """Build DNS-rebinding-protection settings for the given extra allowed hosts.

    The MCP SDK enables host/origin checking by default and only trusts
    localhost, which breaks reverse-proxy deployments (the proxy forwards the
    public Host header). We extend the allow-list with the configured hostnames,
    or disable protection entirely when ``*`` is supplied (trust the proxy).
    """
    if "*" in allowed_hosts:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)

    hosts = list(_LOCAL_HOSTS)
    origins = list(_LOCAL_ORIGINS)
    for host in allowed_hosts:
        # Allow both the bare host (default 443/80, no port in the Host header)
        # and any explicit port via the SDK's ":*" wildcard.
        hosts.extend([host, f"{host}:*"])
        for scheme in ("https", "http"):
            origins.extend([f"{scheme}://{host}", f"{scheme}://{host}:*"])

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


async def _query(
    handler: Callable[..., Awaitable[Dict[str, Any]]], **kwargs: Any
) -> Dict[str, Any]:
    """Run an existing route handler with a freshly-built Eero client.

    The database session is held open for the whole ``await`` so the client can
    resolve the active network while the handler runs.
    """
    with get_db_context() as db:
        client = EeroClientWrapper(db)
        return await handler(client=client, **kwargs)


def build_mcp_server(path: str = "/mcp", allowed_hosts: Optional[list[str]] = None) -> FastMCP:
    """Create the eeroVista MCP server with its curated read-only tools.

    Args:
        path: Absolute path the Streamable HTTP endpoint is served at. The server
            is mounted at this path by the main app, so the internal route is the
            sub-app root ("/").
        allowed_hosts: Extra Host header values to accept in addition to
            localhost (needed behind a reverse proxy). Pass ``["*"]`` to trust the
            proxy entirely and disable host/origin checking.
    """
    mcp = FastMCP(
        name="eeroVista",
        instructions=(
            "Read-only tools for monitoring an eero mesh network in real time. "
            "Use these to inspect network health, connected devices, eero nodes, "
            "WAN uptime, outages, speedtests, signal quality, and bandwidth usage. "
            "All tools are query-only; none change network configuration. "
            "Most tools accept an optional `network` name; omit it to use the "
            "default (first) network. Data comes from eeroVista's local database, "
            "so call `collection_status` if you need to confirm how fresh it is."
        ),
        stateless_http=True,
        json_response=True,
        streamable_http_path="/",
        transport_security=_build_transport_security(allowed_hosts or []),
    )

    @mcp.tool()
    async def dashboard_stats(network: Optional[str] = None) -> Dict[str, Any]:
        """Get a high-level dashboard summary for the network.

        Returns current device counts (total/online), the network health score,
        WAN status, guest-network state, and the latest speedtest result. This is
        the best single tool for a quick "how is my network doing right now?".
        """
        return await _query(routes.dashboard_stats, network=network)

    @mcp.tool()
    async def network_summary(network: Optional[str] = None) -> Dict[str, Any]:
        """Get a network summary including every eero node's status.

        Returns total/online device counts, WAN status, guest-network state, and a
        list of nodes with their location, model, gateway flag, online status,
        connected-device count, and uptime.
        """
        return await _query(routes.get_network_summary, network=network)

    @mcp.tool()
    async def list_devices(network: Optional[str] = None) -> Dict[str, Any]:
        """List all client devices known on the network.

        Returns each device's name, MAC address, IP, manufacturer, connection type
        (wired/wireless), the eero node it is connected to, online status, and
        signal metrics where available.
        """
        return await _query(routes.get_devices, network=network)

    @mcp.tool()
    async def list_nodes(network: Optional[str] = None) -> Dict[str, Any]:
        """List the eero nodes (access points) that make up the mesh.

        Returns each node's location, model, gateway flag, online status,
        connected-device count, uptime, and connection mode (wired/wireless
        backhaul).
        """
        return await _query(routes.get_nodes, network=network)

    @mcp.tool()
    async def collection_status() -> Dict[str, Any]:
        """Report background data-collection health and freshness.

        Returns the last successful collection timestamps for each collector
        (device, network, routing, speedtest) so you can tell how current the data
        returned by the other tools is.
        """
        # collection_status takes no client argument, so call it directly.
        return await routes.collection_status()

    @mcp.tool()
    async def firmware_status(network: Optional[str] = None) -> Dict[str, Any]:
        """Check the firmware version and whether an update is available."""
        return await _query(routes.get_firmware_update, network=network)

    @mcp.tool()
    async def health_score(network: Optional[str] = None) -> Dict[str, Any]:
        """Get the current network health score (0-100) and its contributing factors."""
        return await _query(analytics.get_network_health_score, network=network)

    @mcp.tool()
    async def wan_uptime(network: Optional[str] = None) -> Dict[str, Any]:
        """Get WAN (internet) uptime percentages over the last 24 hours, 7 days, and 30 days."""
        return await _query(analytics.get_network_uptime, network=network)

    @mcp.tool()
    async def recent_outages(days: int = 30, network: Optional[str] = None) -> Dict[str, Any]:
        """List recent WAN outages (internet drops) within the given number of days."""
        return await _query(analytics.get_network_outages, days=days, network=network)

    @mcp.tool()
    async def speedtest_analysis(days: int = 30, network: Optional[str] = None) -> Dict[str, Any]:
        """Summarize recent speedtest results (download/upload/latency trends) over the given window."""
        return await _query(analytics.get_speedtest_analysis, days=days, network=network)

    @mcp.tool()
    async def signal_summary(network: Optional[str] = None) -> Dict[str, Any]:
        """Summarize wireless signal quality across all connected devices.

        Highlights devices with weak signal that may have connectivity problems.
        """
        return await _query(analytics.get_devices_signal_summary, network=network)

    @mcp.tool()
    async def top_bandwidth_devices(
        days: int = 7, limit: int = 5, network: Optional[str] = None
    ) -> Dict[str, Any]:
        """List the devices using the most bandwidth over the given window.

        Args:
            days: Look-back window in days (default 7).
            limit: Maximum number of devices to return (default 5).
            network: Optional network name; defaults to the first network.
        """
        return await _query(
            analytics.get_network_bandwidth_top_devices, days=days, limit=limit, network=network
        )

    logger.info(
        "MCP server initialized with read-only eero network tools (mounted at %s, allowed_hosts=%s)",
        path,
        allowed_hosts or "localhost-only",
    )
    return mcp
