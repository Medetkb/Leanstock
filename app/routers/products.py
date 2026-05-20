from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.dependencies import get_current_user, require_manager
from app.database import get_session
from app.models.product import Product
from app.models.user import User

router = APIRouter(prefix="/products", tags=["Products"])
# Все маршруты начинаются с /products


class ProductCreate(BaseModel):
    name: str
    sku: str
    category: Optional[str] = None
    price: float
    min_stock: int = 0


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    price: Optional[float] = None
    is_active: Optional[bool] = None
    # Все поля Optional — можно передать только те поля которые нужно изменить (PATCH-стиль через PUT)


@router.get("")
def list_products(
    category: Optional[str] = None,
    cursor: Optional[int] = Query(default=None, description="Cursor for pagination (last product id)"),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = select(Product).where(
        Product.tenant_id == current_user.tenant_id,
        # Мультитенантность: пользователь видит только товары своей компании
        Product.is_active == True,
    )
    if category:
        query = query.where(Product.category == category)
    if cursor:
        query = query.where(Product.id > cursor)
        # Cursor pagination: берём только записи с ID больше последнего полученного
        # Эффективнее чем OFFSET — не замедляется на больших таблицах

    query = query.order_by(Product.id).limit(limit)
    products = session.exec(query).all()

    return {
        "items": products,
        "next_cursor": products[-1].id if len(products) == limit else None,
        # Если вернулось ровно limit записей — есть ещё страницы. Иначе это последняя страница.
        "limit": limit,
    }


@router.post("", status_code=201)
def create_product(
    body: ProductCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
    # Только manager и admin могут создавать товары
):
    if body.price <= 0:
        raise HTTPException(status_code=422, detail="Price must be greater than 0")

    existing = session.exec(
        select(Product).where(
            Product.sku == body.sku,
            Product.tenant_id == current_user.tenant_id,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="SKU already exists in your catalog")
        # SKU уникален в рамках одной компании

    product = Product(
        tenant_id=current_user.tenant_id,
        name=body.name,
        sku=body.sku,
        category=body.category,
        price=body.price,
        min_stock=body.min_stock,
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    # refresh() подгружает обратно из БД чтобы получить id и created_at
    return product


@router.get("/{product_id}")
def get_product(
    product_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    product = session.exec(
        select(Product).where(
            Product.id == product_id,
            Product.tenant_id == current_user.tenant_id,
            # Проверяем tenant_id — нельзя получить товар чужой компании
        )
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.put("/{product_id}")
def update_product(
    product_id: int,
    body: ProductUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
):
    product = session.exec(
        select(Product).where(
            Product.id == product_id,
            Product.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    if body.name is not None:
        product.name = body.name
    if body.category is not None:
        product.category = body.category
    if body.price is not None:
        if body.price <= 0:
            raise HTTPException(status_code=422, detail="Price must be greater than 0")
        product.price = body.price
    if body.is_active is not None:
        product.is_active = body.is_active
    # Обновляем только переданные поля — None-поля не трогаем

    product.updated_at = datetime.utcnow()
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@router.delete("/{product_id}")
def delete_product(
    product_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_manager),
):
    product = session.exec(
        select(Product).where(
            Product.id == product_id,
            Product.tenant_id == current_user.tenant_id,
        )
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    product.is_active = False
    # Мягкое удаление: не удаляем из БД, а ставим флаг is_active=False
    # История трансферов и инвентаря остаётся целой
    product.updated_at = datetime.utcnow()
    session.add(product)
    session.commit()
    return {"message": "Product deactivated"}
