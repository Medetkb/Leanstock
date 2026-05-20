from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime


class Location(SQLModel, table=True):
    __tablename__ = "locations"
    # Физическое место хранения товаров (склад, магазин, точка выдачи)

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    # Склад принадлежит конкретной компании
    name: str
    # Название склада, например "Главный склад"
    address: Optional[str] = None
    city: Optional[str] = None
    is_active: bool = Field(default=True)
    # False = склад деактивирован (мягкое удаление)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Inventory(SQLModel, table=True):
    __tablename__ = "inventories"
    # Связывает товар и склад: сколько единиц конкретного товара на конкретном складе

    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.id", index=True)
    location_id: int = Field(foreign_key="locations.id", index=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    # tenant_id дублируется здесь для быстрой фильтрации без JOIN
    quantity: int = Field(default=0)
    # Текущее количество единиц товара на этом складе
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class InventoryTransfer(SQLModel, table=True):
    __tablename__ = "inventory_transfers"
    # Запись о каждом перемещении товара между складами. Только добавление (append-only лог).

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id", index=True)
    product_id: int = Field(foreign_key="products.id")
    from_location_id: int = Field(foreign_key="locations.id")
    # Склад-источник (откуда)
    to_location_id: int = Field(foreign_key="locations.id")
    # Склад-получатель (куда)
    quantity: int
    # Сколько единиц было перемещено
    transferred_by: int = Field(foreign_key="users.id")
    # Кто выполнил трансфер (ID пользователя)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"
    # Журнал всех действий в системе. Только добавление — записи никогда не изменяются и не удаляются.

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = None
    # Кто совершил действие (None если действие автоматическое, например Celery задача)
    tenant_id: Optional[int] = None
    action: str
    # Тип действия: "inventory_transfer", "dead_stock_decay" и т.д.
    entity_type: str
    # Тип объекта над которым совершено действие: "inventory", "product"
    entity_id: Optional[int] = None
    # ID конкретного объекта
    details: Optional[str] = None
    # Текстовое описание что именно произошло
    created_at: datetime = Field(default_factory=datetime.utcnow)
