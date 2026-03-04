# Bonded Devices Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow users to group multiple device entries (different MAC addresses) into a single "bonded device" that displays as one row in the device list with aggregated stats.

**Architecture:** New `device_groups` and `device_group_members` tables store group membership. The `/api/devices` endpoint aggregates stats for grouped members at query time. A new CRUD API manages groups. The frontend adds a "Create Device Group" modal and modifies the device list/detail views.

**Tech Stack:** SQLAlchemy (models + migration), FastAPI (API endpoints), vanilla JS + Chart.js (frontend)

**Design doc:** `docs/plans/2026-03-04-bonded-devices-design.md`

---

### Task 1: Database Models

**Files:**
- Modify: `src/models/database.py` (after `DailyBandwidth` class, ~line 213)

**Step 1: Write the failing test**

Create `tests/test_device_groups.py`:

```python
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
        # Devices themselves are NOT deleted
        assert db_session.query(Device).count() == 2
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_device_groups.py -v`
Expected: ImportError for `DeviceGroup` and `DeviceGroupMember`

**Step 3: Write minimal implementation**

Add to `src/models/database.py` after the `DailyBandwidth` class (before `IpReservation`):

```python
class DeviceGroup(Base):
    __tablename__ = "device_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    network_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    members: Mapped[list["DeviceGroupMember"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class DeviceGroupMember(Base):
    __tablename__ = "device_group_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("device_groups.id", ondelete="CASCADE"), nullable=False)
    device_id: Mapped[int] = mapped_column(Integer, ForeignKey("devices.id"), nullable=False, unique=True)

    group: Mapped["DeviceGroup"] = relationship(back_populates="members")
    device: Mapped["Device"] = relationship()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_device_groups.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add src/models/database.py tests/test_device_groups.py
git commit -m "feat: add DeviceGroup and DeviceGroupMember models (#79)"
```

---

### Task 2: Database Migration

**Files:**
- Create: `src/migrations/008_add_device_groups.py`
- Modify: `src/migrations/runner.py` (line ~75, add to migrations list)

**Step 1: Write the migration file**

Create `src/migrations/008_add_device_groups.py`:

```python
import logging
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run(session: Session, eero_client) -> None:
    """Create device_groups and device_group_members tables."""
    engine = session.get_bind()
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if "device_groups" not in existing_tables:
        session.execute(text("""
            CREATE TABLE device_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                network_name TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        session.execute(text(
            "CREATE INDEX ix_device_groups_network_name ON device_groups (network_name)"
        ))
        logger.info("Created device_groups table")
    else:
        logger.info("device_groups table already exists")

    if "device_group_members" not in existing_tables:
        session.execute(text("""
            CREATE TABLE device_group_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL REFERENCES device_groups(id) ON DELETE CASCADE,
                device_id INTEGER NOT NULL REFERENCES devices(id),
                UNIQUE (device_id)
            )
        """))
        logger.info("Created device_group_members table")
    else:
        logger.info("device_group_members table already exists")

    session.commit()
    logger.info("Migration 008 completed")
```

**Step 2: Register the migration**

In `src/migrations/runner.py`, add to the `migrations` list after the `007` entry:

```python
('008_add_device_groups', 'src.migrations.008_add_device_groups', False),
```

**Step 3: Run tests to verify nothing broke**

Run: `python -m pytest tests/ -v`
Expected: All existing tests PASS

**Step 4: Commit**

```bash
git add src/migrations/008_add_device_groups.py src/migrations/runner.py
git commit -m "feat: add migration 008 for device_groups tables (#79)"
```

---

### Task 3: Device Groups CRUD API

**Files:**
- Create: `src/api/device_groups.py`
- Modify: `src/main.py` (add router include)
- Create: `tests/test_device_groups_api.py`

**Step 1: Write the failing tests**

Create `tests/test_device_groups_api.py`:

```python
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
        # Device still exists
        assert db_session.query(Device).count() == 4

    def test_create_group_requires_at_least_one_device(self, db_session, devices):
        from src.api.device_groups import create_device_group
        with pytest.raises(ValueError, match="at least"):
            create_device_group(db_session, "home", "Empty", [])
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_device_groups_api.py -v`
Expected: ImportError for `create_device_group`

