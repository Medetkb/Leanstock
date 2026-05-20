from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.dependencies import get_current_user, require_manager
from app.database import get_session
from app.models.inventory import Location
from app.models.user import User

router = APIRouter(prefix="/locations", tags=["Locations"])
# Все маршруты начинаются с /locations


class LocationCreate(BaseModel):
    name: str
    # Название склада, например "Главный склад"
    address: Optional[str] = None
    city: Optional[str] = None


@router.get("")
def list_locations(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    locations = session.exec(
        select(Location).where(
            Location.tenant_id == current_user.tenant_id,
            # Только склады своей компании
            Location.is_active == True,
            # Деактивированные склады не показываем
        )
    ).all()
    return locations


@router.post("", status_code=201)
def create_location(
    body: LocationCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
    # Создавать склады могут только manager и admin
):
    location = Location(
        tenant_id=current_user.tenant_id,
        name=body.name,
        address=body.address,
        city=body.city,
    )
    session.add(location)
    session.commit()
    session.refresh(location)
    return location


@router.get("/{location_id}")
def get_location(
    location_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    loc = session.exec(
        select(Location).where(
            Location.id == location_id,
            Location.tenant_id == current_user.tenant_id,
            # tenant_id защищает от получения чужих складов
        )
    ).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    return loc


@router.delete("/{location_id}")
def delete_location(
    location_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
):
    loc = session.exec(
        select(Location).where(
            Location.id == location_id,
            Location.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")

    loc.is_active = False
    # Мягкое удаление — история инвентаря и трансферов для этого склада сохраняется
    session.add(loc)
    session.commit()
    return {"message": "Location deactivated"}
