import uuid
from fastapi import APIRouter, HTTPException
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
async def view_cart(session_id: str):
    cart = await get_cart(session_id)
    if not cart:
        raise HTTPException(status_code=404, detail="Корзина не найдена или истекла")
    return cart


@router.post("/cart/update", summary="Обновить количество товара")
async def update_item_quantity(data: CartUpdateSchema):
    cart = await get_cart(data.session_id)
    if not cart:
        raise HTTPException(status_code=404, detail="Корзина не найдена")

    for item in cart.get("items", []):
        if item["product_id"] == data.product_id:
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

    cart["items"] = [item for item in cart.get("items", []) if item["product_id"] != data.product_id]
    cart["total"] = sum(i["price"] * i["quantity"] for i in cart["items"])

    await save_cart(data.session_id, cart)

    return {"message": "Товар удален", "cart": cart}