**Step 3: Write the API module**

Create `src/api/device_groups.py`:

```python
"""Device Groups CRUD API for bonded devices."""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.models.database import Device, DeviceGroup, DeviceGroupMember
from src.api.health import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["device-groups"])


# --- Pydantic models ---

class CreateGroupRequest(BaseModel):
    network_name: str
    name: str
    device_ids: List[int]


class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    device_ids: Optional[List[int]] = None


# --- Business logic (testable without FastAPI) ---

def create_device_group(
    db: Session, network_name: str, name: str, device_ids: List[int]
) -> Dict[str, Any]:
    if not device_ids:
        raise ValueError("Group must contain at least one device")

    # Validate devices exist on the network
    devices = db.query(Device).filter(
        Device.id.in_(device_ids), Device.network_name == network_name
    ).all()
    if len(devices) != len(device_ids):
        raise ValueError("One or more devices not found on this network")

    # Check none are already grouped
    existing = db.query(DeviceGroupMember).filter(
        DeviceGroupMember.device_id.in_(device_ids)
    ).first()
    if existing:
        raise ValueError(f"Device {existing.device_id} is already in a group")

    group = DeviceGroup(network_name=network_name, name=name)
    db.add(group)
    db.flush()

    for did in device_ids:
        db.add(DeviceGroupMember(group_id=group.id, device_id=did))
    db.commit()

    return {"id": group.id, "name": group.name, "network_name": group.network_name,
            "device_ids": device_ids}


def list_device_groups(db: Session, network_name: str) -> List[Dict[str, Any]]:
    groups = db.query(DeviceGroup).filter(
        DeviceGroup.network_name == network_name
    ).all()
    result = []
    for g in groups:
        result.append({
            "id": g.id, "name": g.name, "network_name": g.network_name,
            "device_ids": [m.device_id for m in g.members],
        })
    return result


def update_device_group(
    db: Session, group_id: int, name: Optional[str] = None,
    device_ids: Optional[List[int]] = None
) -> Dict[str, Any]:
    group = db.query(DeviceGroup).filter(DeviceGroup.id == group_id).first()
    if not group:
        raise ValueError("Group not found")

    if name is not None:
        group.name = name

    if device_ids is not None:
        if not device_ids:
            raise ValueError("Group must contain at least one device")

        # Validate devices exist on the group's network
        devices = db.query(Device).filter(
            Device.id.in_(device_ids), Device.network_name == group.network_name
        ).all()
        if len(devices) != len(device_ids):
            raise ValueError("One or more devices not found on this network")

        # Check no conflicts (excluding current group members)
        current_member_ids = {m.device_id for m in group.members}
        new_ids = set(device_ids) - current_member_ids
        if new_ids:
            conflict = db.query(DeviceGroupMember).filter(
                DeviceGroupMember.device_id.in_(new_ids)
            ).first()
            if conflict:
                raise ValueError(f"Device {conflict.device_id} is already in a group")

        # Replace members
        db.query(DeviceGroupMember).filter(
            DeviceGroupMember.group_id == group.id
        ).delete()
        for did in device_ids:
            db.add(DeviceGroupMember(group_id=group.id, device_id=did))

    db.commit()
    return {"id": group.id, "name": group.name, "network_name": group.network_name,
            "device_ids": [m.device_id for m in group.members]}


def delete_device_group(db: Session, group_id: int) -> None:
    group = db.query(DeviceGroup).filter(DeviceGroup.id == group_id).first()
    if not group:
        raise ValueError("Group not found")
    db.delete(group)
    db.commit()


# --- FastAPI routes ---

@router.get("/device-groups")
async def api_list_groups(network: Optional[str] = None, db: Session = Depends(get_db)):
    from src.api.health import get_eero_client, get_default_network
    network_name = network or get_default_network(db)
    return {"groups": list_device_groups(db, network_name)}


@router.post("/device-groups")
async def api_create_group(req: CreateGroupRequest, db: Session = Depends(get_db)):
    try:
        result = create_device_group(db, req.network_name, req.name, req.device_ids)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/device-groups/{group_id}")
async def api_update_group(group_id: int, req: UpdateGroupRequest, db: Session = Depends(get_db)):
    try:
        result = update_device_group(db, group_id, name=req.name, device_ids=req.device_ids)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/device-groups/{group_id}")
async def api_delete_group(group_id: int, db: Session = Depends(get_db)):
    try:
        delete_device_group(db, group_id)
        return {"status": "deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
```

