from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.dependencies import get_current_user, require_manager
from app.database import get_session
from app.models.inventory import AuditLog, Inventory, Location
from app.models.product import Product
from app.models.supplier import POStatus, PurchaseOrder, PurchaseOrderItem, Supplier
from app.models.user import User
from app.services.email_service import send_po_confirmation_email

router = APIRouter(prefix="/purchase-orders", tags=["Purchase Orders"])


class POItemInput(BaseModel):
    product_id: int
    quantity_ordered: int
    unit_price: float


class POCreate(BaseModel):
    supplier_id: int
    location_id: int
    items: List[POItemInput]
    notes: Optional[str] = None


class POReceiveItem(BaseModel):
    product_id: int
    quantity_received: int


class POReceive(BaseModel):
    items: List[POReceiveItem]


@router.get("")
def list_purchase_orders(
    status: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = select(PurchaseOrder).where(PurchaseOrder.tenant_id == current_user.tenant_id)
    if status:
        query = query.where(PurchaseOrder.status == status)
    query = query.order_by(PurchaseOrder.id.desc())
    orders = session.exec(query).all()

    result = []
    for po in orders:
        items = session.exec(
            select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == po.id)
        ).all()
        result.append({**po.model_dump(), "items": [i.model_dump() for i in items]})
    return {"items": result, "count": len(result)}


@router.post("", status_code=201)
def create_purchase_order(
    body: POCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
):
    if not body.items:
        raise HTTPException(status_code=422, detail="Purchase order must have at least one item")

    supplier = session.exec(
        select(Supplier).where(
            Supplier.id == body.supplier_id,
            Supplier.tenant_id == current_user.tenant_id,
            Supplier.is_active == True,
        )
    ).first()
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")

    location = session.exec(
        select(Location).where(
            Location.id == body.location_id,
            Location.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")

    po = PurchaseOrder(
        tenant_id=current_user.tenant_id,
        supplier_id=body.supplier_id,
        location_id=body.location_id,
        notes=body.notes,
        created_by=current_user.id,
        updated_at=datetime.utcnow(),
    )
    session.add(po)
    session.flush()

    for item in body.items:
        product = session.exec(
            select(Product).where(
                Product.id == item.product_id,
                Product.tenant_id == current_user.tenant_id,
            )
        ).first()
        if not product:
            raise HTTPException(status_code=404, detail=f"Product {item.product_id} not found")

        poi = PurchaseOrderItem(
            po_id=po.id,
            product_id=item.product_id,
            quantity_ordered=item.quantity_ordered,
            unit_price=item.unit_price,
        )
        session.add(poi)

    log = AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="purchase_order_created",
        entity_type="purchase_order",
        entity_id=po.id,
        details=f"PO created for supplier_id={body.supplier_id}, {len(body.items)} items",
    )
    session.add(log)
    session.commit()
    session.refresh(po)
    return {"id": po.id, "status": po.status, "message": "Purchase order created"}


@router.get("/{po_id}")
def get_purchase_order(
    po_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    po = session.exec(
        select(PurchaseOrder).where(
            PurchaseOrder.id == po_id,
            PurchaseOrder.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")

    items = session.exec(
        select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == po.id)
    ).all()
    return {**po.model_dump(), "items": [i.model_dump() for i in items]}


@router.post("/{po_id}/send")
def send_purchase_order(
    po_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
):
    po = session.exec(
        select(PurchaseOrder).where(
            PurchaseOrder.id == po_id,
            PurchaseOrder.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.status != POStatus.draft:
        raise HTTPException(status_code=409, detail=f"Cannot send PO with status '{po.status}'")

    supplier = session.get(Supplier, po.supplier_id)
    items = session.exec(
        select(PurchaseOrderItem).where(PurchaseOrderItem.po_id == po.id)
    ).all()

    po.status = POStatus.sent
    po.updated_at = datetime.utcnow()
    session.add(po)

    log = AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="purchase_order_sent",
        entity_type="purchase_order",
        entity_id=po.id,
        details=f"PO #{po.id} sent to supplier {supplier.name if supplier else po.supplier_id}",
    )
    session.add(log)
    session.commit()

    if supplier and supplier.email:
        item_list = [
            {"product_id": i.product_id, "qty": i.quantity_ordered, "price": i.unit_price}
            for i in items
        ]
        background_tasks.add_task(
            send_po_confirmation_email,
            supplier.email,
            po.id,
            supplier.name,
            item_list,
        )

    return {"message": f"Purchase order #{po_id} sent to supplier", "status": po.status}


@router.post("/{po_id}/receive")
def receive_purchase_order(
    po_id: int,
    body: POReceive,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
):
    po = session.exec(
        select(PurchaseOrder).where(
            PurchaseOrder.id == po_id,
            PurchaseOrder.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.status not in [POStatus.sent, POStatus.confirmed]:
        raise HTTPException(status_code=409, detail=f"Cannot receive PO with status '{po.status}'")

    for recv in body.items:
        poi = session.exec(
            select(PurchaseOrderItem).where(
                PurchaseOrderItem.po_id == po_id,
                PurchaseOrderItem.product_id == recv.product_id,
            )
        ).first()
        if not poi:
            raise HTTPException(
                status_code=404,
                detail=f"Product {recv.product_id} not in this PO",
            )

        poi.quantity_received += recv.quantity_received
        session.add(poi)

        # Add received stock to inventory at the PO's destination location
        inv = session.exec(
            select(Inventory).where(
                Inventory.product_id == recv.product_id,
                Inventory.location_id == po.location_id,
                Inventory.tenant_id == current_user.tenant_id,
            )
        ).first()
        if inv:
            inv.quantity += recv.quantity_received
            inv.updated_at = datetime.utcnow()
            session.add(inv)
        else:
            new_inv = Inventory(
                product_id=recv.product_id,
                location_id=po.location_id,
                tenant_id=current_user.tenant_id,
                quantity=recv.quantity_received,
                updated_at=datetime.utcnow(),
            )
            session.add(new_inv)

    po.status = POStatus.received
    po.updated_at = datetime.utcnow()
    session.add(po)

    log = AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="purchase_order_received",
        entity_type="purchase_order",
        entity_id=po.id,
        details=f"PO #{po.id} received, stock updated at location_id={po.location_id}",
    )
    session.add(log)
    session.commit()

    return {"message": f"Purchase order #{po_id} received and inventory updated"}


@router.post("/{po_id}/cancel")
def cancel_purchase_order(
    po_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
):
    po = session.exec(
        select(PurchaseOrder).where(
            PurchaseOrder.id == po_id,
            PurchaseOrder.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if po.status == POStatus.received:
        raise HTTPException(status_code=409, detail="Cannot cancel a received PO")

    po.status = POStatus.cancelled
    po.updated_at = datetime.utcnow()
    session.add(po)
    session.commit()
    return {"message": f"Purchase order #{po_id} cancelled"}
