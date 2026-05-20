from celery import Celery
from app.config import settings

celery_app = Celery(
    "leanstock",
    broker=settings.REDIS_URL,
    # broker — Redis принимает задачи от FastAPI и кладёт их в очередь
    backend=settings.REDIS_URL,
    # backend — Redis хранит результаты выполненных задач (job_id → результат)
    include=["app.workers.tasks"],
    # Указываем где искать задачи (@celery_app.task)
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Сериализация задач в JSON — читаемо и безопасно
    timezone="UTC",
    beat_schedule={
        # Celery Beat — планировщик задач (как cron, но внутри Python)
        "increment-days-daily": {
            "task": "app.workers.tasks.increment_days_in_inventory",
            "schedule": 24 * 3600,
            # Каждые 24 часа: +1 день к days_in_inventory всех активных товаров
        },
        "dead-stock-decay": {
            "task": "app.workers.tasks.dead_stock_decay",
            "schedule": 72 * 3600,
            # Каждые 72 часа: применяет 10% скидку к залежавшимся товарам (>30 дней)
        },
        "check-low-stock-daily": {
            "task": "app.workers.tasks.check_low_stock",
            "schedule": 24 * 3600,
            # Каждые 24 часа: оповещает менеджеров о товарах ниже min_stock
        },
        "expire-reservations": {
            "task": "app.workers.tasks.expire_reservations",
            "schedule": 5 * 60,
            # Каждые 5 минут: помечает истёкшие бронирования как expired
        },
    },
)
