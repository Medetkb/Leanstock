from datetime import datetime
from sqlmodel import Session, select, func
from app.workers.celery_app import celery_app
from app.database import engine
from app.models.product import Product
from app.models.inventory import AuditLog, Inventory
from app.models.user import User, UserRole
from app.models.reservation import Reservation, ReservationStatus
from app.services.email_service import _send, send_dead_stock_alert_email, send_low_stock_alert_email


@celery_app.task(name="app.workers.tasks.send_email_task")
def send_email_task(to_email: str, subject: str, html: str):
    """Generic async email task — keeps API endpoints fast."""
    _send(to_email, subject, html)
    # Универсальная задача отправки email. Выполняется в Celery воркере, не блокирует API.


@celery_app.task(name="app.workers.tasks.increment_days_in_inventory")
def increment_days_in_inventory():
    """Run daily: +1 day for every active product."""
    # Запускается автоматически каждые 24 часа через Celery Beat
    with Session(engine) as session:
        products = session.exec(
            select(Product).where(Product.is_active == True)
        ).all()

        for p in products:
            p.days_in_inventory += 1
            p.updated_at = datetime.utcnow()
            session.add(p)
            # Прибавляем 1 день каждому активному товару

        session.commit()
    return f"Incremented days_in_inventory for {len(products)} products"
    # Возвращаемое значение сохраняется в Redis как результат задачи


@celery_app.task(name="app.workers.tasks.dead_stock_decay")
def dead_stock_decay(decay_percent: float = 10.0):
    """
    Run every 72 hours.
    Products sitting > 30 days get +decay_percent% discount (capped at 90%).
    """
    # Применяет штрафную скидку к залежавшимся товарам
    with Session(engine) as session:
        products = session.exec(
            select(Product).where(
                Product.days_in_inventory > 30,
                # Только товары которые лежат больше 30 дней
                Product.is_active == True,
            )
        ).all()

        affected = 0
        for p in products:
            new_discount = min(p.current_discount + decay_percent, 90.0)
            # Скидка не может превысить 90% — min() ограничивает максимум
            p.current_discount = new_discount
            p.updated_at = datetime.utcnow()
            session.add(p)

            log = AuditLog(
                tenant_id=p.tenant_id,
                action="dead_stock_decay",
                entity_type="product",
                entity_id=p.id,
                details=f"Auto discount set to {new_discount}% (days={p.days_in_inventory})",
            )
            session.add(log)
            # Каждое применение скидки фиксируется в audit log
            affected += 1

        session.commit()

        # Send email alert to tenant managers for each affected product
        with Session(engine) as alert_session:
            managers = alert_session.exec(
                select(User).where(
                    User.tenant_id == p.tenant_id,
                    User.role.in_([UserRole.admin, UserRole.manager]),
                    User.is_active == True,
                    User.is_verified == True,
                )
            ).all()
            for manager in managers:
                try:
                    send_dead_stock_alert_email(manager.email, p.name, p.days_in_inventory, new_discount)
                except Exception:
                    pass

    return f"Dead stock decay applied to {affected} products"


@celery_app.task(name="app.workers.tasks.check_low_stock")
def check_low_stock():
    """Run daily: send low-stock alerts to managers for products below min_stock."""
    with Session(engine) as session:
        inventories = session.exec(
            select(Inventory).where(Inventory.quantity >= 0)
        ).all()

        alerted = 0
        for inv in inventories:
            product = session.get(Product, inv.product_id)
            if not product or not product.is_active or product.min_stock <= 0:
                continue
            if inv.quantity <= product.min_stock:
                managers = session.exec(
                    select(User).where(
                        User.tenant_id == product.tenant_id,
                        User.role.in_([UserRole.admin, UserRole.manager]),
                        User.is_active == True,
                        User.is_verified == True,
                    )
                ).all()
                for manager in managers:
                    try:
                        send_low_stock_alert_email(
                            manager.email,
                            product.name,
                            product.sku,
                            inv.quantity,
                            product.min_stock,
                        )
                        alerted += 1
                    except Exception:
                        pass

    return f"Low stock alerts sent for {alerted} manager/product pairs"


@celery_app.task(name="app.workers.tasks.expire_reservations")
def expire_reservations():
    """Run every 5 minutes: mark expired reservations."""
    with Session(engine) as session:
        now = datetime.utcnow()
        expired = session.exec(
            select(Reservation).where(
                Reservation.status == ReservationStatus.active,
                Reservation.expires_at <= now,
            )
        ).all()
        for r in expired:
            r.status = ReservationStatus.expired
            session.add(r)
        session.commit()
    return f"Expired {len(expired)} reservations"
