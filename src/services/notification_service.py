"""Notification service for evaluating rules and dispatching alerts via Apprise."""

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import apprise

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.config import Settings, get_settings
from src.models.database import Device, DeviceConnection, EeroNode, EeroNodeMetric
from src.models.notifications import NotificationHistory, NotificationRule

logger = logging.getLogger(__name__)


class NotificationService:
    """Evaluates notification rules and dispatches alerts via Apprise."""

    def __init__(self, db: Session, apprise_urls: Optional[str] = None, config: Optional[Settings] = None):
        self.db = db
        self.config = config or get_settings()
        self._apprise = apprise.Apprise()
        if apprise_urls:
            for url in re.split(r"[,\n]", apprise_urls):
                url = url.strip()
                if url:
                    self._apprise.add(url)

    def check_all_rules(self) -> dict:
        """Evaluate all enabled notification rules and send alerts as needed."""
        rules = self.db.query(NotificationRule).filter(
            NotificationRule.enabled == 1
        ).all()

        if not rules:
            return {"success": True, "rules_checked": 0, "notifications_sent": 0}

        total_sent = 0
        for rule in rules:
            try:
                sent = self._check_rule(rule)
                total_sent += sent
            except Exception as e:
                logger.error(f"Error checking rule {rule.id} ({rule.rule_type}): {e}", exc_info=True)

        return {"success": True, "rules_checked": len(rules), "notifications_sent": total_sent}

    def _check_rule(self, rule: NotificationRule) -> int:
        """Check a single rule and return number of notifications sent."""
        handler_map = {
            "node_offline": self._check_node_offline,
            "high_bandwidth": self._check_high_bandwidth,
            "new_device": self._check_new_device,
            "firmware_update": self._check_firmware_update,
            "device_offline": self._check_device_offline,
        }

        handler = handler_map.get(rule.rule_type)
        if not handler:
            logger.warning(f"Unknown rule type: {rule.rule_type}")
            return 0

        return handler(rule)

    @staticmethod
    def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
        """Ensure a datetime is timezone-aware (assume UTC if naive, as SQLite strips tzinfo)."""
        if dt is not None and dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    def _should_notify(self, rule: NotificationRule, event_key: str) -> bool:
        """Check if we should send a notification (cooldown/dedup check).

        Cooldown suppresses duplicate alerts for the same ongoing event.
        Once an event is resolved, a new occurrence can fire immediately —
        this is intentional so that flapping devices generate a fresh alert
        each time they go offline again, rather than being silently suppressed.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=rule.cooldown_minutes)

        # Check for an active (unresolved) event or a recent one within cooldown
        existing = self.db.query(NotificationHistory).filter(
            NotificationHistory.rule_id == rule.id,
            NotificationHistory.event_key == event_key,
            (
                (NotificationHistory.resolved_at.is_(None)) |
                (NotificationHistory.sent_at > cutoff)
            ),
        ).first()

        return existing is None

    def _send(self, title: str, body: str) -> bool:
        """Send notification via Apprise. Returns True if sent successfully."""
        if len(self._apprise) == 0:
            logger.warning("No Apprise URLs configured, skipping notification")
            return False

        try:
            result = self._apprise.notify(title=title, body=body)
            if result:
                logger.info(f"Notification sent: {title}")
            else:
                logger.warning(f"Notification send failed: {title}")
            return result
        except Exception as e:
            logger.error(f"Failed to send notification: {e}", exc_info=True)
            return False

    def _record_notification(self, rule: NotificationRule, event_key: str, message: str) -> None:
        """Record a sent notification in history."""
        history = NotificationHistory(
            rule_id=rule.id,
            event_key=event_key,
            message=message,
        )
        self.db.add(history)
        self.db.commit()

    def _resolve_cleared(self, rule: NotificationRule, current_event_keys: set) -> None:
        """Mark resolved any active events that are no longer occurring."""
        active = self.db.query(NotificationHistory).filter(
            NotificationHistory.rule_id == rule.id,
            NotificationHistory.resolved_at.is_(None),
        ).all()

        now = datetime.now(timezone.utc)
        for entry in active:
            if entry.event_key not in current_event_keys:
                entry.resolved_at = now

        if active:
            self.db.commit()

    def _check_node_offline(self, rule: NotificationRule) -> int:
        """Check for offline eero nodes using the latest metric status."""
        config = json.loads(rule.config_json)
        node_ids = config.get("node_ids", [])

        if not node_ids:
            return 0

        nodes = self.db.query(EeroNode).filter(
            EeroNode.id.in_(node_ids),
            EeroNode.network_name == rule.network_name,
        ).all()

        sent = 0
        current_keys = set()

        for node in nodes:
            # Get the latest metric record for this node
            latest_metric = self.db.query(EeroNodeMetric).filter(
                EeroNodeMetric.eero_node_id == node.id,
            ).order_by(EeroNodeMetric.timestamp.desc()).first()

            is_offline = latest_metric is None or latest_metric.status != "online"
            event_key = f"node_offline:{node.id}"

            if is_offline:
                current_keys.add(event_key)
                if self._should_notify(rule, event_key):
                    last_seen_str = node.last_seen.strftime("%Y-%m-%d %H:%M UTC") if node.last_seen else "never"
                    body = f"Eero node '{node.location or node.eero_id}' has been offline since {last_seen_str}"
                    if self._send("eeroVista: Node Offline", body):
                        self._record_notification(rule, event_key, body)
                        sent += 1

        self._resolve_cleared(rule, current_keys)
        return sent

    def _check_high_bandwidth(self, rule: NotificationRule) -> int:
        """Check for high bandwidth usage across all devices on the network."""
        config = json.loads(rule.config_json)
        threshold_down = config.get("threshold_down_mbps", 0)
        threshold_up = config.get("threshold_up_mbps", 0)

        if not threshold_down and not threshold_up:
            return 0

        # Get all devices on this network
        all_devices = self.db.query(Device).filter(
            Device.network_name == rule.network_name,
        ).all()

        sent = 0
        current_keys = set()

        for device in all_devices:
            # Get the latest connection record for this device
            latest = self.db.query(DeviceConnection).filter(
                DeviceConnection.device_id == device.id,
                DeviceConnection.network_name == rule.network_name,
            ).order_by(DeviceConnection.timestamp.desc()).first()

            if not latest:
                continue

            device_name = device.nickname or device.hostname or device.mac_address
            event_key = f"high_bandwidth:{device.id}"

            exceeded = False
            details = []

            if threshold_down > 0 and latest.bandwidth_down_mbps and latest.bandwidth_down_mbps > threshold_down:
                exceeded = True
                details.append(f"{latest.bandwidth_down_mbps:.1f} Mbps download (threshold: {threshold_down:.1f} Mbps)")

            if threshold_up > 0 and latest.bandwidth_up_mbps and latest.bandwidth_up_mbps > threshold_up:
                exceeded = True
                details.append(f"{latest.bandwidth_up_mbps:.1f} Mbps upload (threshold: {threshold_up:.1f} Mbps)")

            if exceeded:
                current_keys.add(event_key)
                if self._should_notify(rule, event_key):
                    body = f"Device '{device_name}' is using {', '.join(details)}"
                    if self._send("eeroVista: High Bandwidth", body):
                        self._record_notification(rule, event_key, body)
                        sent += 1

        self._resolve_cleared(rule, current_keys)
        return sent

    def _check_new_device(self, rule: NotificationRule) -> int:
        """Check for new devices that joined the network after the rule was created."""
        # Only look for devices discovered since the rule was created
        # and within the last check interval
        check_window = datetime.now(timezone.utc) - timedelta(
            seconds=self.config.notification_check_interval * 2
        )
        rule_created = self._ensure_utc(rule.created_at)

        new_devices = self.db.query(Device).filter(
            Device.network_name == rule.network_name,
        ).all()

        # Filter in Python to handle naive/aware datetime comparison
        new_devices = [
            d for d in new_devices
            if self._ensure_utc(d.first_seen) is not None
            and self._ensure_utc(d.first_seen) > rule_created
            and self._ensure_utc(d.first_seen) > check_window
        ]

        sent = 0
        current_keys = set()

        for device in new_devices:
            event_key = f"new_device:{device.mac_address}"
            current_keys.add(event_key)

            if self._should_notify(rule, event_key):
                name = device.nickname or device.hostname or "Unknown"
                body = f"New device '{name}' ({device.mac_address}) joined the network"
                if self._send("eeroVista: New Device Detected", body):
                    self._record_notification(rule, event_key, body)
                    sent += 1

        # Don't resolve new_device events - they're one-time alerts
        return sent

    def _check_firmware_update(self, rule: NotificationRule) -> int:
        """Check for eero nodes with firmware updates available (consolidated)."""
        nodes = self.db.query(EeroNode).filter(
            EeroNode.network_name == rule.network_name,
            EeroNode.update_available == True,  # noqa: E712
        ).all()

        sent = 0
        current_keys = set()
        event_key = f"firmware_update:network:{rule.network_name}"

        if nodes:
            current_keys.add(event_key)
            if self._should_notify(rule, event_key):
                lines = []
                for node in nodes:
                    name = node.location or node.eero_id
                    version = node.os_version or "unknown"
                    lines.append(f"- {name} (current: {version})")
                body = "Firmware update available for your eero network.\nAffected nodes:\n" + "\n".join(lines)
                if self._send("eeroVista: Firmware Update Available", body):
                    self._record_notification(rule, event_key, body)
                    sent += 1

        self._resolve_cleared(rule, current_keys)
        return sent

    def _check_device_offline(self, rule: NotificationRule) -> int:
        """Check for offline devices based on latest collection status."""
        config = json.loads(rule.config_json)
        device_ids = config.get("device_ids", [])

        if not device_ids:
            return 0

        devices = self.db.query(Device).filter(
            Device.id.in_(device_ids),
            Device.network_name == rule.network_name,
        ).all()

        sent = 0
        current_keys = set()

        for device in devices:
            # Check the most recent connection record for this device
            latest_conn = self.db.query(DeviceConnection).filter(
                DeviceConnection.device_id == device.id,
                DeviceConnection.network_name == rule.network_name,
            ).order_by(DeviceConnection.timestamp.desc()).first()

            is_offline = latest_conn is None or not latest_conn.is_connected
            event_key = f"device_offline:{device.id}"

            if is_offline:
                current_keys.add(event_key)
                if self._should_notify(rule, event_key):
                    device_name = device.nickname or device.hostname or device.mac_address
                    last_seen_str = device.last_seen.strftime("%Y-%m-%d %H:%M UTC") if device.last_seen else "never"
                    body = f"Device '{device_name}' ({device.mac_address}) has been offline since {last_seen_str}"
                    if self._send("eeroVista: Device Offline", body):
                        self._record_notification(rule, event_key, body)
                        sent += 1

        self._resolve_cleared(rule, current_keys)
        return sent

    def send_test(self, message: str = "This is a test notification from eeroVista") -> bool:
        """Send a test notification to verify Apprise configuration."""
        return self._send("eeroVista: Test Notification", message)
