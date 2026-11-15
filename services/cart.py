import uuid
import httpx
from decimal import Decimal

from core.exceptions import ProductNotFoundError, CartNotFoundError
from fastapi import HTTPException, status
from services.promo_service import PromoValidationResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core.config import settings
from db.redis import get_cart, save_cart, redis_client
from models.product_meta import ProductMeta
from schemas.cart import CartItemAddSchema


headers = {"X-Service-Token": settings.SERVICE_API_KEY}

async def fetch_price_for_product(product_id: int) -> Decimal | None:
    try:
        async with httpx.AsyncClient(headers=headers, timeout=3.0) as client:
            response = await client.get(f"{settings.WAREHOUSE_URL}/api/products/{product_id}/")
            response.raise_for_status()
            if response.status_code == 200:
                data = response.json()
                price_val = data.get("sale_price")
                if price_val is not None:
                    return Decimal(str(price_val))
                else:
                    print(f"Ошибка: Склад вернул товар {product_id}, но в JSON нет поля 'sale_price'")
            else:
                print(f"Склад вернул статус {response.status_code} для товара {product_id}")
    except Exception as e:
        print(f"Ошибка HTTP при получении цены для товара {product_id}: {e}")
    return None

async def fetch_warehouse_names(product_ids: list[int]) -> dict[int, str]:
    if not product_ids:
        return {}

    try:
        async with httpx.AsyncClient(headers=headers, timeout=3.0) as client:
            ids_query = ",".join(map(str, product_ids))
            response = await client.get(f"{settings.WAREHOUSE_URL}/api/products/", params={"ids": ids_query})

            if response.status_code == 200:
                data = response.json()
                products_list = data.get("results", data) if isinstance(data, dict) else data
                return {p["id"]: p["name"] for p in products_list}
    except Exception as e:
        print(f"Не удалось получить названия со склада: {e}")
    return {}

async def add_product_to_cart(session_id: str | None, item: CartItemAddSchema, phone: str | None = None) -> tuple[str, dict]:
    actual_price = await fetch_price_for_product(item.product_id)
    if actual_price is None:
        raise ProductNotFoundError(f"Товар {item.product_id} недоступен или не существует")

    session_id = session_id or str(uuid.uuid4())
    cart = await get_cart(session_id) or {"session_id": session_id, "items": [], "total": Decimal("0.0")}

    # === ПРИВЯЗКА ТЕЛЕФОНА ===
    if phone:
        cart["customer_phone"] = phone

    existing_item = next((i for i in cart["items"] if i["product_id"] == item.product_id), None)
    if existing_item:
        existing_item["quantity"] += item.quantity
        existing_item["price"] = actual_price
    else:
        cart["items"].append({
            "product_id": item.product_id,
            "quantity": item.quantity,
            "price": actual_price
        })

    cart["total"] = sum(Decimal(str(i["price"])) * i["quantity"] for i in cart["items"])
    await save_cart(session_id, cart)
    return session_id, cart


async def update_item_quantity(session_id: str, product_id: int, quantity: int) -> dict:
    cart = await get_cart(session_id)
    if not cart:
        raise CartNotFoundError("Корзина не найдена")

    for item in cart.get("items", []):
        if str(item["product_id"]) == str(product_id):
            item["quantity"] = quantity
            break

    cart["total"] = sum(Decimal(str(i["price"])) * i["quantity"] for i in cart["items"])
    await save_cart(session_id, cart)
    return cart


async def remove_item_from_cart(session_id: str, product_id: int) -> dict:
    cart = await get_cart(session_id)
    if not cart:
        raise CartNotFoundError("Корзина не найдена")

    cart["items"] = [item for item in cart.get("items", []) if str(item["product_id"]) != str(product_id)]
    cart["total"] = sum(Decimal(str(i["price"])) * i["quantity"] for i in cart["items"])

    await save_cart(session_id, cart)
    return cart


async def apply_promo_to_cart(session_id: str, promo_data: PromoValidationResult):
    """Сохраняет данные промокода в Redis, привязывая к корзине."""
    promo_key = f"cart:{session_id}:promo"
    await redis_client.setex(
        promo_key,
        86400,
        promo_data.model_dump_json()
    )


