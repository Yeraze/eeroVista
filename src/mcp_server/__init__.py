"""Model Context Protocol (MCP) server for eeroVista.

Exposes a curated, read-only set of network-status tools over Streamable HTTP so
that AI agents can query the eero mesh network in real time. The tools reuse the
existing FastAPI route handlers, so their behaviour stays identical to the REST API.
"""

from src.mcp_server.server import build_mcp_server

__all__ = ["build_mcp_server"]
