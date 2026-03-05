"""Notification rules CRUD API endpoints."""

import json
import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from src.models.database import Config
from src.models.notifications import NotificationHistory, NotificationRule

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Apprise URL helpers (DB-backed via Config table)
# ---------------------------------------------------------------------------

def get_apprise_urls(db: Session) -> Optional[str]:
    """Read the stored Apprise URLs from the Config table. Returns None if not set."""
    row = db.query(Config).filter(Config.key == "apprise_urls").first()
    if row and row.value:
        return row.value
    return None


def set_apprise_urls(db: Session, urls: str) -> None:
    """Write Apprise URLs to the Config table."""
    row = db.query(Config).filter(Config.key == "apprise_urls").first()
    if row:
        row.value = urls
    else:
        row = Config(key="apprise_urls", value=urls)
        db.add(row)
    db.commit()


# ---------------------------------------------------------------------------
# Business logic functions (testable without FastAPI)
# ---------------------------------------------------------------------------

def _rule_to_dict(rule: NotificationRule) -> dict:
    """Convert a NotificationRule ORM object to a response dict."""
    return {
        "id": rule.id,
        "network_name": rule.network_name,
        "rule_type": rule.rule_type,
        "enabled": bool(rule.enabled),
        "config_json": rule.config_json,
        "cooldown_minutes": rule.cooldown_minutes,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
    }


def _history_to_dict(entry: NotificationHistory) -> dict:
    """Convert a NotificationHistory ORM object to a response dict."""
    return {
        "id": entry.id,
        "rule_id": entry.rule_id,
        "event_key": entry.event_key,
        "message": entry.message,
        "sent_at": entry.sent_at.isoformat() if entry.sent_at else None,
        "resolved_at": entry.resolved_at.isoformat() if entry.resolved_at else None,
    }


def list_notification_rules(db: Session, network_name: Optional[str] = None) -> list:
    """List notification rules, optionally filtered by network."""
    query = db.query(NotificationRule)
    if network_name:
        query = query.filter(NotificationRule.network_name == network_name)
    rules = query.order_by(NotificationRule.id).all()
    return [_rule_to_dict(r) for r in rules]