**Step 4: Register the router**

In `src/main.py`, add import and include after the existing routers:

```python
from src.api import device_groups
# ...
app.include_router(device_groups.router)
```

**Step 5: Run tests**

Run: `python -m pytest tests/test_device_groups_api.py -v`
Expected: All 9 tests PASS

**Step 6: Run full suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 7: Commit**

```bash
git add src/api/device_groups.py src/main.py tests/test_device_groups_api.py
git commit -m "feat: add device groups CRUD API (#79)"
```

---

### Task 4: Modify `/api/devices` to Aggregate Groups

**Files:**
- Modify: `src/api/health.py` (the `get_devices` function, lines ~601-793)

**Step 1: Write the failing test**

Add to `tests/test_device_groups.py`:

```python
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

        # Add connections
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

        # Group d1 and d2
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
        """Grouped devices should appear as one entry in the device list."""
        from src.api.health import build_devices_list
        devices_list = build_devices_list(db_session, "home")
        # Should be 2 entries: 1 group + 1 ungrouped device
        assert len(devices_list) == 2

    def test_grouped_entry_has_aggregated_bandwidth(self, db_session, grouped_devices):
        from src.api.health import build_devices_list
        devices_list = build_devices_list(db_session, "home")
        group_entry = next(d for d in devices_list if d.get("group_id"))
        assert group_entry["bandwidth_down_mbps"] == 150.0  # 50 + 100
        assert group_entry["bandwidth_up_mbps"] == 30.0     # 10 + 20

    def test_grouped_entry_has_best_signal(self, db_session, grouped_devices):
        from src.api.health import build_devices_list
        devices_list = build_devices_list(db_session, "home")
        group_entry = next(d for d in devices_list if d.get("group_id"))
        assert group_entry["signal_strength"] == -45  # best of -45 and None

    def test_grouped_entry_has_combined_connection_type(self, db_session, grouped_devices):
        from src.api.health import build_devices_list
        devices_list = build_devices_list(db_session, "home")
        group_entry = next(d for d in devices_list if d.get("group_id"))
        assert "Wired" in group_entry["connection_type"]
        assert "Wireless" in group_entry["connection_type"]

    def test_grouped_entry_has_member_details(self, db_session, grouped_devices):
        from src.api.health import build_devices_list
        devices_list = build_devices_list(db_session, "home")
        group_entry = next(d for d in devices_list if d.get("group_id"))
        assert "group_members" in group_entry
        assert len(group_entry["group_members"]) == 2

    def test_ungrouped_device_unchanged(self, db_session, grouped_devices):
        from src.api.health import build_devices_list
        devices_list = build_devices_list(db_session, "home")
        phone = next(d for d in devices_list if d.get("mac_address") == "aa:bb:cc:dd:ee:03")
        assert phone["hostname"] == "phone"
        assert phone.get("group_id") is None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_device_groups.py::TestDeviceGroupAggregation -v`
Expected: ImportError for `build_devices_list`

**Step 3: Refactor `get_devices` in `src/api/health.py`**

Extract the device-list-building logic from `get_devices()` into a new `build_devices_list(db, network_name)` function. Then add group aggregation logic. The key changes are:

1. Extract lines ~629-783 of `get_devices()` into `build_devices_list(db: Session, network_name: str) -> List[Dict]`
2. In `build_devices_list`, after building the initial `devices_list`:
   - Query all `DeviceGroup` + `DeviceGroupMember` for this network
   - For each group: collect its member devices from the already-built list, compute aggregated stats, create a group entry with `group_id`, `group_name`, `group_members`, and aggregated fields
   - Remove individual member devices from the top-level list
   - Add the group entries
3. `get_devices()` becomes a thin wrapper: calls `build_devices_list()` and returns `{"devices": result, "total": len(result)}`

