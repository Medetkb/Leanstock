import redis as redis_lib
from fastapi import HTTPException, Request
from app.config import settings

_redis = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
# Подключение к Redis. decode_responses=True — возвращает строки вместо байтов.


def check_rate_limit(request: Request, prefix: str, max_attempts: int = 5, window: int = 60):
    """
    Simple Redis-based token bucket rate limiter.
    Raises 429 if the IP exceeds max_attempts within window seconds.
    """
    # Защита от брутфорса: считает количество запросов с одного IP за период
    try:
        ip = request.client.host
        # Получаем IP адрес клиента
        key = f"rate_limit:{prefix}:{ip}"
        # Ключ в Redis вида: rate_limit:login:127.0.0.1
        count = _redis.get(key)
        if count and int(count) >= max_attempts:
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Wait {window} seconds and try again."
            )
            # 429 Too Many Requests — стандартный статус для rate limiting
        pipe = _redis.pipeline()
        # Pipeline — отправляет несколько команд Redis за один раз (атомарно)
        pipe.incr(key)
        # Увеличиваем счётчик на 1
        pipe.expire(key, window)
        # Устанавливаем TTL (время жизни ключа) — через window секунд счётчик сбросится
        pipe.execute()
    except HTTPException:
        raise
    except Exception:
        # If Redis is unreachable, allow the request (fail open)
        pass
        # Если Redis недоступен — пропускаем запрос. Лучше работать без лимита, чем упасть.
