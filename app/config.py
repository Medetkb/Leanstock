from typing import Optional
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Настройки базы данных ---
    DATABASE_URL: str

    # --- JWT токены ---
    SECRET_KEY: str = "dev-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # DeployRocks provides DATABASE_URL as postgres:// — SQLAlchemy needs postgresql://
    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_db_url(cls, v):
        if isinstance(v, str) and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql://", 1)
        return v

    # DeployRocks auto-generates base64 secrets for vars with "TOKEN" in name.
    # These validators fall back to defaults if the injected value isn't an integer.
    @field_validator("ACCESS_TOKEN_EXPIRE_MINUTES", mode="before")
    @classmethod
    def parse_access_expire(cls, v):
        try:
            return int(v)
        except (ValueError, TypeError):
            return 30

    @field_validator("REFRESH_TOKEN_EXPIRE_DAYS", mode="before")
    @classmethod
    def parse_refresh_expire(cls, v):
        try:
            return int(v)
        except (ValueError, TypeError):
            return 7

    # --- Redis ---
    REDIS_URL: str = "redis://redis:6379/0"

    # --- Email (SMTP) ---
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    @field_validator("SMTP_PORT", mode="before")
    @classmethod
    def parse_smtp_port(cls, v):
        try:
            return int(v)
        except (ValueError, TypeError):
            return 587

    # --- Базовый URL приложения ---
    APP_URL: str = "http://localhost:8000"

    # --- CORS ---
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://localhost:8000"

    # --- Окружение ---
    ENVIRONMENT: str = "development"

    class Config:
        env_file = ".env"


settings = Settings()
# Единственный экземпляр настроек — импортируется во всех модулях как `from app.config import settings`