Aggregation logic for a group:
```python
def _aggregate_group(group, member_entries):
    """Aggregate stats for a device group."""
    bandwidth_down = sum(m.get("bandwidth_down_mbps") or 0 for m in member_entries)
    bandwidth_up = sum(m.get("bandwidth_up_mbps") or 0 for m in member_entries)

    signals = [m["signal_strength"] for m in member_entries
               if m.get("signal_strength") is not None]
    best_signal = max(signals) if signals else None  # least negative = best

    is_online = any(m.get("is_online") for m in member_entries)

    conn_types = sorted({m.get("connection_type", "").capitalize()
                        for m in member_entries if m.get("connection_type")})
    connection_type = " + ".join(conn_types) if conn_types else "Unknown"

    ips = [m["ip_address"] for m in member_entries if m.get("ip_address")]
    ip_address = ", ".join(ips) if ips else None

    is_guest = any(m.get("is_guest") for m in member_entries)

    return {
        "name": group.name,
        "nickname": None,
        "hostname": None,
        "manufacturer": None,
        "type": "group",
        "ip_address": ip_address,
        "is_online": is_online,
        "is_guest": is_guest,
        "connection_type": connection_type,
        "signal_strength": best_signal,
        "bandwidth_down_mbps": bandwidth_down,
        "bandwidth_up_mbps": bandwidth_up,
        "node": ", ".join(sorted({m["node"] for m in member_entries if m.get("node") and m["node"] != "N/A"})) or "N/A",
        "mac_address": member_entries[0]["mac_address"],  # primary MAC for detail lookups
        "last_seen": max((m["last_seen"] for m in member_entries if m.get("last_seen")), default=None),
        "aliases": None,
        "group_id": group.id,
        "group_name": group.name,
        "group_members": member_entries,
    }
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_device_groups.py -v`
Expected: All tests PASS

**Step 5: Run full suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/api/health.py tests/test_device_groups.py
git commit -m "feat: aggregate grouped devices in /api/devices response (#79)"
```

---

### Task 5: Frontend — Create Device Group Modal

**Files:**
- Modify: `src/templates/devices.html`

**Step 1: Add "Create Device Group" button**

In the filter controls area (after the Show Guests checkbox, ~line 335), add:

```html
<button id="create-group-btn" class="btn"
    style="background: var(--ctp-blue); color: white; padding: 0.4rem 1rem; border: none; border-radius: 6px; cursor: pointer;">
    &#x1F517; Create Device Group
</button>
```

**Step 2: Add the group creation modal HTML**

After the existing `#device-modal` div (~line 379), add a new modal:

```html
<div id="group-modal" class="modal-overlay" style="display: none;">
    <div class="modal-content" style="max-width: 500px;">
        <div class="modal-header">
            <h2 class="modal-title">Create Device Group</h2>
            <button class="modal-close" id="group-modal-close">&times;</button>
        </div>
        <div class="modal-body">
            <label for="group-name-input" style="font-weight: 600;">Group Name:</label>
            <input type="text" id="group-name-input" placeholder="e.g., My Desktop"
                style="width: 100%; padding: 0.5rem; margin: 0.5rem 0 1rem; border: 1px solid var(--ctp-surface1); border-radius: 6px;">

            <label style="font-weight: 600;">Select Devices:</label>
            <input type="text" id="group-device-filter" placeholder="Filter devices..."
                style="width: 100%; padding: 0.4rem; margin: 0.5rem 0; border: 1px solid var(--ctp-surface1); border-radius: 6px;">
            <div id="group-device-list" style="max-height: 300px; overflow-y: auto; border: 1px solid var(--ctp-surface1); border-radius: 6px; padding: 0.5rem;">
                <!-- Populated by JS -->
            </div>

            <div style="display: flex; gap: 0.5rem; margin-top: 1rem; justify-content: flex-end;">
                <button id="group-cancel-btn" class="btn"
                    style="padding: 0.4rem 1rem; border: 1px solid var(--ctp-surface1); border-radius: 6px; cursor: pointer;">
                    Cancel
                </button>
                <button id="group-save-btn" class="btn"
                    style="background: var(--ctp-green); color: white; padding: 0.4rem 1rem; border: none; border-radius: 6px; cursor: pointer;">
                    Create Group
                </button>
            </div>
        </div>
    </div>
</div>
```

**Step 3: Add JavaScript for the modal**

Add these functions to the `<script>` section:

