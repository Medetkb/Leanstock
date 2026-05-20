from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum


class UserRole(str, Enum):
    admin = "admin"
    manager = "manager"
    staff = "staff"
# Роли пользователей. admin > manager > staff по правам доступа.


class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"
    # Компания (организация). Вся система мультитенантная — каждая компания видит только свои данные.

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    # Название компании — уникальное
    slug: str = Field(unique=True, index=True)
    # URL-friendly версия названия, например "my-company". Используется для идентификации.
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    # Храним только хэш пароля, никогда не сам пароль
    role: UserRole = Field(default=UserRole.staff)
    # По умолчанию новый пользователь — staff (минимальные права)
    tenant_id: Optional[int] = Field(default=None, foreign_key="tenants.id", index=True)
    # Привязка к компании. Все запросы фильтруются по этому полю.
    is_verified: bool = Field(default=False)
    # False пока пользователь не перешёл по ссылке в письме
    is_active: bool = Field(default=True)
    # False = деактивирован администратором (мягкое удаление)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"
    # Хранилище refresh токенов в БД. Позволяет отзывать токены при logout.

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    token: str = Field(unique=True, index=True)
    # Сам токен — случайная строка из 64 символов
    expires_at: datetime
    is_revoked: bool = Field(default=False)
    # True после logout — токен больше нельзя использовать
    created_at: datetime = Field(default_factory=datetime.utcnow)


class EmailVerification(SQLModel, table=True):
    __tablename__ = "email_verifications"
    # Токены для подтверждения email. Ссылка в письме содержит этот токен.

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    token: str = Field(unique=True, index=True)
    expires_at: datetime
    # Токен действует 24 часа (для регистрации) или 48 часов (для invite от admin)
    used: bool = Field(default=False)
    # True после использования — повторно применить нельзя
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PasswordResetToken(SQLModel, table=True):
    __tablename__ = "password_reset_tokens"
    # Токены для сброса пароля. Действуют 1 час, одноразовые.

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    token: str = Field(unique=True, index=True)
    expires_at: datetime
    used: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
