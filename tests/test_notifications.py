"""Tests for notification rules and notification service."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, Device, DeviceConnection, EeroNode
from src.models.notifications import NotificationHistory, NotificationRule


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    # Also create notification tables
    from src.models.notifications import NotificationRule, NotificationHistory
    NotificationRule.__table__.create(engine, checkfirst=True)
    NotificationHistory.__table__.create(engine, checkfirst=True)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def config():
    """Create a mock config."""
    cfg = MagicMock()
    cfg.collection_interval_devices = 30
    cfg.notification_check_interval = 60
    return cfg


class TestNotificationRuleCRUD:
    """Test CRUD operations for notification rules."""

    def test_create_rule(self, db_session):
        from src.api.notifications import create_notification_rule
        result = create_notification_rule(
            db_session,
            network_name="home",
            rule_type="node_offline",
            config_json='{"node_ids": [1, 2]}',
            cooldown_minutes=30,
        )
        assert result["id"] is not None
        assert result["network_name"] == "home"
        assert result["rule_type"] == "node_offline"
        assert result["enabled"] is True
        assert result["cooldown_minutes"] == 30

    def test_create_rule_invalid_type(self, db_session):
        from src.api.notifications import create_notification_rule
        with pytest.raises(ValueError, match="Invalid rule type"):
            create_notification_rule(db_session, "home", "invalid_type")

    def test_create_rule_invalid_json(self, db_session):
        from src.api.notifications import create_notification_rule
        with pytest.raises(ValueError, match="Invalid config_json"):
            create_notification_rule(db_session, "home", "new_device", config_json="not json")

    def test_list_rules(self, db_session):
        from src.api.notifications import create_notification_rule, list_notification_rules
        create_notification_rule(db_session, "home", "new_device")
        create_notification_rule(db_session, "home", "firmware_update")
        create_notification_rule(db_session, "office", "new_device")

        all_rules = list_notification_rules(db_session)
        assert len(all_rules) == 3

        home_rules = list_notification_rules(db_session, network_name="home")
        assert len(home_rules) == 2

    def test_update_rule(self, db_session):
        from src.api.notifications import create_notification_rule, update_notification_rule
        rule = create_notification_rule(db_session, "home", "new_device", cooldown_minutes=60)

        updated = update_notification_rule(db_session, rule["id"], enabled=False, cooldown_minutes=120)
        assert updated["enabled"] is False
        assert updated["cooldown_minutes"] == 120

    def test_update_rule_not_found(self, db_session):
        from src.api.notifications import update_notification_rule
        with pytest.raises(ValueError, match="Rule not found"):
            update_notification_rule(db_session, 9999, enabled=False)

    def test_delete_rule(self, db_session):
        from src.api.notifications import create_notification_rule, delete_notification_rule, list_notification_rules
        rule = create_notification_rule(db_session, "home", "new_device")
        delete_notification_rule(db_session, rule["id"])
        assert len(list_notification_rules(db_session)) == 0

    def test_delete_rule_not_found(self, db_session):
        from src.api.notifications import delete_notification_rule
        with pytest.raises(ValueError, match="Rule not found"):
            delete_notification_rule(db_session, 9999)

    def test_get_history_empty(self, db_session):
        from src.api.notifications import get_notification_history
        assert get_notification_history(db_session) == []


class TestNotificationService:
    """Test notification service logic."""

    def _make_service(self, db_session, config):
        from src.services.notification_service import NotificationService
        service = NotificationService(db_session, apprise_urls="json://stdout", config=config)
        # Replace internal apprise with a mock
        mock_apprise = MagicMock()
        mock_apprise.notify.return_value = True
        mock_apprise.__len__ = lambda self: 1
        service._apprise = mock_apprise
        return service

    def test_check_all_rules_no_rules(self, db_session, config):
        service = self._make_service(db_session, config)
        result = service.check_all_rules()
        assert result["success"] is True
        assert result["rules_checked"] == 0

    def test_node_offline_detection(self, db_session, config):
        # Create a node that's been offline
        node = EeroNode(
            network_name="home",
            eero_id="node1",
            location="Living Room",
            last_seen=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db_session.add(node)
        db_session.commit()

        # Create an offline rule
        rule = NotificationRule(
            network_name="home",
            rule_type="node_offline",
            config_json=json.dumps({"node_ids": [node.id]}),
            cooldown_minutes=60,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        result = service.check_all_rules()
        assert result["notifications_sent"] == 1
        service._apprise.notify.assert_called_once()

    def test_node_offline_cooldown(self, db_session, config):
        """Second check within cooldown should not send again."""
        node = EeroNode(
            network_name="home",
            eero_id="node1",
            location="Living Room",
            last_seen=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db_session.add(node)
        db_session.commit()

        rule = NotificationRule(
            network_name="home",
            rule_type="node_offline",
            config_json=json.dumps({"node_ids": [node.id]}),
            cooldown_minutes=60,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        service.check_all_rules()
        service._apprise.notify.reset_mock()

        # Second check - should be suppressed by cooldown
        result = service.check_all_rules()
        assert result["notifications_sent"] == 0
        service._apprise.notify.assert_not_called()

    def test_node_online_resolves(self, db_session, config):
        """A node coming back online should resolve the event."""
        node = EeroNode(
            network_name="home",
            eero_id="node1",
            location="Living Room",
            last_seen=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db_session.add(node)
        db_session.commit()

        rule = NotificationRule(
            network_name="home",
            rule_type="node_offline",
            config_json=json.dumps({"node_ids": [node.id]}),
            cooldown_minutes=60,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        service.check_all_rules()

        # Node comes back online
        node.last_seen = datetime.now(timezone.utc)
        db_session.commit()

        service.check_all_rules()

        # History entry should be resolved
        history = db_session.query(NotificationHistory).first()
        assert history.resolved_at is not None

    def test_new_device_detection(self, db_session, config):
        # Create a rule first
        rule = NotificationRule(
            network_name="home",
            rule_type="new_device",
            config_json="{}",
            cooldown_minutes=60,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db_session.add(rule)
        db_session.commit()

        # New device appears after rule creation and within check window
        device = Device(
            network_name="home",
            mac_address="aa:bb:cc:dd:ee:ff",
            hostname="New Phone",
            first_seen=datetime.now(timezone.utc),
        )
        db_session.add(device)
        db_session.commit()

        service = self._make_service(db_session, config)
        result = service.check_all_rules()
        assert result["notifications_sent"] == 1

    def test_new_device_ignores_old_devices(self, db_session, config):
        """Devices that existed before the rule was created should be ignored."""
        # Old device
        device = Device(
            network_name="home",
            mac_address="aa:bb:cc:dd:ee:ff",
            hostname="Old Device",
            first_seen=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db_session.add(device)
        db_session.commit()

        # Rule created after device
        rule = NotificationRule(
            network_name="home",
            rule_type="new_device",
            config_json="{}",
            cooldown_minutes=60,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        result = service.check_all_rules()
        assert result["notifications_sent"] == 0

    def test_firmware_update_detection(self, db_session, config):
        node = EeroNode(
            network_name="home",
            eero_id="node1",
            location="Office",
            update_available=True,
            os_version="7.3.0",
            last_seen=datetime.now(timezone.utc),
        )
        db_session.add(node)
        db_session.commit()

        rule = NotificationRule(
            network_name="home",
            rule_type="firmware_update",
            config_json="{}",
            cooldown_minutes=60,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        result = service.check_all_rules()
        assert result["notifications_sent"] == 1

    def test_firmware_update_consolidated(self, db_session, config):
        """Multiple nodes with updates should produce a single notification."""
        for i, loc in enumerate(["Living Room", "Office"]):
            node = EeroNode(
                network_name="home",
                eero_id=f"node{i}",
                location=loc,
                update_available=True,
                os_version="7.3.0",
                last_seen=datetime.now(timezone.utc),
            )
            db_session.add(node)
        db_session.commit()

        rule = NotificationRule(
            network_name="home",
            rule_type="firmware_update",
            config_json="{}",
            cooldown_minutes=60,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        result = service.check_all_rules()
        # Only one consolidated notification, not two
        assert result["notifications_sent"] == 1
        call_args = service._apprise.notify.call_args
        body = call_args[1].get("body", "") if call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else ""
        assert "Living Room" in body
        assert "Office" in body

    def test_high_bandwidth_detection(self, db_session, config):
        device = Device(
            network_name="home",
            mac_address="aa:bb:cc:dd:ee:ff",
            nickname="Gaming PC",
        )
        db_session.add(device)
        db_session.commit()

        conn = DeviceConnection(
            device_id=device.id,
            network_name="home",
            bandwidth_down_mbps=150.0,
            bandwidth_up_mbps=20.0,
            timestamp=datetime.now(timezone.utc),
        )
        db_session.add(conn)
        db_session.commit()

        rule = NotificationRule(
            network_name="home",
            rule_type="high_bandwidth",
            config_json=json.dumps({
                "threshold_down_mbps": 100.0,
                "threshold_up_mbps": 50.0,
            }),
            cooldown_minutes=60,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        result = service.check_all_rules()
        assert result["notifications_sent"] == 1

    def test_high_bandwidth_below_threshold(self, db_session, config):
        device = Device(
            network_name="home",
            mac_address="aa:bb:cc:dd:ee:ff",
            nickname="Laptop",
        )
        db_session.add(device)
        db_session.commit()

        conn = DeviceConnection(
            device_id=device.id,
            network_name="home",
            bandwidth_down_mbps=50.0,
            bandwidth_up_mbps=10.0,
            timestamp=datetime.now(timezone.utc),
        )
        db_session.add(conn)
        db_session.commit()

        rule = NotificationRule(
            network_name="home",
            rule_type="high_bandwidth",
            config_json=json.dumps({
                "threshold_down_mbps": 100.0,
                "threshold_up_mbps": 50.0,
            }),
            cooldown_minutes=60,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        result = service.check_all_rules()
        assert result["notifications_sent"] == 0

    def test_send_test(self, db_session, config):
        service = self._make_service(db_session, config)
        result = service.send_test("Hello test")
        assert result is True
        service._apprise.notify.assert_called_once()

    def test_device_offline_detection(self, db_session, config):
        """Device with is_connected=False should trigger offline notification."""
        device = Device(
            network_name="home",
            mac_address="aa:bb:cc:dd:ee:ff",
            nickname="Smart TV",
            last_seen=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db_session.add(device)
        db_session.commit()

        # Latest connection shows device disconnected
        conn = DeviceConnection(
            device_id=device.id,
            network_name="home",
            is_connected=False,
            timestamp=datetime.now(timezone.utc),
        )
        db_session.add(conn)
        db_session.commit()

        rule = NotificationRule(
            network_name="home",
            rule_type="device_offline",
            config_json=json.dumps({"device_ids": [device.id]}),
            cooldown_minutes=60,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        result = service.check_all_rules()
        assert result["notifications_sent"] == 1
        service._apprise.notify.assert_called_once()

    def test_device_offline_no_connection_record(self, db_session, config):
        """Device with no connection records should trigger offline notification."""
        device = Device(
            network_name="home",
            mac_address="aa:bb:cc:dd:ee:ff",
            nickname="Smart TV",
        )
        db_session.add(device)
        db_session.commit()

        rule = NotificationRule(
            network_name="home",
            rule_type="device_offline",
            config_json=json.dumps({"device_ids": [device.id]}),
            cooldown_minutes=60,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        result = service.check_all_rules()
        assert result["notifications_sent"] == 1

    def test_device_offline_online_device_no_alert(self, db_session, config):
        """Device with is_connected=True should not trigger notification."""
        device = Device(
            network_name="home",
            mac_address="aa:bb:cc:dd:ee:ff",
            nickname="Smart TV",
            last_seen=datetime.now(timezone.utc),
        )
        db_session.add(device)
        db_session.commit()

        conn = DeviceConnection(
            device_id=device.id,
            network_name="home",
            is_connected=True,
            timestamp=datetime.now(timezone.utc),
        )
        db_session.add(conn)
        db_session.commit()

        rule = NotificationRule(
            network_name="home",
            rule_type="device_offline",
            config_json=json.dumps({"device_ids": [device.id]}),
            cooldown_minutes=60,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        result = service.check_all_rules()
        assert result["notifications_sent"] == 0

    def test_device_offline_resolves_when_online(self, db_session, config):
        """Device coming back online should resolve the event."""
        device = Device(
            network_name="home",
            mac_address="aa:bb:cc:dd:ee:ff",
            nickname="Smart TV",
            last_seen=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        db_session.add(device)
        db_session.commit()

        # Start disconnected
        conn = DeviceConnection(
            device_id=device.id,
            network_name="home",
            is_connected=False,
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=2),
        )
        db_session.add(conn)
        db_session.commit()

        rule = NotificationRule(
            network_name="home",
            rule_type="device_offline",
            config_json=json.dumps({"device_ids": [device.id]}),
            cooldown_minutes=60,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        service.check_all_rules()

        # Device comes back online - new connection record
        conn2 = DeviceConnection(
            device_id=device.id,
            network_name="home",
            is_connected=True,
            timestamp=datetime.now(timezone.utc),
        )
        db_session.add(conn2)
        db_session.commit()

        service.check_all_rules()

        history = db_session.query(NotificationHistory).first()
        assert history.resolved_at is not None

    def test_disabled_rule_skipped(self, db_session, config):
        """Disabled rules should not be checked."""
        rule = NotificationRule(
            network_name="home",
            rule_type="new_device",
            config_json="{}",
            cooldown_minutes=60,
            enabled=0,
        )
        db_session.add(rule)
        db_session.commit()

        service = self._make_service(db_session, config)
        result = service.check_all_rules()
        assert result["rules_checked"] == 0


class TestAppriseUrlsDB:
    """Test DB-backed Apprise URL helpers."""

    def test_get_apprise_urls_empty(self, db_session):
        from src.api.notifications import get_apprise_urls
        assert get_apprise_urls(db_session) is None

    def test_set_and_get_apprise_urls(self, db_session):
        from src.api.notifications import get_apprise_urls, set_apprise_urls
        set_apprise_urls(db_session, "json://stdout,slack://tok")
        assert get_apprise_urls(db_session) == "json://stdout,slack://tok"

    def test_set_apprise_urls_overwrites(self, db_session):
        from src.api.notifications import get_apprise_urls, set_apprise_urls
        set_apprise_urls(db_session, "json://stdout")
        set_apprise_urls(db_session, "slack://tok")
        assert get_apprise_urls(db_session) == "slack://tok"

    def test_get_apprise_urls_empty_string(self, db_session):
        from src.api.notifications import get_apprise_urls, set_apprise_urls
        set_apprise_urls(db_session, "")
        assert get_apprise_urls(db_session) is None