```javascript
let deviceGroupsData = [];

async function loadDeviceGroups() {
    const network = document.getElementById('network-selector').value;
    try {
        const resp = await fetch(`/api/device-groups?network=${encodeURIComponent(network)}`);
        const data = await resp.json();
        deviceGroupsData = data.groups || [];
    } catch (e) {
        console.error('Failed to load device groups:', e);
        deviceGroupsData = [];
    }
}

function openGroupModal(editGroupId = null) {
    const modal = document.getElementById('group-modal');
    const nameInput = document.getElementById('group-name-input');
    const saveBtn = document.getElementById('group-save-btn');
    const title = modal.querySelector('.modal-title');

    if (editGroupId) {
        const group = deviceGroupsData.find(g => g.id === editGroupId);
        title.textContent = 'Edit Device Group';
        saveBtn.textContent = 'Save Changes';
        nameInput.value = group ? group.name : '';
        modal.dataset.editGroupId = editGroupId;
    } else {
        title.textContent = 'Create Device Group';
        saveBtn.textContent = 'Create Group';
        nameInput.value = '';
        delete modal.dataset.editGroupId;
    }

    populateGroupDeviceList(editGroupId);
    modal.style.display = 'flex';
}

function populateGroupDeviceList(editGroupId = null) {
    const container = document.getElementById('group-device-list');
    // Get IDs of devices already in other groups
    const groupedDeviceIds = new Set();
    let currentGroupDeviceIds = new Set();
    deviceGroupsData.forEach(g => {
        g.device_ids.forEach(id => {
            if (editGroupId && g.id === editGroupId) {
                currentGroupDeviceIds.add(id);
            } else {
                groupedDeviceIds.add(id);
            }
        });
    });

    // Filter to ungrouped devices (+ current group members if editing)
    const available = devicesData.filter(d => {
        if (d.group_id && d.group_id !== editGroupId) return false;
        // For ungrouped devices, check by device_id if available
        return true;
    });

    container.innerHTML = available.map(d => {
        const name = d.name || d.mac_address;
        const checked = d.group_id === editGroupId ? 'checked' : '';
        return `<label style="display: flex; align-items: center; padding: 0.3rem; gap: 0.5rem; cursor: pointer;">
            <input type="checkbox" class="group-device-checkbox" value="${d.mac_address}" ${checked}>
            <span>${name}</span>
            <span style="color: var(--ctp-subtext0); font-size: 0.85rem; margin-left: auto;">${d.mac_address}</span>
        </label>`;
    }).join('');
}

function closeGroupModal() {
    document.getElementById('group-modal').style.display = 'none';
}

async function saveDeviceGroup() {
    const modal = document.getElementById('group-modal');
    const name = document.getElementById('group-name-input').value.trim();
    if (!name) { alert('Please enter a group name.'); return; }

    const checked = [...document.querySelectorAll('.group-device-checkbox:checked')];
    if (checked.length < 2) { alert('Select at least 2 devices to group.'); return; }

    const selectedMacs = checked.map(cb => cb.value);
    // We need device IDs, not MACs — look them up from the full device data
    // The /api/devices endpoint needs to return device IDs for this to work.
    // For now, send MAC addresses and let the backend resolve them.
    const network = document.getElementById('network-selector').value;
    const editGroupId = modal.dataset.editGroupId;

    try {
        let resp;
        if (editGroupId) {
            resp = await fetch(`/api/device-groups/${editGroupId}`, {
                method: 'PUT',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name, mac_addresses: selectedMacs }),
            });
        } else {
            resp = await fetch('/api/device-groups', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ network_name: network, name, mac_addresses: selectedMacs }),
            });
        }

        if (!resp.ok) {
            const err = await resp.json();
            alert(err.detail || 'Failed to save group.');
            return;
        }

        closeGroupModal();
        await loadDeviceGroups();
        await loadDevices();
    } catch (e) {
        alert('Error saving group: ' + e.message);
    }
}

async function deleteDeviceGroup(groupId) {
    if (!confirm('Are you sure you want to ungroup these devices?')) return;
    try {
        const resp = await fetch(`/api/device-groups/${groupId}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Failed to delete group');
        await loadDeviceGroups();
        await loadDevices();
    } catch (e) {
        alert('Error deleting group: ' + e.message);
    }
}
```

**Step 4: Wire up event listeners**

Add to the existing event listener setup section:

```javascript
document.getElementById('create-group-btn').addEventListener('click', () => openGroupModal());
document.getElementById('group-modal-close').addEventListener('click', closeGroupModal);
document.getElementById('group-cancel-btn').addEventListener('click', closeGroupModal);
document.getElementById('group-save-btn').addEventListener('click', saveDeviceGroup);
document.getElementById('group-modal').addEventListener('click', (e) => {
    if (e.target.id === 'group-modal') closeGroupModal();
});
document.getElementById('group-device-filter').addEventListener('input', (e) => {
    const filter = e.target.value.toLowerCase();
    document.querySelectorAll('#group-device-list label').forEach(label => {
        label.style.display = label.textContent.toLowerCase().includes(filter) ? 'flex' : 'none';
    });
});
```

**Step 5: Update `initialize()` to load groups**

```javascript
async function initialize() {
    await loadNetworks();
    await loadDeviceGroups();
    loadDevices();
    loadRoutingData();
}
```

**Step 6: Commit**

```bash
git add src/templates/devices.html
git commit -m "feat: add Create Device Group modal to devices page (#79)"
```

---

### Task 6: Frontend — Render Grouped Devices in Table

**Files:**
- Modify: `src/templates/devices.html` (the `renderDevices()` function, ~line 576)

**Step 1: Modify `renderDevices()` to handle group entries**

In the `renderDevices()` function, when iterating devices and building `<tr>` rows, detect group entries by checking `device.group_id`. For group entries:

- Show a link icon (&#x1F517;) before the name
- Use `device.group_name` for the name column
- The onclick should call `showGroupDetails(device)` instead of `showDeviceDetails(index)`

```javascript
// Inside renderDevices(), when building the row HTML:
const isGroup = !!device.group_id;
const nameDisplay = isGroup
    ? `&#x1F517; ${device.group_name || device.name}`
    : `${getDeviceEmoji(device.type)} ${device.name}`;