async def get_promo_from_cart(session_id: str) -> PromoValidationResult | None:
    """Достает примененный промокод из Redis."""
    promo_key = f"cart:{session_id}:promo"
    data_str = await redis_client.get(promo_key)

    if data_str:
        return PromoValidationResult.model_validate_json(data_str)
    return None


async def remove_promo_from_cart(session_id: str):
    """Удаляет промокод из корзины."""
    promo_key = f"cart:{session_id}:promo"
    await redis_client.delete(promo_key)


def calculate_discount_amount(cart_total: Decimal, promo: PromoValidationResult) -> Decimal:
    """Математика расчета скидки"""
    if cart_total <= 0:
        return Decimal("0.00")

    discount_value = Decimal(str(promo.discount_value))
    min_order_amount = Decimal(str(promo.min_order_amount))

    if cart_total < min_order_amount:
        return Decimal("0.00")

    if promo.discount_type == "PERCENT":
        discount = cart_total * (discount_value / Decimal("100"))
    elif promo.discount_type == "FIXED":
        discount = discount_value
    else:
        return Decimal("0.00")

    final_discount = min(discount, cart_total)
    return round(final_discount, 2)


async def get_cart_with_meta(session_id: str, db: AsyncSession, phone: str | None = None) -> dict:
    cart = await get_cart(session_id)
    if not cart:
        raise CartNotFoundError("Корзина не найдена или истекла")

    # === СИНХРОНИЗАЦИЯ КОРЗИНЫ ПРИ ЛОГИНЕ ===
    if phone and cart.get("customer_phone") != phone:
        cart["customer_phone"] = phone
        await save_cart(session_id, cart)

    if not cart.get("items"):
        return cart

    product_ids = [int(item["product_id"]) for item in cart["items"]]

    stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id.in_(product_ids))
    result = await db.execute(stmt)
    meta_dict = {meta.warehouse_product_id: meta for meta in result.scalars().all()}

    warehouse_products = await fetch_warehouse_names(product_ids)

    for item in cart["items"]:
        pid = int(item["product_id"])
        meta = meta_dict.get(pid)
        original_name = warehouse_products.get(pid, f"Товар #{pid}")

        item["name"] = meta.marketing_name if meta and meta.marketing_name else original_name
        item["image"] = meta.images[0] if meta and meta.images else ""
        item["price"] = Decimal(str(item["price"]))

    # 1. Считаем чистую сумму товаров
    subtotal = sum(item["price"] * item["quantity"] for item in cart["items"])
    cart["subtotal"] = subtotal

    # 2. Проверяем, есть ли промокод
    discount_amount = Decimal("0.00")
    promo_data = await get_promo_from_cart(session_id)

    if promo_data:
        discount_amount = calculate_discount_amount(subtotal, promo_data)
        cart["promo_code"] = promo_data.code
        cart["discount_amount"] = discount_amount
        cart["discount_message"] = f"Скидка: {promo_data.code}"
    else:
        cart["promo_code"] = None
        cart["discount_amount"] = Decimal("0.00")

    # 3. Итоговая сумма к оплате (с вычетом скидки)
    cart["total"] = subtotal - discount_amount
    return cart


async def validate_certificate_with_warehouse(code: str) -> dict:
    """
    Делает запрос в Django для проверки статуса и баланса подарочного сертификата.
    """
    async with httpx.AsyncClient(headers=headers, timeout=5.0) as client:
        try:
            response = await client.get(f"{settings.WAREHOUSE_URL}/api/certificates/validate/?code={code}")
            data = response.json()

            # Если Django ответил ошибкой (400 или 404), прокидываем её в FastAPI
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=data.get("message", "Ошибка проверки сертификата")
                )

            # Если всё ок (200), возвращаем данные (is_valid и current_balance)
            return data

        except httpx.RequestError:
            # Если контейнер Django упал или не отвечает
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Сервис сертификатов временно недоступен"
            )