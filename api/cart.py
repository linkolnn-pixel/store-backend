import os
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core.config import settings
from db.postgres import get_db_session
from models.product_meta import ProductMeta
from schemas.cart import CartItemSchema, CartUpdateSchema, CartRemoveSchema  # <-- Добавили импорты здесь
from db.redis import get_cart, save_cart

router = APIRouter()

@router.post("/cart/add", summary="Добавить товар или услугу в корзину")
async def add_item_to_cart(item: CartItemSchema, session_id: str | None = None):
    if not session_id:
        session_id = str(uuid.uuid4())
        cart = {"session_id": session_id, "items": [], "total": 0.0}
    else:
        cart = await get_cart(session_id)
        if not cart:
            cart = {"session_id": session_id, "items": [], "total": 0.0}

    existing_item = next((i for i in cart["items"] if i["product_id"] == item.product_id), None)

    if existing_item:
        existing_item["quantity"] += item.quantity
    else:
        cart["items"].append(item.model_dump())

    cart["total"] = sum(i["price"] * i["quantity"] for i in cart["items"])
    await save_cart(session_id, cart)

    return {"session_id": session_id, "cart": cart}


@router.get("/cart/{session_id}", summary="Получить состав корзины")
async def view_cart(session_id: str, db: AsyncSession = Depends(get_db_session)):
    cart = await get_cart(session_id)
    if not cart:
        raise HTTPException(status_code=404, detail="Корзина не найдена или истекла")
    if not cart.get("items"):
        return cart

    # Собираем ID всех товаров в корзине
    product_ids = [int(item["product_id"]) for item in cart["items"]]

    # 3. Идем в PostgreSQL за картинками и маркетинговыми названиями
    stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id.in_(product_ids))
    result = await db.execute(stmt)
    meta_dict = {meta.warehouse_product_id: meta for meta in result.scalars().all()}

    # 4. Идем на склад Django за оригинальными названиями (fallback)
    warehouse_products = {}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{settings.WAREHOUSE_URL}/api/products/")
            if response.status_code == 200:
                data = response.json()
                products_list = data.get("results", data) if isinstance(data, dict) else data
                # Делаем словарь {id: "Название"}
                warehouse_products = {p["id"]: p["name"] for p in products_list}
    except Exception as e:
        print(f"Не удалось получить названия со склада: {e}")

    # 5. Обогащаем товары в корзине данными
    for item in cart["items"]:
        pid = int(item["product_id"])
        meta = meta_dict.get(pid)

        # Оригинальное название со склада
        original_name = warehouse_products.get(pid, f"Товар #{pid}")

        # Если есть красивое маркетинговое имя в БД FastAPI - берем его, иначе складское
        item["name"] = meta.marketing_name if meta and meta.marketing_name else original_name

        # Добавляем первую картинку из массива (если есть)
        item["image"] = meta.images[0] if meta and meta.images else ""

    return cart


@router.post("/cart/update", summary="Обновить количество товара")
async def update_item_quantity(data: CartUpdateSchema):
    cart = await get_cart(data.session_id)
    if not cart:
        raise HTTPException(status_code=404, detail="Корзина не найдена")

    for item in cart.get("items", []):
        if str(item["product_id"]) == str(data.product_id):
            item["quantity"] = data.quantity
            break

    cart["total"] = sum(i["price"] * i["quantity"] for i in cart["items"])
    await save_cart(data.session_id, cart)

    return {"message": "Количество обновлено", "cart": cart}


@router.post("/cart/remove", summary="Удалить товар из корзины")
async def remove_item_from_cart(data: CartRemoveSchema):
    cart = await get_cart(data.session_id)
    if not cart:
        raise HTTPException(status_code=404, detail="Корзина не найдена")

    cart["items"] = [item for item in cart.get("items", []) if str(item["product_id"]) != str(data.product_id)]
    cart["total"] = sum(i["price"] * i["quantity"] for i in cart["items"])

    await save_cart(data.session_id, cart)

    return {"message": "Товар удален", "cart": cart}