const rowOnclick = isGroup
    ? `showGroupDetails(${JSON.stringify(device).replace(/"/g, '&quot;')})`
    : `showDeviceDetails(${originalIndex})`;
```

**Step 2: Commit**

```bash
git add src/templates/devices.html
git commit -m "feat: render grouped devices as single row in device table (#79)"
```

---

### Task 7: Frontend — Group Detail Modal View

**Files:**
- Modify: `src/templates/devices.html`

**Step 1: Add `showGroupDetails()` function**

```javascript
function showGroupDetails(groupDevice) {
    const modal = document.getElementById('device-modal');
    const title = document.getElementById('modal-title');
    const body = document.getElementById('modal-body');

    title.textContent = groupDevice.group_name;

    let html = `
        <div style="display: flex; gap: 0.5rem; margin-bottom: 1rem;">
            <button onclick="openGroupModal(${groupDevice.group_id})"
                class="btn" style="padding: 0.3rem 0.8rem; border: 1px solid var(--ctp-blue); color: var(--ctp-blue); border-radius: 6px; cursor: pointer;">
                Edit Group
            </button>
            <button onclick="deleteDeviceGroup(${groupDevice.group_id})"
                class="btn" style="padding: 0.3rem 0.8rem; border: 1px solid var(--ctp-red); color: var(--ctp-red); border-radius: 6px; cursor: pointer;">
                Ungroup
            </button>
        </div>

        <div class="info-grid" style="display: grid; grid-template-columns: auto 1fr; gap: 0.3rem 1rem; margin-bottom: 1rem;">
            <span style="font-weight: 600;">Status:</span>
            <span>${groupDevice.is_online ? '🟢 Online' : '🔴 Offline'}</span>
            <span style="font-weight: 600;">Connection:</span>
            <span>${groupDevice.connection_type || 'N/A'}</span>
            <span style="font-weight: 600;">IP Address:</span>
            <span>${groupDevice.ip_address || 'N/A'}</span>
            <span style="font-weight: 600;">Bandwidth Down:</span>
            <span>${groupDevice.bandwidth_down_mbps != null ? groupDevice.bandwidth_down_mbps.toFixed(1) + ' Mbps' : 'N/A'}</span>
            <span style="font-weight: 600;">Bandwidth Up:</span>
            <span>${groupDevice.bandwidth_up_mbps != null ? groupDevice.bandwidth_up_mbps.toFixed(1) + ' Mbps' : 'N/A'}</span>
            <span style="font-weight: 600;">Signal:</span>
            <span>${groupDevice.signal_strength != null ? groupDevice.signal_strength + ' dBm' : 'N/A'}</span>
        </div>

        <h3 style="margin-top: 1rem; margin-bottom: 0.5rem;">Member Devices</h3>
        <table class="table" style="font-size: 0.9rem;">
            <thead>
                <tr>
                    <th>Name</th><th>MAC</th><th>Connection</th><th>IP</th><th>Bandwidth</th><th>Signal</th>
                </tr>
            </thead>
            <tbody>
                ${(groupDevice.group_members || []).map(m => `
                    <tr>
                        <td>${m.name || m.mac_address}</td>
                        <td style="font-family: monospace; font-size: 0.85rem;">${m.mac_address}</td>
                        <td>${m.connection_type || 'N/A'}</td>
                        <td>${m.ip_address || 'N/A'}</td>
                        <td>${m.bandwidth_down_mbps != null ? m.bandwidth_down_mbps.toFixed(1) : '0'} / ${m.bandwidth_up_mbps != null ? m.bandwidth_up_mbps.toFixed(1) : '0'} Mbps</td>
                        <td>${m.signal_strength != null ? m.signal_strength + ' dBm' : 'N/A'}</td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;

    body.innerHTML = html;
    modal.style.display = 'flex';
}
```

**Step 2: Commit**

```bash
git add src/templates/devices.html
git commit -m "feat: add group detail view in device modal (#79)"
```

---

### Task 8: API Adjustment — Accept MAC Addresses in Group CRUD

**Files:**
- Modify: `src/api/device_groups.py`

The frontend sends MAC addresses (since that's what the device list has). Update the Pydantic models and business logic to accept `mac_addresses` instead of (or in addition to) `device_ids`, resolving MACs to device IDs internally.

**Step 1: Update Pydantic models**

```python
class CreateGroupRequest(BaseModel):
    network_name: str
    name: str
    mac_addresses: List[str]

