from sqlmodel import create_engine, Session, SQLModel
from app.config import settings

engine = create_engine(settings.DATABASE_URL, echo=False)
# Создаём движок БД по URL из конфига. echo=False — не логировать SQL запросы в консоль


def create_db_and_tables():
    # Импортируем все модели чтобы SQLModel узнал о них до вызова create_all
    from app.models import user, product, inventory, supplier, reservation  # noqa: F401
    # noqa — подавляем предупреждение линтера "импорт не используется" (он нужен для регистрации моделей)
    SQLModel.metadata.create_all(engine)
    # Создаёт все таблицы в БД если их нет. Вызывается при старте приложения.


def get_session():
    with Session(engine) as session:
        yield session
    # Генератор сессии для FastAPI Depends() — открывает сессию на время запроса, автоматически закрывает
