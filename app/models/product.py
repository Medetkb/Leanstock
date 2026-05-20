from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class Product(SQLModel, table=True):
    __tablename__ = "products"
    # Товар в каталоге компании. Каждый товар принадлежит одному тенанту.

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    # Привязка к компании — товары одной компании не видны другой
    name: str
    # Название товара, например "Widget Pro"
    sku: str = Field(index=True)
    # Stock Keeping Unit — уникальный артикул товара, например "WGT-001"
    category: Optional[str] = None
    # Категория товара — опциональная, используется для фильтрации
    price: float
    # Базовая цена товара
    current_discount: float = Field(default=0.0)
    # Скидка в процентах (0–90%). Автоматически растёт если товар залежался (dead stock decay).
    days_in_inventory: int = Field(default=0)
    # Сколько дней товар находится на складе. Celery каждый день прибавляет +1.
    min_stock: int = Field(default=0)
    # Минимальный уровень запаса — при падении ниже этой отметки отправляется low-stock alert
    is_active: bool = Field(default=True)
    # False = товар деактивирован (мягкое удаление через DELETE /products/{id})
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    # updated_at обновляется при каждом изменении товара
