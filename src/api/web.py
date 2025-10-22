"""Web UI routes for eeroVista."""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src import __version__
from src.eero_client import EeroClientWrapper
from src.utils.database import get_db

logger = logging.getLogger(__name__)

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