class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    mac_addresses: Optional[List[str]] = None
```

**Step 2: Add MAC resolution helper**

```python
def _resolve_mac_to_device_ids(db: Session, network_name: str, mac_addresses: List[str]) -> List[int]:
    devices = db.query(Device).filter(
        Device.mac_address.in_(mac_addresses),
        Device.network_name == network_name,
    ).all()
    if len(devices) != len(mac_addresses):
        found_macs = {d.mac_address for d in devices}
        missing = [m for m in mac_addresses if m not in found_macs]
        raise ValueError(f"Devices not found on network: {missing}")
    return [d.id for d in devices]
```

**Step 3: Update route handlers to resolve MACs before calling business logic**

**Step 4: Also update `GET /api/devices` response to include `device_id` for each device**

In `src/api/health.py`, add `"device_id": device.id` to each device dict in `build_devices_list()`. This allows the frontend to reference devices by ID if needed.

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/api/device_groups.py src/api/health.py
git commit -m "feat: accept MAC addresses in group CRUD, return device_id in /api/devices (#79)"
```

---

### Task 9: Integration Testing & Polish

**Files:**
- All modified files

**Step 1: Manual testing checklist**

Run the app with `docker compose up` and verify:

- [ ] Device list loads normally with no groups
- [ ] "Create Device Group" button visible
- [ ] Modal opens, shows ungrouped devices
- [ ] Can create a group with 2+ devices
- [ ] Group appears as single row with aggregated stats
- [ ] Clicking group row shows detail modal with member breakdown
- [ ] "Edit Group" button works (rename, add/remove members)
- [ ] "Ungroup" button deletes the group, devices reappear individually
- [ ] Prometheus `/metrics` endpoint unchanged
- [ ] Network topology page unchanged
- [ ] Creating a group with a device already in another group shows error

**Step 2: Run full test suite one final time**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 3: Final commit if any polish needed**

```bash
git add -A
git commit -m "feat: polish bonded devices feature (#79)"
```
