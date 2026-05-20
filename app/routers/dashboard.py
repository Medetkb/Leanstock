from datetime import datetime

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from app.core.dependencies import get_current_user
from app.database import get_session
from app.models.inventory import AuditLog, Inventory, InventoryTransfer, Location
from app.models.product import Product
from app.models.reservation import Reservation, ReservationStatus
from app.models.supplier import POStatus, PurchaseOrder
from app.models.user import User

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("")
def get_dashboard(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Business stats snapshot for the current tenant."""
    tid = current_user.tenant_id
    now = datetime.utcnow()

    # ── Counts ────────────────────────────────────────────────────────────────
    product_count = session.exec(
        select(func.count(Product.id)).where(
            Product.tenant_id == tid, Product.is_active == True
        )
    ).first() or 0

    location_count = session.exec(
        select(func.count(Location.id)).where(
            Location.tenant_id == tid, Location.is_active == True
        )
    ).first() or 0

    dead_stock_count = session.exec(
        select(func.count(Product.id)).where(
            Product.tenant_id == tid,
            Product.days_in_inventory > 30,
            Product.is_active == True,
        )
    ).first() or 0

    active_reservations = session.exec(
        select(func.count(Reservation.id)).where(
            Reservation.tenant_id == tid,
            Reservation.status == ReservationStatus.active,
            Reservation.expires_at > now,
        )
    ).first() or 0

    pending_pos = session.exec(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.tenant_id == tid,
            PurchaseOrder.status.in_([POStatus.draft, POStatus.sent]),
        )
    ).first() or 0

    # ── Inventory value ───────────────────────────────────────────────────────
    # Sum of (quantity × price) across all inventory rows
    inventories = session.exec(
        select(Inventory).where(Inventory.tenant_id == tid)
    ).all()
    inventory_value = 0.0
    total_units = 0
    for inv in inventories:
        product = session.get(Product, inv.product_id)
        if product and product.is_active:
            effective_price = product.price * (1 - product.current_discount / 100)
            inventory_value += inv.quantity * effective_price
            total_units += inv.quantity

    # ── Low stock ─────────────────────────────────────────────────────────────
    low_stock_count = sum(
        1 for inv in inventories
        if (p := session.get(Product, inv.product_id))
        and p.is_active and p.min_stock > 0 and inv.quantity <= p.min_stock
    )

    # ── Recent transfers (last 5) ─────────────────────────────────────────────
    recent_transfers = session.exec(
        select(InventoryTransfer)
        .where(InventoryTransfer.tenant_id == tid)
        .order_by(InventoryTransfer.id.desc())
        .limit(5)
    ).all()

    transfer_details = []
    for t in recent_transfers:
        product = session.get(Product, t.product_id)
        from_loc = session.get(Location, t.from_location_id)
        to_loc = session.get(Location, t.to_location_id)
        transfer_details.append({
            "id": t.id,
            "product": product.name if product else f"#{t.product_id}",
            "qty": t.quantity,
            "from": from_loc.name if from_loc else f"#{t.from_location_id}",
            "to": to_loc.name if to_loc else f"#{t.to_location_id}",
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    # ── Recent audit events (last 5) ─────────────────────────────────────────
    recent_logs = session.exec(
        select(AuditLog)
        .where(AuditLog.tenant_id == tid)
        .order_by(AuditLog.id.desc())
        .limit(5)
    ).all()

    return {
        "products": product_count,
        "locations": location_count,
        "total_units": total_units,
        "inventory_value": round(inventory_value, 2),
        "dead_stock": dead_stock_count,
        "low_stock": low_stock_count,
        "active_reservations": active_reservations,
        "pending_purchase_orders": pending_pos,
        "recent_transfers": transfer_details,
        "recent_events": [
            {
                "action": l.action,
                "entity_type": l.entity_type,
                "details": l.details,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in recent_logs
        ],
    }
