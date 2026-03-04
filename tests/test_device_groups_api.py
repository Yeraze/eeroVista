"""Tests for device groups CRUD API."""

import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.models.database import Base, Device, DeviceGroup, DeviceGroupMember


class TestDeviceGroupsCRUD:
    """Test device group CRUD operations at the data layer."""

    @pytest.fixture
    def db_session(self):
        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        session = SessionLocal()
        yield session
        session.close()

    @pytest.fixture
    def devices(self, db_session):
        devs = [
            Device(mac_address=f"aa:bb:cc:dd:ee:0{i}", network_name="home", hostname=f"dev-{i}")
            for i in range(4)
        ]
        db_session.add_all(devs)
        db_session.commit()
        return devs

    def test_create_group_with_members(self, db_session, devices):
        from src.api.device_groups import create_device_group
        result = create_device_group(
            db_session, network_name="home", name="Desktop",
            device_ids=[devices[0].id, devices[1].id]
        )
        assert result["name"] == "Desktop"
        assert len(result["device_ids"]) == 2
        assert result["id"] is not None

    def test_create_group_rejects_already_grouped_device(self, db_session, devices):
        from src.api.device_groups import create_device_group
        create_device_group(db_session, "home", "Group1", [devices[0].id])
        with pytest.raises(ValueError, match="already in a group"):
            create_device_group(db_session, "home", "Group2", [devices[0].id])

    def test_create_group_rejects_wrong_network(self, db_session, devices):
        from src.api.device_groups import create_device_group
        with pytest.raises(ValueError, match="not found"):
            create_device_group(db_session, "office", "Group", [devices[0].id])

    def test_list_groups(self, db_session, devices):
        from src.api.device_groups import create_device_group, list_device_groups
        create_device_group(db_session, "home", "Desktop", [devices[0].id, devices[1].id])
        create_device_group(db_session, "home", "Laptop", [devices[2].id])
        groups = list_device_groups(db_session, "home")
        assert len(groups) == 2

    def test_update_group_name(self, db_session, devices):
        from src.api.device_groups import create_device_group, update_device_group
        g = create_device_group(db_session, "home", "Old Name", [devices[0].id])
        updated = update_device_group(db_session, g["id"], name="New Name")
        assert updated["name"] == "New Name"

    def test_update_group_members(self, db_session, devices):
        from src.api.device_groups import create_device_group, update_device_group
        g = create_device_group(db_session, "home", "Desktop", [devices[0].id])
        updated = update_device_group(db_session, g["id"], device_ids=[devices[0].id, devices[1].id])
        assert len(updated["device_ids"]) == 2

    def test_delete_group(self, db_session, devices):
        from src.api.device_groups import create_device_group, delete_device_group, list_device_groups
        g = create_device_group(db_session, "home", "Desktop", [devices[0].id])
        delete_device_group(db_session, g["id"])
        assert len(list_device_groups(db_session, "home")) == 0
        assert db_session.query(Device).count() == 4

    def test_create_group_requires_at_least_one_device(self, db_session, devices):
        from src.api.device_groups import create_device_group
        with pytest.raises(ValueError, match="at least"):
            create_device_group(db_session, "home", "Empty", [])
