"""Device Groups CRUD API endpoints."""

import logging
from typing import List, Optional

from sqlalchemy.orm import Session

from src.models.database import Device, DeviceGroup, DeviceGroupMember

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Business logic functions (testable without FastAPI)
# ---------------------------------------------------------------------------

def _group_to_dict(group: DeviceGroup) -> dict:
    """Convert a DeviceGroup ORM object to a response dict."""
    return {
        "id": group.id,
        "network_name": group.network_name,
        "name": group.name,
        "device_ids": [m.device_id for m in group.members],
    }


def create_device_group(
    db: Session,
    network_name: str,
    name: str,
    device_ids: List[int],
) -> dict:
    """Create a new device group with the given members.

    Validates:
    - At least one device_id is provided.
    - All device_ids belong to devices on the specified network.
    - No device is already in another group.
    """
    if not device_ids:
        raise ValueError("Group must contain at least one device")

    # Validate devices exist on the specified network
    devices = (
        db.query(Device)
        .filter(Device.id.in_(device_ids), Device.network_name == network_name)
        .all()
    )
    found_ids = {d.id for d in devices}
    missing = set(device_ids) - found_ids
    if missing:
        raise ValueError(
            f"One or more devices not found on this network"
        )

    # Check none are already in a group
    existing_members = (
        db.query(DeviceGroupMember)
        .filter(DeviceGroupMember.device_id.in_(device_ids))
        .all()
    )
    if existing_members:
        already_id = existing_members[0].device_id
        raise ValueError(f"Device {already_id} is already in a group")

    group = DeviceGroup(network_name=network_name, name=name)
    db.add(group)
    db.flush()

    for did in device_ids:
        db.add(DeviceGroupMember(group_id=group.id, device_id=did))
    db.commit()
    db.refresh(group)

    return _group_to_dict(group)


def list_device_groups(db: Session, network_name: str) -> list:
    """List all device groups for a network."""
    groups = (
        db.query(DeviceGroup)
        .filter(DeviceGroup.network_name == network_name)
        .all()
    )
    return [_group_to_dict(g) for g in groups]


def update_device_group(
    db: Session,
    group_id: int,
    name: Optional[str] = None,
    device_ids: Optional[List[int]] = None,
) -> dict:
    """Update a device group's name and/or members."""
    group = db.query(DeviceGroup).filter(DeviceGroup.id == group_id).first()
    if not group:
        raise ValueError("Group not found")

    if name is not None:
        group.name = name

    if device_ids is not None:
        if not device_ids:
            raise ValueError("Group must contain at least one device")

        # Validate devices exist on the group's network
        devices = (
            db.query(Device)
            .filter(Device.id.in_(device_ids), Device.network_name == group.network_name)
            .all()
        )
        found_ids = {d.id for d in devices}
        missing = set(device_ids) - found_ids
        if missing:
            raise ValueError(
                f"One or more devices not found on this network"
            )

        # Check none are already in a *different* group
        existing_members = (
            db.query(DeviceGroupMember)
            .filter(
                DeviceGroupMember.device_id.in_(device_ids),
                DeviceGroupMember.group_id != group_id,
            )
            .all()
        )
        if existing_members:
            already_id = existing_members[0].device_id
            raise ValueError(f"Device {already_id} is already in a group")

        # Replace members
        db.query(DeviceGroupMember).filter(
            DeviceGroupMember.group_id == group_id
        ).delete()
        for did in device_ids:
            db.add(DeviceGroupMember(group_id=group_id, device_id=did))

    db.commit()
    db.refresh(group)
    return _group_to_dict(group)


def delete_device_group(db: Session, group_id: int) -> None:
    """Delete a device group (members are cascade-deleted, devices are kept)."""
    group = db.query(DeviceGroup).filter(DeviceGroup.id == group_id).first()
    if not group:
        raise ValueError("Group not found")
    db.delete(group)
    db.commit()


# ---------------------------------------------------------------------------
# FastAPI route handlers
# ---------------------------------------------------------------------------

try:
    from fastapi import APIRouter, Depends, HTTPException
    from pydantic import BaseModel

    from src.utils.database import get_db

    router = APIRouter(prefix="/api", tags=["device-groups"])

    class CreateGroupRequest(BaseModel):
        """Request model for creating a device group."""
        network_name: str
        name: str
        device_ids: List[int]

    class UpdateGroupRequest(BaseModel):
        """Request model for updating a device group."""
        name: Optional[str] = None
        device_ids: Optional[List[int]] = None

    class GroupResponse(BaseModel):
        """Response model for a device group."""
        id: int
        network_name: str
        name: str
        device_ids: List[int]

    @router.get("/device-groups")
    def api_list_device_groups(
        network: Optional[str] = None,
        db: Session = Depends(get_db),
    ):
        """List device groups for a network."""
        if not network:
            first_device = db.query(Device).first()
            if first_device:
                network = first_device.network_name
            else:
                return []
        return list_device_groups(db, network)

    @router.post("/device-groups", status_code=201)
    def api_create_device_group(
        req: CreateGroupRequest,
        db: Session = Depends(get_db),
    ):
        """Create a new device group."""
        try:
            return create_device_group(db, req.network_name, req.name, req.device_ids)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.put("/device-groups/{group_id}")
    def api_update_device_group(
        group_id: int,
        req: UpdateGroupRequest,
        db: Session = Depends(get_db),
    ):
        """Update a device group."""
        try:
            return update_device_group(db, group_id, name=req.name, device_ids=req.device_ids)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.delete("/device-groups/{group_id}", status_code=204)
    def api_delete_device_group(
        group_id: int,
        db: Session = Depends(get_db),
    ):
        """Delete a device group."""
        try:
            delete_device_group(db, group_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

except ImportError:
    # FastAPI not available (e.g. in test environment without it installed).
    # Business logic functions above are still importable.
    router = None
