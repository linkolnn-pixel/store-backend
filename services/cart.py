import uuid
import httpx
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core.config import settings
from db.redis import get_cart, save_cart
from models.product_meta import ProductMeta
from schemas.cart import CartItemAddSchema


class ProductNotFoundError(Exception):
    pass


class CartNotFoundError(Exception):
    pass



async def fetch_price_for_product(product_id: int) -> Decimal | None:
    """Запрашивает актуальную цену товара со склада."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            headers = {"Authorization": f"Api-Key {settings.SERVICE_API_KEY}"}
            response = await client.get(f"{settings.WAREHOUSE_URL}/api/products/{product_id}/", headers=headers)
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
        # В production заменить на logging.error
        print(f"Ошибка HTTP при получении цены для товара {product_id}: {e}")
    return None


async def fetch_warehouse_names(product_ids: list[int]) -> dict[int, str]:
    """Запрашивает названия товаров со склада."""
    if not product_ids:
        return {}

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            ids_query = ",".join(map(str, product_ids))
            response = await client.get(f"{settings.WAREHOUSE_URL}/api/products/", params={"ids": ids_query})

            if response.status_code == 200:
                data = response.json()
                products_list = data.get("results", data) if isinstance(data, dict) else data
                return {p["id"]: p["name"] for p in products_list}
    except Exception as e:
        print(f"Не удалось получить названия со склада: {e}")
    return {}


async def add_product_to_cart(session_id: str | None, item: CartItemAddSchema) -> tuple[str, dict]:
    actual_price = await fetch_price_for_product(item.product_id)
    if actual_price is None:
        raise ProductNotFoundError(f"Товар {item.product_id} недоступен или не существует")

    session_id = session_id or str(uuid.uuid4())
    cart = await get_cart(session_id) or {"session_id": session_id, "items": [], "total": Decimal("0.0")}

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


async def get_cart_with_meta(session_id: str, db: AsyncSession) -> dict:
    cart = await get_cart(session_id)
    if not cart:
        raise CartNotFoundError("Корзина не найдена или истекла")

    if not cart.get("items"):
        return cart

    product_ids = [int(item["product_id"]) for item in cart["items"]]

    # Получаем метаданные из локальной базы
    stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id.in_(product_ids))
    result = await db.execute(stmt)
    meta_dict = {meta.warehouse_product_id: meta for meta in result.scalars().all()}

    # Получаем названия со склада
    warehouse_products = await fetch_warehouse_names(product_ids)

    # Обогащаем товары
    for item in cart["items"]:
        pid = int(item["product_id"])
        meta = meta_dict.get(pid)
        original_name = warehouse_products.get(pid, f"Товар #{pid}")

        item["name"] = meta.marketing_name if meta and meta.marketing_name else original_name
        item["image"] = meta.images[0] if meta and meta.images else ""
        item["price"] = Decimal(str(item["price"]))

    cart["total"] = sum(item["price"] * item["quantity"] for item in cart["items"])
    return cart


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