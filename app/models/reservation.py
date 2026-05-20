from enum import Enum
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


class ReservationStatus(str, Enum):
    active = "active"
    released = "released"
    expired = "expired"


class Reservation(SQLModel, table=True):
    __tablename__ = "reservations"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    product_id: int = Field(foreign_key="products.id", index=True)
    location_id: int = Field(foreign_key="locations.id")
    quantity: int
    reserved_by: int = Field(foreign_key="users.id")
    status: ReservationStatus = Field(default=ReservationStatus.active)
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)