def create_notification_rule(
    db: Session,
    network_name: str,
    rule_type: str,
    config_json: str = "{}",
    cooldown_minutes: int = 60,
    enabled: bool = True,
) -> dict:
    """Create a new notification rule."""
    valid_types = {"node_offline", "high_bandwidth", "new_device", "firmware_update", "device_offline"}
    if rule_type not in valid_types:
        raise ValueError(f"Invalid rule type: {rule_type}. Must be one of: {', '.join(sorted(valid_types))}")

    # Validate config_json is valid JSON
    try:
        json.loads(config_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid config_json: {e}")

    rule = NotificationRule(
        network_name=network_name,
        rule_type=rule_type,
        config_json=config_json,
        cooldown_minutes=cooldown_minutes,
        enabled=1 if enabled else 0,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_to_dict(rule)


def update_notification_rule(
    db: Session,
    rule_id: int,
    enabled: Optional[bool] = None,
    config_json: Optional[str] = None,
    cooldown_minutes: Optional[int] = None,
) -> dict:
    """Update an existing notification rule."""
    rule = db.query(NotificationRule).filter(NotificationRule.id == rule_id).first()
    if not rule:
        raise ValueError("Rule not found")

    if enabled is not None:
        rule.enabled = 1 if enabled else 0
    if config_json is not None:
        try:
            json.loads(config_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid config_json: {e}")
        rule.config_json = config_json
    if cooldown_minutes is not None:
        rule.cooldown_minutes = cooldown_minutes

    rule.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(rule)
    return _rule_to_dict(rule)


def delete_notification_rule(db: Session, rule_id: int) -> None:
    """Delete a notification rule and its history."""
    rule = db.query(NotificationRule).filter(NotificationRule.id == rule_id).first()
    if not rule:
        raise ValueError("Rule not found")

    # Delete history first (SQLite may not enforce FK cascade)
    db.query(NotificationHistory).filter(NotificationHistory.rule_id == rule_id).delete()
    db.delete(rule)
    db.commit()


def get_notification_history(db: Session, limit: int = 50) -> list:
    """Get recent notification history."""
    entries = db.query(NotificationHistory).order_by(
        NotificationHistory.sent_at.desc()
    ).limit(limit).all()
    return [_history_to_dict(e) for e in entries]


# ---------------------------------------------------------------------------
# FastAPI route handlers
# ---------------------------------------------------------------------------

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.utils.database import get_db

router = APIRouter(prefix="/api", tags=["notifications"])


class CreateRuleRequest(BaseModel):
    """Request model for creating a notification rule."""
    network_name: str
    rule_type: str
    config_json: str = "{}"
    cooldown_minutes: int = 60
    enabled: bool = True


class UpdateRuleRequest(BaseModel):
    """Request model for updating a notification rule."""
    enabled: Optional[bool] = None
    config_json: Optional[str] = None
    cooldown_minutes: Optional[int] = None


class TestNotificationRequest(BaseModel):
    """Request model for sending a test notification."""
    message: str = "This is a test notification from eeroVista"


class NotificationSettingsRequest(BaseModel):
    """Request model for updating notification settings."""
    apprise_urls: str = ""


@router.get("/notification-settings")
def api_get_notification_settings(db: Session = Depends(get_db)):
    """Get current Apprise URL configuration."""
    urls = get_apprise_urls(db) or ""
    return {"apprise_urls": urls, "configured": bool(urls.strip())}


@router.put("/notification-settings")
def api_put_notification_settings(
    req: NotificationSettingsRequest,
    db: Session = Depends(get_db),
):
    """Save Apprise URL configuration."""
    set_apprise_urls(db, req.apprise_urls.strip())
    urls = req.apprise_urls.strip()
    return {"apprise_urls": urls, "configured": bool(urls)}


@router.get("/notification-rules")
def api_list_notification_rules(
    network: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List notification rules."""
    return list_notification_rules(db, network)


@router.post("/notification-rules", status_code=201)
def api_create_notification_rule(
    req: CreateRuleRequest,
    db: Session = Depends(get_db),
):
    """Create a new notification rule."""
    try:
        return create_notification_rule(
            db,
            network_name=req.network_name,
            rule_type=req.rule_type,
            config_json=req.config_json,
            cooldown_minutes=req.cooldown_minutes,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/notification-rules/{rule_id}")
def api_update_notification_rule(
    rule_id: int,
    req: UpdateRuleRequest,
    db: Session = Depends(get_db),
):
    """Update a notification rule."""
    try:
        return update_notification_rule(
            db, rule_id,
            enabled=req.enabled,
            config_json=req.config_json,
            cooldown_minutes=req.cooldown_minutes,
        )
    except ValueError as e:
        status = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=status, detail=str(e))


@router.delete("/notification-rules/{rule_id}", status_code=204)
def api_delete_notification_rule(
    rule_id: int,
    db: Session = Depends(get_db),
):
    """Delete a notification rule."""
    try:
        delete_notification_rule(db, rule_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/notifications/test")
def api_test_notification(
    req: TestNotificationRequest,
    db: Session = Depends(get_db),
):
    """Send a test notification."""
    urls = get_apprise_urls(db)
    if not urls:
        raise HTTPException(
            status_code=400,
            detail="No Apprise URLs configured. Add them in the Settings page."
        )

    from src.services.notification_service import NotificationService
    service = NotificationService(db, apprise_urls=urls)
    success = service.send_test(req.message)

    if success:
        return {"success": True, "message": "Test notification sent successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to send test notification")


@router.get("/notification-config/networks")
def api_get_networks_for_config(
    db: Session = Depends(get_db),
):
    """Get available network names for notification rule configuration."""
    from src.models.database import EeroNode
    from sqlalchemy import distinct
    networks = db.query(distinct(EeroNode.network_name)).all()
    return [n[0] for n in networks if n[0]]


@router.get("/notification-config/nodes")
def api_get_nodes_for_config(
    network: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get eero nodes list for notification rule configuration."""
    from src.models.database import Device, EeroNode
    query = db.query(EeroNode)
    if network:
        query = query.filter(EeroNode.network_name == network)
    nodes = query.all()
    return [
        {"id": n.id, "location": n.location, "eero_id": n.eero_id, "is_gateway": n.is_gateway or False}
        for n in nodes
    ]


@router.get("/notification-config/devices")
def api_get_devices_for_config(
    network: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Get devices list for notification rule configuration."""
    from src.models.database import Device
    query = db.query(Device)
    if network:
        query = query.filter(Device.network_name == network)
    devices = query.all()
    return [
        {"id": d.id, "name": d.nickname or d.hostname or d.mac_address, "mac_address": d.mac_address}
        for d in devices
    ]


@router.get("/notification-history")
def api_notification_history(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Get recent notification history."""
    return get_notification_history(db, limit=min(limit, 200))
