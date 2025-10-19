"""Setup wizard API endpoints for initial authentication."""

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.eero_client import EeroClientWrapper
from src.utils.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/setup", tags=["setup"])
templates = Jinja2Templates(directory="src/templates")


def get_eero_client(db: Session = Depends(get_db)) -> EeroClientWrapper:
    """Dependency to get Eero client."""
    return EeroClientWrapper(db)


@router.get("/", response_class=HTMLResponse)
async def setup_page(request: Request, client: EeroClientWrapper = Depends(get_eero_client)):
    """Show setup wizard page."""
    # If already authenticated, redirect to dashboard
    if client.is_authenticated():
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse(
        "setup.html", {"request": request, "step": "phone"}
    )


@router.post("/send-code")
async def send_verification_code(
    phone: str = Form(...), client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Send SMS verification code to phone number."""
    logger.info(f"Sending verification code to {phone}")
    result = client.login_phone(phone)
    return result


@router.post("/verify-code")
async def verify_code(
    code: str = Form(...), client: EeroClientWrapper = Depends(get_eero_client)
) -> Dict[str, Any]:
    """Verify SMS code and complete authentication."""
    logger.info("Verifying SMS code")
    result = client.login_verify(code)
    return result


@router.get("/status")
async def setup_status(client: EeroClientWrapper = Depends(get_eero_client)) -> Dict[str, Any]:
    """Check setup/authentication status."""
    is_authenticated = client.is_authenticated()

    if is_authenticated:
        # Try to get account info
        account = client.get_account()
        return {
            "authenticated": True,
            "setup_complete": True,
            "account": account.get("email") if account else None,
        }
    else:
        return {"authenticated": False, "setup_complete": False}
