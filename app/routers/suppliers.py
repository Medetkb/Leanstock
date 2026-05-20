from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.dependencies import get_current_user, require_manager
from app.database import get_session
from app.models.supplier import Supplier
from app.models.user import User

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


class SupplierCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    lead_time_days: int = 7


class SupplierUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    lead_time_days: Optional[int] = None


@router.get("")
def list_suppliers(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    suppliers = session.exec(
        select(Supplier).where(
            Supplier.tenant_id == current_user.tenant_id,
            Supplier.is_active == True,
        )
    ).all()
    return {"items": suppliers, "count": len(suppliers)}


@router.post("", status_code=201)
def create_supplier(
    body: SupplierCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
):
    supplier = Supplier(
        tenant_id=current_user.tenant_id,
        name=body.name,
        email=body.email,
        phone=body.phone,
        lead_time_days=body.lead_time_days,
    )
    session.add(supplier)
    session.commit()
    session.refresh(supplier)
    return supplier


@router.get("/{supplier_id}")
def get_supplier(
    supplier_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    supplier = session.exec(
        select(Supplier).where(
            Supplier.id == supplier_id,
            Supplier.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


@router.put("/{supplier_id}")
def update_supplier(
    supplier_id: int,
    body: SupplierUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
):
    supplier = session.exec(
        select(Supplier).where(
            Supplier.id == supplier_id,
            Supplier.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    if body.name is not None:
        supplier.name = body.name
    if body.email is not None:
        supplier.email = body.email
    if body.phone is not None:
        supplier.phone = body.phone
    if body.lead_time_days is not None:
        supplier.lead_time_days = body.lead_time_days

    session.add(supplier)
    session.commit()
    session.refresh(supplier)
    return supplier


@router.delete("/{supplier_id}", status_code=204)
def delete_supplier(
    supplier_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
):
    supplier = session.exec(
        select(Supplier).where(
            Supplier.id == supplier_id,
            Supplier.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    supplier.is_active = False
    session.add(supplier)
    session.commit()
