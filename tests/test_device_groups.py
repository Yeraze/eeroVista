"""Tests for device group (bonded devices) functionality."""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, Device, DeviceGroup, DeviceGroupMember


class TestDeviceGroupModel:
    """Test DeviceGroup and DeviceGroupMember database models."""

    @pytest.fixture
    def db_session(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        yield session
        session.close()

    @pytest.fixture
    def two_devices(self, db_session):
        d1 = Device(mac_address="aa:bb:cc:dd:ee:01", network_name="home", hostname="dev-wifi")
        d2 = Device(mac_address="aa:bb:cc:dd:ee:02", network_name="home", hostname="dev-eth")
        db_session.add_all([d1, d2])
        db_session.commit()
        return d1, d2

    def test_create_group(self, db_session, two_devices):
        d1, d2 = two_devices
        group = DeviceGroup(network_name="home", name="My Desktop")
        db_session.add(group)
        db_session.flush()

        m1 = DeviceGroupMember(group_id=group.id, device_id=d1.id)
        m2 = DeviceGroupMember(group_id=group.id, device_id=d2.id)
        db_session.add_all([m1, m2])
        db_session.commit()

        assert group.id is not None
        assert len(group.members) == 2

    def test_device_unique_to_one_group(self, db_session, two_devices):
        d1, _ = two_devices
        g1 = DeviceGroup(network_name="home", name="Group 1")
        g2 = DeviceGroup(network_name="home", name="Group 2")
        db_session.add_all([g1, g2])
        db_session.flush()

        db_session.add(DeviceGroupMember(group_id=g1.id, device_id=d1.id))
        db_session.commit()

        db_session.add(DeviceGroupMember(group_id=g2.id, device_id=d1.id))
        with pytest.raises(Exception):
            db_session.commit()

    def test_cascade_delete_group(self, db_session, two_devices):
        d1, d2 = two_devices
        group = DeviceGroup(network_name="home", name="My Desktop")
        db_session.add(group)
        db_session.flush()
        db_session.add_all([
            DeviceGroupMember(group_id=group.id, device_id=d1.id),
            DeviceGroupMember(group_id=group.id, device_id=d2.id),
        ])
        db_session.commit()

        db_session.delete(group)
        db_session.commit()

        assert db_session.query(DeviceGroupMember).count() == 0
        assert db_session.query(Device).count() == 2


class TestDeviceGroupAggregation:
    """Test that /api/devices returns aggregated stats for grouped devices."""

    @pytest.fixture
    def db_session(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        yield session
        session.close()

    @pytest.fixture
    def grouped_devices(self, db_session):
        """Create two devices with connections, grouped together."""
        from src.models.database import DeviceConnection, EeroNode
        d1 = Device(mac_address="aa:bb:cc:dd:ee:01", network_name="home", hostname="desktop-wifi")
        d2 = Device(mac_address="aa:bb:cc:dd:ee:02", network_name="home", hostname="desktop-eth")
        d3 = Device(mac_address="aa:bb:cc:dd:ee:03", network_name="home", hostname="phone")
        db_session.add_all([d1, d2, d3])
        db_session.commit()

        now = datetime.utcnow()
        db_session.add(DeviceConnection(
            device_id=d1.id, network_name="home", timestamp=now,
            is_connected=True, connection_type="wireless", signal_strength=-45,
            bandwidth_down_mbps=50.0, bandwidth_up_mbps=10.0, ip_address="192.168.1.10",
        ))
        db_session.add(DeviceConnection(
            device_id=d2.id, network_name="home", timestamp=now,
            is_connected=True, connection_type="wired", signal_strength=None,
            bandwidth_down_mbps=100.0, bandwidth_up_mbps=20.0, ip_address="192.168.1.11",
        ))
        db_session.add(DeviceConnection(
            device_id=d3.id, network_name="home", timestamp=now,
            is_connected=True, connection_type="wireless", signal_strength=-60,
            bandwidth_down_mbps=25.0, bandwidth_up_mbps=5.0, ip_address="192.168.1.12",
        ))
        db_session.commit()

        group = DeviceGroup(network_name="home", name="My Desktop")
        db_session.add(group)
        db_session.flush()
        db_session.add_all([
            DeviceGroupMember(group_id=group.id, device_id=d1.id),
            DeviceGroupMember(group_id=group.id, device_id=d2.id),
        ])
        db_session.commit()
        return d1, d2, d3, group

    def test_grouped_devices_return_single_entry(self, db_session, grouped_devices):
        from src.services.device_service import build_devices_list
        devices_list = build_devices_list(db_session, "home")
        assert len(devices_list) == 2

    def test_grouped_entry_has_aggregated_bandwidth(self, db_session, grouped_devices):
        from src.services.device_service import build_devices_list
        devices_list = build_devices_list(db_session, "home")
        group_entry = next(d for d in devices_list if d.get("group_id"))
        assert group_entry["bandwidth_down_mbps"] == 150.0
        assert group_entry["bandwidth_up_mbps"] == 30.0

    def test_grouped_entry_has_best_signal(self, db_session, grouped_devices):
        from src.services.device_service import build_devices_list
        devices_list = build_devices_list(db_session, "home")
        group_entry = next(d for d in devices_list if d.get("group_id"))
        assert group_entry["signal_strength"] == -45

    def test_grouped_entry_has_combined_connection_type(self, db_session, grouped_devices):
        from src.services.device_service import build_devices_list
        devices_list = build_devices_list(db_session, "home")
        group_entry = next(d for d in devices_list if d.get("group_id"))
        assert "Wired" in group_entry["connection_type"]
        assert "Wireless" in group_entry["connection_type"]

    def test_grouped_entry_has_member_details(self, db_session, grouped_devices):
        from src.services.device_service import build_devices_list
        devices_list = build_devices_list(db_session, "home")
        group_entry = next(d for d in devices_list if d.get("group_id"))
        assert "group_members" in group_entry
        assert len(group_entry["group_members"]) == 2

    def test_ungrouped_device_unchanged(self, db_session, grouped_devices):
        from src.services.device_service import build_devices_list
        devices_list = build_devices_list(db_session, "home")
        phone = next(d for d in devices_list if d.get("mac_address") == "aa:bb:cc:dd:ee:03")
        assert phone["hostname"] == "phone"
        assert phone.get("group_id") is None
