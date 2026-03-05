"""Tests for DNS service hostname generation and timezone handling."""

import os
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, Device, DeviceConnection
from src.services.dns_service import sanitize_hostname, generate_hosts_file


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


class TestSanitizeHostname:
    """Test hostname sanitization."""

    def test_basic_name(self):
        assert sanitize_hostname("MyDevice") == "mydevice"

    def test_spaces_to_underscores(self):
        assert sanitize_hostname("Living Room") == "living_room"

    def test_special_characters_removed(self):
        assert sanitize_hostname("John's iPad!") == "johns_ipad"

    def test_empty_string(self):
        assert sanitize_hostname("") == ""

    def test_starts_with_non_alnum(self):
        assert sanitize_hostname("-device") == "device_-device"


class TestGenerateHostsFileTimezone:
    """Test that generate_hosts_file handles naive/aware datetime comparisons."""

    def _add_device_with_connection(self, db, name, ip, is_connected, timestamp):
        """Helper to add a device and its connection record."""
        device = Device(
            mac_address=f"AA:BB:CC:DD:EE:{name[:2].upper()}",
            nickname=name,
            hostname=name.lower(),
            network_name="home",
        )
        db.add(device)
        db.flush()

        conn = DeviceConnection(
            device_id=device.id,
            network_name="home",
            ip_address=ip,
            is_connected=is_connected,
            timestamp=timestamp,
        )
        db.add(conn)
        db.commit()
        return device

    def test_naive_timestamp_no_crash(self, db_session):
        """Offline device with naive timestamp should not raise TypeError."""
        # SQLite returns naive datetimes — simulate that
        naive_ts = datetime(2026, 3, 5, 10, 0, 0)  # no tzinfo
        self._add_device_with_connection(
            db_session, "OfflineDevice", "192.168.1.50",
            is_connected=False, timestamp=naive_ts,
        )

        with patch("src.services.dns_service.get_db_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = lambda s: db_session
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch("src.services.dns_service.reload_dnsmasq"):
                # Should not raise TypeError
                total, added = generate_hosts_file()

    def test_naive_timestamp_recent_offline_included(self, db_session, tmp_path):
        """Recently-offline device with naive timestamp should be included."""
        # 1 hour ago, naive (as SQLite would return)
        naive_ts = datetime.utcnow() - timedelta(hours=1)
        self._add_device_with_connection(
            db_session, "RecentOffline", "192.168.1.51",
            is_connected=False, timestamp=naive_ts,
        )

        hosts_file = str(tmp_path / "hosts")
        with patch("src.services.dns_service.get_db_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = lambda s: db_session
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch("src.services.dns_service.reload_dnsmasq"):
                with patch("src.services.dns_service.HOSTS_FILE_PATH", hosts_file):
                    total, added = generate_hosts_file()
                    assert added >= 1

    def test_naive_timestamp_old_offline_excluded(self, db_session, tmp_path):
        """Offline device last seen 48 hours ago should be excluded (default 24h window)."""
        naive_ts = datetime.utcnow() - timedelta(hours=48)
        self._add_device_with_connection(
            db_session, "OldOffline", "192.168.1.52",
            is_connected=False, timestamp=naive_ts,
        )

        hosts_file = str(tmp_path / "hosts")
        with patch("src.services.dns_service.get_db_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = lambda s: db_session
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch("src.services.dns_service.reload_dnsmasq"):
                with patch("src.services.dns_service.HOSTS_FILE_PATH", hosts_file):
                    total, added = generate_hosts_file()
                    assert added == 0

    def test_online_device_always_included(self, db_session, tmp_path):
        """Online device should always be included regardless of timestamp."""
        naive_ts = datetime.utcnow() - timedelta(hours=1)
        self._add_device_with_connection(
            db_session, "OnlineDevice", "192.168.1.53",
            is_connected=True, timestamp=naive_ts,
        )

        hosts_file = str(tmp_path / "hosts")
        with patch("src.services.dns_service.get_db_context") as mock_ctx:
            mock_ctx.return_value.__enter__ = lambda s: db_session
            mock_ctx.return_value.__exit__ = MagicMock(return_value=False)
            with patch("src.services.dns_service.reload_dnsmasq"):
                with patch("src.services.dns_service.HOSTS_FILE_PATH", hosts_file):
                    total, added = generate_hosts_file()
                    assert added == 1
