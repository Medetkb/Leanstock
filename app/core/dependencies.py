from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import Session
from jose import JWTError
from app.database import get_session
from app.models.user import User, UserRole
from app.core.security import decode_access_token

security = HTTPBearer()
# HTTPBearer автоматически достаёт токен из заголовка: Authorization: Bearer <token>


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: Session = Depends(get_session),
) -> User:
    # Эта функция используется как Depends() в каждом защищённом эндпоинте
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        # "sub" (subject) — стандартное поле JWT, содержит ID пользователя
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = session.get(User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified. Check your inbox.")
    return user
    # Возвращает объект User — доступен в эндпоинте как current_user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
    # Дополнительная проверка поверх get_current_user — только для роли admin


def require_manager(user: User = Depends(get_current_user)) -> User:
    if user.role not in [UserRole.admin, UserRole.manager]:
        raise HTTPException(status_code=403, detail="Manager or admin access required")
    return user
    # Разрешает доступ для admin и manager. Staff не может создавать/изменять данные.
