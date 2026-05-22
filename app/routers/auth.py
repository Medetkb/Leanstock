from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from app.config import settings
from app.core.dependencies import get_current_user
from app.core.rate_limit import check_rate_limit
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    generate_token,
    hash_password,
    verify_password,
)
from app.database import get_session
from app.models.user import (
    EmailVerification,
    PasswordResetToken,
    RefreshToken,
    Tenant,
    User,
    UserRole,
)
from app.services.email_service import send_password_reset_email, send_verification_email

router = APIRouter(prefix="/auth", tags=["Auth"])
# Все маршруты этого файла начинаются с /auth


# ─── Схемы запросов (Pydantic модели для валидации входящих данных) ──────────

class RegisterRequest(BaseModel):
    email: EmailStr
    # EmailStr — автоматически валидирует формат email
    username: str
    password: str
    tenant_name: str
    # Название компании — если такой нет, создастся новый Tenant


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    # Токен из ссылки в письме
    new_password: str


# ─── Эндпоинты ──────────────────────────────────────────────────────────────

@router.post("/register", status_code=201)
def register(
    request: Request,
    body: RegisterRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    check_rate_limit(request, "register")
    # Не более 5 регистраций с одного IP за 60 секунд

    if len(body.password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    if session.exec(select(User).where(User.email == body.email)).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    if session.exec(select(User).where(User.username == body.username)).first():
        raise HTTPException(status_code=409, detail="Username already taken")

    # Ищем существующую компанию по slug (регистронезависимо) или создаём новую
    slug = body.tenant_name.lower().replace(" ", "-")
    tenant = session.exec(
        select(Tenant).where(Tenant.slug == slug)
    ).first()
    if not tenant:
        # Если slug занят другим именем — добавляем суффикс
        existing_slug = session.exec(
            select(Tenant).where(Tenant.slug == slug)
        ).first()
        if existing_slug:
            import random
            slug = f"{slug}-{random.randint(100, 999)}"
        tenant = Tenant(name=body.tenant_name, slug=slug)
        session.add(tenant)
        session.flush()

    # Первый пользователь в компании автоматически становится admin
    existing_in_tenant = session.exec(
        select(User).where(User.tenant_id == tenant.id)
    ).first()
    role = UserRole.admin if not existing_in_tenant else UserRole.staff

    user = User(
        email=body.email,
        username=body.username,
        password_hash=hash_password(body.password),
        tenant_id=tenant.id,
        role=role,
    )
    session.add(user)
    session.flush()

    # Создаём токен верификации email — действует 24 часа
    token = generate_token()
    verification = EmailVerification(
        user_id=user.id,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=24),
    )
    session.add(verification)
    session.commit()

    background_tasks.add_task(send_verification_email, body.email, token)
    # BackgroundTasks — письмо отправится после ответа клиенту, не блокируя запрос

    return {"message": "Registered! Check your email to verify your account."}


@router.post("/login")
def login(
    request: Request,
    body: LoginRequest,
    session: Session = Depends(get_session),
):
    check_rate_limit(request, "login")
    # Не более 5 попыток логина с одного IP за 60 секунд — защита от брутфорса

    user = session.exec(select(User).where(User.email == body.email)).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
        # Намеренно одинаковая ошибка — не раскрываем какое поле неправильное

    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Please verify your email first")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Your account has been deactivated")

    access_token = create_access_token({
        "sub": str(user.id),
        "role": user.role,
        "tenant_id": user.tenant_id,
    })
    # В payload токена зашиваем: ID юзера, роль, ID компании

    refresh_token_str = generate_refresh_token()
    refresh_token = RefreshToken(
        user_id=user.id,
        token=refresh_token_str,
        expires_at=datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    session.add(refresh_token)
    session.commit()
    # Сохраняем refresh token в БД чтобы можно было отозвать при logout

    return {
        "access_token": access_token,
        "refresh_token": refresh_token_str,
        "token_type": "bearer",
    }


@router.post("/refresh")
def refresh(body: RefreshRequest, session: Session = Depends(get_session)):
    rt = session.exec(
        select(RefreshToken).where(
            RefreshToken.token == body.refresh_token,
            RefreshToken.is_revoked == False,
        )
    ).first()

    if not rt or rt.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
        # Токен либо не существует, либо отозван, либо истёк

    user = session.get(User, rt.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")

    new_access_token = create_access_token({
        "sub": str(user.id),
        "role": user.role,
        "tenant_id": user.tenant_id,
    })
    # Выдаём новый access token. Refresh token при этом не меняется.

    return {"access_token": new_access_token, "token_type": "bearer"}


@router.post("/logout")
def logout(body: RefreshRequest, session: Session = Depends(get_session)):
    rt = session.exec(
        select(RefreshToken).where(RefreshToken.token == body.refresh_token)
    ).first()

    if rt:
        rt.is_revoked = True
        session.add(rt)
        session.commit()
    # Отзываем refresh token. Даже если токен не найден — возвращаем успех (идемпотентность).

    return {"message": "Logged out successfully"}


@router.get("/verify-email/{token}")
def verify_email(token: str, session: Session = Depends(get_session)):
    ev = session.exec(
        select(EmailVerification).where(
            EmailVerification.token == token,
            EmailVerification.used == False,
        )
    ).first()

    if not ev:
        raise HTTPException(status_code=404, detail="Invalid verification token")

    if ev.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Verification link expired. Please register again.")

    user = session.get(User, ev.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_verified = True
    ev.used = True
    # Помечаем токен использованным — повторное использование невозможно
    session.add(user)
    session.add(ev)
    session.commit()

    return {"message": "Email verified! You can now log in."}


@router.post("/forgot-password")
def forgot_password(
    body: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
):
    user = session.exec(select(User).where(User.email == body.email)).first()

    if user:
        token = generate_token()
        reset = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=1),
            # Токен сброса пароля действует 1 час
        )
        session.add(reset)
        session.commit()
        background_tasks.add_task(send_password_reset_email, body.email, token)

    return {"message": "If that email exists, a reset link has been sent."}
    # Одинаковый ответ независимо от того, существует email или нет — не раскрываем зарегистрированные адреса


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, session: Session = Depends(get_session)):
    reset = session.exec(
        select(PasswordResetToken).where(
            PasswordResetToken.token == body.token,
            PasswordResetToken.used == False,
        )
    ).first()

    if not reset or reset.expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters")

    user = session.get(User, reset.user_id)
    user.password_hash = hash_password(body.new_password)
    # Заменяем хэш пароля на новый
    reset.used = True
    # Токен одноразовый — после использования нельзя применить снова
    session.add(user)
    session.add(reset)
    session.commit()

    return {"message": "Password reset successfully. You can now log in."}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "role": current_user.role,
        "tenant_id": current_user.tenant_id,
        "is_verified": current_user.is_verified,
    }
    # Возвращает данные текущего авторизованного пользователя по токену
