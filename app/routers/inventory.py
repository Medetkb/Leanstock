from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.core.dependencies import get_current_user, require_manager
from app.database import get_session
from app.models.inventory import AuditLog, Inventory, InventoryTransfer, Location
from app.models.product import Product
from app.models.user import User
from app.services.email_service import send_low_stock_alert_email, send_transfer_notification_email

router = APIRouter(prefix="/inventory", tags=["Inventory"])
# Все маршруты начинаются с /inventory


class InventorySetRequest(BaseModel):
    product_id: int
    location_id: int
    quantity: int
    # Устанавливает абсолютное значение количества (не добавляет, а заменяет)


class TransferRequest(BaseModel):
    product_id: int
    from_location_id: int
    to_location_id: int
    quantity: int
    # Сколько единиц переместить


@router.get("")
def list_inventory(
    location_id: Optional[int] = None,
    cursor: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = select(Inventory).where(Inventory.tenant_id == current_user.tenant_id)
    if location_id:
        query = query.where(Inventory.location_id == location_id)
        # Фильтрация по конкретному складу
    if cursor:
        query = query.where(Inventory.id > cursor)
        # Cursor pagination — эффективнее чем OFFSET

    query = query.order_by(Inventory.id).limit(limit)
    items = session.exec(query).all()

    return {
        "items": items,
        "next_cursor": items[-1].id if len(items) == limit else None,
    }


@router.post("/set", status_code=201)
def set_inventory(
    body: InventorySetRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
):
    """Manually set inventory quantity for a product at a location."""
    # Ручная установка количества — используется для начальной загрузки данных
    if body.quantity < 0:
        raise HTTPException(status_code=422, detail="Quantity cannot be negative")

    product = session.exec(
        select(Product).where(
            Product.id == body.product_id,
            Product.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    location = session.exec(
        select(Location).where(
            Location.id == body.location_id,
            Location.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")

    existing = session.exec(
        select(Inventory).where(
            Inventory.product_id == body.product_id,
            Inventory.location_id == body.location_id,
        )
    ).first()

    if existing:
        existing.quantity = body.quantity
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        # Обновляем существующую запись
    else:
        inv = Inventory(
            product_id=body.product_id,
            location_id=body.location_id,
            tenant_id=current_user.tenant_id,
            quantity=body.quantity,
            updated_at=datetime.utcnow(),
        )
        session.add(inv)
        # Создаём новую запись если товара на этом складе ещё не было

    session.commit()
    return {"message": "Inventory updated"}


@router.post("/transfer")
def transfer_inventory(
    body: TransferRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
):
    """
    Atomically move stock between two locations.
    Uses SELECT FOR UPDATE to prevent race conditions (overselling).
    """
    # Атомарный трансфер: либо всё выполняется, либо ничего (транзакция)
    if body.from_location_id == body.to_location_id:
        raise HTTPException(status_code=400, detail="Source and destination must be different")

    if body.quantity <= 0:
        raise HTTPException(status_code=422, detail="Quantity must be positive")

    source = session.exec(
        select(Inventory).where(
            Inventory.product_id == body.product_id,
            Inventory.location_id == body.from_location_id,
            Inventory.tenant_id == current_user.tenant_id,
        ).with_for_update()
        # SELECT FOR UPDATE: блокирует строку в БД до конца транзакции
        # Если два трансфера одного товара запущены одновременно — второй ждёт первого
        # Предотвращает "overselling" — списание большего количества чем есть
    ).first()

    if not source:
        raise HTTPException(status_code=404, detail="No inventory found at the source location")

    if source.quantity < body.quantity:
        raise HTTPException(
            status_code=409,
            detail=f"Not enough stock. Available: {source.quantity}, Requested: {body.quantity}",
        )

    source.quantity -= body.quantity
    source.updated_at = datetime.utcnow()
    session.add(source)
    # Уменьшаем количество на складе-источнике

    dest = session.exec(
        select(Inventory).where(
            Inventory.product_id == body.product_id,
            Inventory.location_id == body.to_location_id,
            Inventory.tenant_id == current_user.tenant_id,
        )
    ).first()

    if dest:
        dest.quantity += body.quantity
        dest.updated_at = datetime.utcnow()
        session.add(dest)
    else:
        dest = Inventory(
            product_id=body.product_id,
            location_id=body.to_location_id,
            tenant_id=current_user.tenant_id,
            quantity=body.quantity,
            updated_at=datetime.utcnow(),
        )
        session.add(dest)
    # Увеличиваем количество на складе-получателе (создаём запись если её нет)

    transfer = InventoryTransfer(
        tenant_id=current_user.tenant_id,
        product_id=body.product_id,
        from_location_id=body.from_location_id,
        to_location_id=body.to_location_id,
        quantity=body.quantity,
        transferred_by=current_user.id,
    )
    session.add(transfer)
    # Сохраняем запись в историю трансферов

    log = AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="inventory_transfer",
        entity_type="inventory",
        entity_id=body.product_id,
        details=(
            f"Moved {body.quantity} units of product_id={body.product_id} "
            f"from location {body.from_location_id} to {body.to_location_id}"
        ),
    )
    session.add(log)
    # Пишем в audit log для истории действий

    session.flush()
    # flush() даёт нам transfer.id без финального commit — нужен для ответа
    transfer_id = transfer.id

    session.commit()
    # Commit: всё выше записывается атомарно. Блокировка SELECT FOR UPDATE снимается.

    product = session.get(Product, body.product_id)
    from_loc = session.get(Location, body.from_location_id)
    to_loc = session.get(Location, body.to_location_id)

    if product and from_loc and to_loc:
        background_tasks.add_task(
            send_transfer_notification_email,
            current_user.email,
            product.name,
            body.quantity,
            from_loc.name,
            to_loc.name,
        )
    # Отправляем email уведомление после commit — не блокирует ответ клиенту

    return {
        "message": "Transfer completed",
        "transfer_id": transfer_id,
        "product_id": body.product_id,
        "quantity": body.quantity,
    }


@router.get("/transfers")
def list_transfers(
    cursor: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = select(InventoryTransfer).where(
        InventoryTransfer.tenant_id == current_user.tenant_id
    )
    if cursor:
        query = query.where(InventoryTransfer.id < cursor)
        # Пагинация от новых к старым: берём ID меньше курсора

    query = query.order_by(InventoryTransfer.id.desc()).limit(limit)
    # desc() — сначала новые трансферы
    transfers = session.exec(query).all()

    return {
        "items": transfers,
        "next_cursor": transfers[-1].id if len(transfers) == limit else None,
    }


@router.get("/dead-stock")
def get_dead_stock(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List products that have been in inventory more than 30 days."""
    products = session.exec(
        select(Product).where(
            Product.tenant_id == current_user.tenant_id,
            Product.days_in_inventory > 30,
            Product.is_active == True,
        ).order_by(Product.days_in_inventory.desc())
    ).all()
    return {"count": len(products), "items": products}


@router.get("/forecast")
def get_forecast(
    location_id: Optional[int] = None,
    days_window: int = Query(default=30, ge=7, le=90),
    reorder_threshold_days: int = Query(default=7, ge=1, le=30),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Predictive reorder suggestions based on moving average of outbound transfers.

    For each product+location, calculates average daily consumption over the last
    `days_window` days, predicts days until stockout, and flags products that need
    reordering within `reorder_threshold_days`.
    """
    since = datetime.utcnow() - timedelta(days=days_window)

    inv_query = select(Inventory).where(Inventory.tenant_id == current_user.tenant_id)
    if location_id:
        inv_query = inv_query.where(Inventory.location_id == location_id)
    inventories = session.exec(inv_query).all()

    suggestions = []
    for inv in inventories:
        # Sum of units transferred OUT of this location in the window
        consumed = session.exec(
            select(func.coalesce(func.sum(InventoryTransfer.quantity), 0)).where(
                InventoryTransfer.product_id == inv.product_id,
                InventoryTransfer.from_location_id == inv.location_id,
                InventoryTransfer.tenant_id == current_user.tenant_id,
                InventoryTransfer.created_at >= since,
            )
        ).first() or 0

        avg_daily = consumed / days_window  # moving average units/day

        if avg_daily > 0:
            days_until_stockout = inv.quantity / avg_daily
        else:
            days_until_stockout = None  # no consumption data = unknown

        product = session.get(Product, inv.product_id)
        if not product or not product.is_active:
            continue

        needs_reorder = (
            days_until_stockout is not None
            and days_until_stockout <= reorder_threshold_days
        ) or (inv.quantity <= product.min_stock)

        if not needs_reorder and days_until_stockout is None:
            continue  # skip products with no consumption and adequate stock

        supplier_lead_days = 7  # default; would come from linked supplier
        reorder_qty = max(0, int(avg_daily * (reorder_threshold_days + supplier_lead_days)) - inv.quantity)

        suggestions.append({
            "product_id": inv.product_id,
            "product_name": product.name,
            "sku": product.sku,
            "location_id": inv.location_id,
            "current_quantity": inv.quantity,
            "min_stock": product.min_stock,
            "avg_daily_consumption": round(avg_daily, 3),
            "days_until_stockout": round(days_until_stockout, 1) if days_until_stockout is not None else None,
            "needs_reorder": needs_reorder,
            "suggested_reorder_qty": reorder_qty,
            "analysis_window_days": days_window,
        })

    suggestions.sort(key=lambda x: (x["days_until_stockout"] or 9999))
    return {"count": len(suggestions), "items": suggestions, "reorder_threshold_days": reorder_threshold_days}


@router.get("/low-stock")
def get_low_stock(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List products where current inventory is at or below min_stock threshold."""
    inventories = session.exec(
        select(Inventory).where(Inventory.tenant_id == current_user.tenant_id)
    ).all()

    results = []
    for inv in inventories:
        product = session.get(Product, inv.product_id)
        if product and product.is_active and product.min_stock > 0 and inv.quantity <= product.min_stock:
            results.append({
                "product_id": inv.product_id,
                "product_name": product.name,
                "sku": product.sku,
                "location_id": inv.location_id,
                "current_quantity": inv.quantity,
                "min_stock": product.min_stock,
                "shortage": product.min_stock - inv.quantity,
            })

    return {"count": len(results), "items": results}
