from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from app.core.dependencies import require_admin
from app.core.security import generate_token, hash_password
from app.database import get_session
from app.models.inventory import AuditLog
from app.models.user import EmailVerification, User, UserRole
from app.services.email_service import send_invite_email
from app.workers.tasks import dead_stock_decay, increment_days_in_inventory

router = APIRouter(prefix="/admin", tags=["Admin"])
# Все маршруты начинаются с /admin. Каждый эндпоинт требует роль admin.


class CreateUserRequest(BaseModel):
    email: EmailStr
    username: str
    password: str
    role: UserRole = UserRole.staff
    # По умолчанию создаётся staff — минимальные права


class RoleUpdateRequest(BaseModel):
    role: UserRole


# ─── Управление пользователями ───────────────────────────────────────────────

@router.get("/users")
def list_users(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
    # require_admin автоматически проверяет что пользователь — admin
):
    users = session.exec(
        select(User).where(User.tenant_id == current_user.tenant_id)
        # Только пользователи своей компании
    ).all()
    return [
        {
            "id": u.id,
            "email": u.email,
            "username": u.username,
            "role": u.role,
            "is_verified": u.is_verified,
            "is_active": u.is_active,
        }
        for u in users
    ]
    # Возвращаем только нужные поля — пароль не передаём


@router.post("/users", status_code=201)
def create_user(
    body: CreateUserRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    """Admin creates a new user inside the same company. Sends an invite email."""
    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    if session.exec(select(User).where(User.email == body.email)).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    if session.exec(select(User).where(User.username == body.username)).first():
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(
        email=body.email,
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        tenant_id=current_user.tenant_id,
        # Новый пользователь автоматически добавляется в ту же компанию что и admin
        is_verified=False,
        # Требует подтверждения email через ссылку в invite письме
    )
    session.add(user)
    session.flush()

    token = generate_token()
    verification = EmailVerification(
        user_id=user.id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=48),
        # Invite токен действует 48 часов (больше чем при самостоятельной регистрации)
    )
    session.add(verification)
    session.commit()

    background_tasks.add_task(
        send_invite_email,
        body.email,
        body.username,
        body.role,
        token,
    )
    # Отправляем invite письмо с кнопкой подтверждения и данными аккаунта

    return {
        "message": f"User {body.email} created. Invite email sent.",
        "user_id": user.id,
        "role": body.role,
    }


@router.put("/users/{user_id}/role")
def update_user_role(
    user_id: int,
    body: RoleUpdateRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    user = session.exec(
        select(User).where(
            User.id == user_id,
            User.tenant_id == current_user.tenant_id,
            # Нельзя изменить роль пользователя другой компании
        )
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.role = body.role
    session.add(user)
    session.commit()
    return {"message": f"Role updated to {body.role}", "user_id": user_id}


@router.delete("/users/{user_id}")
def deactivate_user(
    user_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot deactivate yourself")
        # Защита: admin не может заблокировать сам себя и потерять доступ

    user = session.exec(
        select(User).where(
            User.id == user_id,
            User.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    # Мягкое удаление — пользователь остаётся в БД, просто не может войти
    session.add(user)
    session.commit()
    return {"message": "User deactivated"}


# ─── Логи и фоновые задачи ───────────────────────────────────────────────────

@router.get("/audit-logs")
def get_audit_logs(
    session: Session = Depends(get_session),
    current_user: User = Depends(require_admin),
):
    logs = session.exec(
        select(AuditLog)
        .where(AuditLog.tenant_id == current_user.tenant_id)
        .order_by(AuditLog.created_at.desc())
        # Сначала новые записи
        .limit(200)
        # Ограничение 200 записей — для больших объёмов нужна пагинация
    ).all()
    return logs


@router.post("/trigger-decay")
def trigger_dead_stock_decay(
    decay_percent: float = 10.0,
    current_user: User = Depends(require_admin),
):
    result = dead_stock_decay.delay(decay_percent)
    # .delay() отправляет задачу в очередь Celery — выполняется асинхронно воркером
    # Задача применяет скидку к товарам с days_in_inventory > 30
    return {"message": "Dead stock decay job queued", "job_id": result.id}


@router.post("/trigger-increment-days")
def trigger_increment_days(current_user: User = Depends(require_admin)):
    result = increment_days_in_inventory.delay()
    # .delay() — запускает задачу в Celery. В production запускается автоматически каждые 24 часа.
    return {"message": "Increment days job queued", "job_id": result.id}
