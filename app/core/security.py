import bcrypt
import secrets
from datetime import datetime, timedelta
from jose import JWTError, jwt
from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    # Хэшируем пароль с солью через bcrypt. Никогда не храним пароль в открытом виде.


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())
    # Проверяем введённый пароль против хэша из БД. bcrypt сам извлекает соль из хэша.


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    # Создаём JWT access token. Внутри зашиты: user_id (sub), роль, tenant_id, время истечения.


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    # Декодируем JWT и проверяем подпись. Если токен изменён или истёк — выбросит JWTError.


def generate_token() -> str:
    """Generate a secure random token (for email verification / password reset)."""
    return secrets.token_urlsafe(32)
    # Генерирует случайный URL-безопасный токен (43 символа). Используется в письмах.


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)
    # Генерирует более длинный токен для refresh — хранится в БД и сравнивается при обновлении access.
