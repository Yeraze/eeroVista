"""Web UI routes for eeroVista."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src import __version__
from src.eero_client import EeroClientWrapper
from src.utils.database import get_db

logger = logging.getLogger(__name__)

# Cache for version check
_version_check_cache: Optional[Dict[str, Any]] = None
_version_check_time: Optional[datetime] = None
_VERSION_CHECK_INTERVAL = timedelta(hours=1)

router = APIRouter(tags=["web"])
templates = Jinja2Templates(directory="src/templates")


def get_eero_client(db: Session = Depends(get_db)) -> EeroClientWrapper:
    """Dependency to get Eero client."""
    return EeroClientWrapper(db)


def require_auth(client: EeroClientWrapper = Depends(get_eero_client)):
    """Require authentication, redirect to setup if not authenticated."""
    if not client.is_authenticated():
        return RedirectResponse(url="/setup", status_code=302)
    return None


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    client: EeroClientWrapper = Depends(get_eero_client),
):
    """Main dashboard page."""
    # Check if authenticated
    if not client.is_authenticated():
        return RedirectResponse(url="/setup", status_code=302)

    # Get basic network info
    networks = client.get_networks()
    if networks:
        # Networks can be Pydantic models or dicts, handle both
        first_network = networks[0]
        if isinstance(first_network, dict):
            network_name = first_network.get('name', 'Unknown')
        else:
            network_name = first_network.name
    else:
        network_name = "Unknown"

    # Get collection intervals from settings
    from src.config import get_settings
    settings = get_settings()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "network_name": network_name,
            "authenticated": True,
            "version": __version__,
            "collection_interval_devices": settings.collection_interval_devices,
            "collection_interval_network": settings.collection_interval_network,
        },
    )


@router.get("/devices", response_class=HTMLResponse)
async def devices_page(
    request: Request,
    client: EeroClientWrapper = Depends(get_eero_client),
):
    """Devices list page."""
    if not client.is_authenticated():
        return RedirectResponse(url="/setup", status_code=302)

    return templates.TemplateResponse(
        "devices.html",
        {
            "request": request,
            "authenticated": True,
            "version": __version__,
        },
    )


@router.get("/network", response_class=HTMLResponse)
async def network_page(
    request: Request,
    client: EeroClientWrapper = Depends(get_eero_client),
):
    """Network topology page."""
    if not client.is_authenticated():
        return RedirectResponse(url="/setup", status_code=302)

    return templates.TemplateResponse(
        "network.html",
        {
            "request": request,
            "authenticated": True,
            "version": __version__,
        },
    )


@router.get("/nodes", response_class=HTMLResponse)
async def nodes_page(
    request: Request,
    client: EeroClientWrapper = Depends(get_eero_client),
):
    """Eero nodes page."""
    if not client.is_authenticated():
        return RedirectResponse(url="/setup", status_code=302)

    return templates.TemplateResponse(
        "nodes.html",
        {
            "request": request,
            "authenticated": True,
            "version": __version__,
        },
    )


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    client: EeroClientWrapper = Depends(get_eero_client),
):
    """Settings page (read-only configuration display)."""
    if not client.is_authenticated():
        return RedirectResponse(url="/setup", status_code=302)

    from src.config import get_settings

    settings = get_settings()

    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "authenticated": True,
            "settings": settings,
            "version": __version__,
        },
    )


@router.get("/api/check-update")
async def check_update():
    """Check if a newer version is available on GitHub.

    Returns:
        JSON with update_available boolean, latest_version string, and release_url if available.
        Uses hourly caching to avoid spamming GitHub API.
    """
    global _version_check_cache, _version_check_time

    # Check if we have a cached result that's still valid
    now = datetime.now()
    if _version_check_cache and _version_check_time:
        if now - _version_check_time < _VERSION_CHECK_INTERVAL:
            return JSONResponse(_version_check_cache)

    # Perform the check
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                "https://api.github.com/repos/Yeraze/eeroVista/releases/latest",
                headers={"Accept": "application/vnd.github.v3+json"}
            )

            if response.status_code == 200:
                data = response.json()
                latest_version = data.get("tag_name", "").lstrip("v")
                release_url = data.get("html_url", "")

                # Compare versions
                current_version = __version__
                update_available = _is_version_newer(latest_version, current_version)

                result = {
                    "update_available": update_available,
                    "current_version": current_version,
                    "latest_version": latest_version,
                    "release_url": release_url,
                }

                # Cache the result
                _version_check_cache = result
                _version_check_time = now

                return JSONResponse(result)
            else:
                logger.warning(f"Failed to check GitHub releases: {response.status_code}")
                return JSONResponse({
                    "update_available": False,
                    "current_version": __version__,
                    "error": "Failed to check for updates"
                })

    except Exception as e:
        logger.error(f"Error checking for updates: {e}")
        return JSONResponse({
            "update_available": False,
            "current_version": __version__,
            "error": str(e)
        })


def _is_version_newer(latest: str, current: str) -> bool:
    """Compare two semantic version strings.

    Args:
        latest: Latest version string (e.g., "2.5.0")
        current: Current version string (e.g., "2.4.4")

    Returns:
        True if latest is newer than current
    """
    try:
        latest_parts = [int(x) for x in latest.split(".")]
        current_parts = [int(x) for x in current.split(".")]

        # Pad with zeros if needed
        while len(latest_parts) < 3:
            latest_parts.append(0)
        while len(current_parts) < 3:
            current_parts.append(0)

        return latest_parts > current_parts
    except (ValueError, AttributeError):
        # If we can't parse the versions, assume no update
        return False
