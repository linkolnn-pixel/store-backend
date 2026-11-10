from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
import re

from db.postgres import get_db_session
from db.redis import get_cart, delete_cart
from models.order import Order, OrderItem
from models.outbox import OutboxEvent  # Наша новая модель
from schemas.order import CheckoutRequest

router = APIRouter()


def normalize_phone(phone: str) -> str:
    cleaned = re.sub(r'[^\d+]', '', phone)
    if cleaned.startswith('8') and len(cleaned) == 11:
        cleaned = '+7' + cleaned[1:]
    elif cleaned.startswith('7') and len(cleaned) == 11:
        cleaned = '+' + cleaned
    return cleaned


@router.post("/checkout", summary="Оформление заказа")
async def process_checkout(
        request_data: CheckoutRequest,
        db: AsyncSession = Depends(get_db_session)
):
    # 1. Забираем корзину из Redis
    cart = await get_cart(request_data.session_id)
    if not cart or not cart.get("items"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Корзина пуста"
        )

    clean_phone = normalize_phone(request_data.customer_phone)

    # 2. Создаем заказ локально
    new_order = Order(
        customer_name=request_data.customer_name,
        customer_phone=clean_phone,
        customer_email=request_data.customer_email,
        total_amount=cart["total"]
    )
    db.add(new_order)
    await db.flush()

    # 3. Привязываем товары
    for item in cart["items"]:
        order_item = OrderItem(
            order_id=new_order.id,
            product_id=item["product_id"],
            quantity=item["quantity"],
            price_at_purchase=item["price"]
        )
        db.add(order_item)

    # 4. ФОРМИРУЕМ OUTBOX EVENT
    # Собираем данные, которые понадобятся скрипту-отправщику
    outbox_payload = {
        "local_order_id": new_order.id,
        "customer_name": request_data.customer_name,
        "customer_phone": clean_phone,
        "customer_email": request_data.customer_email,
        "items": [
            {
                "product_id": item["product_id"],
                "quantity": item["quantity"],
                "price": item["price"]
            }
            for item in cart["items"]
        ]
    }

    outbox_event = OutboxEvent(
        event_type="order_created",
        payload=outbox_payload
    )
    db.add(outbox_event)

    # 5. Сохраняем всё СРАЗУ. 
    payment_id = f"mock_payment_{new_order.id}"
    payment_url = "http://localhost:5173/success"
    new_order.payment_id = payment_id

    await db.commit()

    # 6. Очищаем корзину
    await delete_cart(request_data.session_id)

    return {
        "order_id": new_order.id,
        "payment_url": payment_url,
        "message": "Заказ успешно создан."
    }