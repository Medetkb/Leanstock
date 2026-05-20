from datetime import datetime, timedelta
from typing import Optional

import redis as redis_lib
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.config import settings
from app.core.dependencies import get_current_user
from app.database import get_session
from app.models.inventory import AuditLog, Inventory
from app.models.product import Product
from app.models.reservation import Reservation, ReservationStatus
from app.models.user import User

router = APIRouter(prefix="/reservations", tags=["Reservations"])

_redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


class ReservationCreate(BaseModel):
    product_id: int
    location_id: int
    quantity: int
    ttl_minutes: int = 30


@router.post("", status_code=201)
def create_reservation(
    body: ReservationCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if body.quantity <= 0:
        raise HTTPException(status_code=422, detail="Quantity must be positive")
    if body.ttl_minutes < 1 or body.ttl_minutes > 1440:
        raise HTTPException(status_code=422, detail="ttl_minutes must be between 1 and 1440")

    # Redis distributed lock prevents double-reservation race conditions
    lock_key = f"res_lock:{body.product_id}:{body.location_id}"
    acquired = _redis.set(lock_key, "1", nx=True, ex=30)
    if not acquired:
        raise HTTPException(status_code=409, detail="Another reservation in progress, retry in a moment")

    try:
        inv = session.exec(
            select(Inventory).where(
                Inventory.product_id == body.product_id,
                Inventory.location_id == body.location_id,
                Inventory.tenant_id == current_user.tenant_id,
            ).with_for_update()
        ).first()

        if not inv:
            raise HTTPException(status_code=404, detail="Inventory record not found")

        # Count all active, non-expired reservations for this product+location
        now = datetime.utcnow()
        reserved_total = session.exec(
            select(func.coalesce(func.sum(Reservation.quantity), 0)).where(
                Reservation.product_id == body.product_id,
                Reservation.location_id == body.location_id,
                Reservation.status == ReservationStatus.active,
                Reservation.expires_at > now,
            )
        ).first() or 0

        available = inv.quantity - reserved_total
        if available < body.quantity:
            raise HTTPException(
                status_code=409,
                detail=f"Insufficient available stock. Available: {available}, Requested: {body.quantity}",
            )

        expires_at = now + timedelta(minutes=body.ttl_minutes)
        reservation = Reservation(
            tenant_id=current_user.tenant_id,
            product_id=body.product_id,
            location_id=body.location_id,
            quantity=body.quantity,
            reserved_by=current_user.id,
            expires_at=expires_at,
        )
        session.add(reservation)

        log = AuditLog(
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            action="reservation_created",
            entity_type="inventory",
            entity_id=body.product_id,
            details=(
                f"Reserved {body.quantity} units of product_id={body.product_id} "
                f"at location_id={body.location_id} until {expires_at.isoformat()}"
            ),
        )
        session.add(log)
        session.commit()
        session.refresh(reservation)
        return reservation
    finally:
        _redis.delete(lock_key)


@router.get("")
def list_reservations(
    product_id: Optional[int] = None,
    location_id: Optional[int] = None,
    active_only: bool = Query(default=True),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = select(Reservation).where(Reservation.tenant_id == current_user.tenant_id)

    if product_id:
        query = query.where(Reservation.product_id == product_id)
    if location_id:
        query = query.where(Reservation.location_id == location_id)
    if active_only:
        now = datetime.utcnow()
        query = query.where(
            Reservation.status == ReservationStatus.active,
            Reservation.expires_at > now,
        )

    query = query.order_by(Reservation.id.desc())
    reservations = session.exec(query).all()
    return {"items": reservations, "count": len(reservations)}


@router.delete("/{reservation_id}", status_code=200)
def release_reservation(
    reservation_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    reservation = session.exec(
        select(Reservation).where(
            Reservation.id == reservation_id,
            Reservation.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if reservation.status != ReservationStatus.active:
        raise HTTPException(status_code=409, detail="Reservation is already released or expired")

    reservation.status = ReservationStatus.released
    session.add(reservation)

    log = AuditLog(
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        action="reservation_released",
        entity_type="inventory",
        entity_id=reservation.product_id,
        details=f"Released reservation #{reservation_id} for {reservation.quantity} units",
    )
    session.add(log)
    session.commit()
    return {"message": f"Reservation #{reservation_id} released"}


@router.post("/expire-old")
def expire_old_reservations(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Mark expired reservations as expired. Can also be run by a Celery cron."""
    now = datetime.utcnow()
    expired = session.exec(
        select(Reservation).where(
            Reservation.tenant_id == current_user.tenant_id,
            Reservation.status == ReservationStatus.active,
            Reservation.expires_at <= now,
        )
    ).all()

    for r in expired:
        r.status = ReservationStatus.expired
        session.add(r)

    session.commit()
    return {"expired_count": len(expired)}
