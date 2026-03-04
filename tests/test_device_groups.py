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
