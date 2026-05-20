from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Настройки базы данных ---
    DATABASE_URL: str
    # Строка подключения к PostgreSQL, например: postgresql://user:pass@db:5432/leanstock

    # --- JWT токены ---
    SECRET_KEY: str
    # Секретный ключ для подписи JWT токенов — должен быть длинным и случайным
    ALGORITHM: str = "HS256"
    # Алгоритм шифрования токена (HS256 = HMAC + SHA256)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    # Access token живёт 30 минут, потом нужно обновлять через refresh
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # Refresh token живёт 7 дней — используется для получения нового access token

    # --- Redis ---
    REDIS_URL: str = "redis://redis:6379/0"
    # Адрес Redis — используется как брокер задач Celery и для rate limiting

    # --- Email (SMTP) ---
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str
    SMTP_PASSWORD: str
    SMTP_FROM: str
    # Данные для отправки писем через Gmail SMTP

    # --- Базовый URL приложения ---
    APP_URL: str = "http://localhost:8000"
    # Используется в ссылках внутри писем (верификация, сброс пароля)

    # --- CORS ---
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://localhost:8000"
    # Через запятую: список разрешённых origins для CORS. В продакшне добавить домен деплоя.

    # --- Окружение ---
    ENVIRONMENT: str = "development"

    class Config:
        env_file = ".env"
        # Все эти переменные читаются из файла .env в корне проекта


settings = Settings()
# Единственный экземпляр настроек — импортируется во всех модулях как `from app.config import settings`
