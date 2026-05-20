from enum import Enum
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


class Supplier(SQLModel, table=True):
    __tablename__ = "suppliers"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    lead_time_days: int = Field(default=7)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class POStatus(str, Enum):
    draft = "draft"
    sent = "sent"
    confirmed = "confirmed"
    received = "received"
    cancelled = "cancelled"


class PurchaseOrder(SQLModel, table=True):
    __tablename__ = "purchase_orders"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    supplier_id: int = Field(foreign_key="suppliers.id", index=True)
    location_id: int = Field(foreign_key="locations.id")
    status: POStatus = Field(default=POStatus.draft)
    notes: Optional[str] = None
    created_by: int = Field(foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PurchaseOrderItem(SQLModel, table=True):
    __tablename__ = "purchase_order_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    po_id: int = Field(foreign_key="purchase_orders.id", index=True)
    product_id: int = Field(foreign_key="products.id")
    quantity_ordered: int
    quantity_received: int = Field(default=0)
    unit_price: float
