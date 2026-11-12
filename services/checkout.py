from services.payment import create_payment_link, PaymentGatewayError
from sqlalchemy.ext.asyncio import AsyncSession

from db.redis import get_cart, delete_cart
from models.order import Order, OrderItem
from models.outbox import OutboxEvent
from schemas.order import CheckoutRequest


class EmptyCartError(Exception):
    """Исключение: попытка оформить заказ с пустой корзиной"""
    pass


async def create_order_from_cart(request_data: CheckoutRequest, db: AsyncSession) -> dict:
    """Бизнес-логика оформления заказа"""

    # 1. Забираем корзину из Redis
    cart = await get_cart(request_data.session_id)
    if not cart or not cart.get("items"):
        raise EmptyCartError("Корзина пуста")

    # 2. Создаем заказ локально (телефон уже валидирован Pydantic)
    new_order = Order(
        customer_name=request_data.customer_name,
        customer_phone=request_data.customer_phone,
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

    # 4. ФОРМИРУЕМ OUTBOX EVENT для воркера
    outbox_payload = {
        "local_order_id": new_order.id,
        "customer_name": request_data.customer_name,
        "customer_phone": request_data.customer_phone,
        "customer_email": request_data.customer_email,
        "items": [
            {
                "product_id": item["product_id"],
                "quantity": item["quantity"],
                "price": item["price"],
                "name": item.get("title") or item.get("name", f"Товар ID {item['product_id']}")
            }
            for item in cart["items"]
        ]
    }

    outbox_event = OutboxEvent(
        event_type="order_created",
        payload=outbox_payload
    )
    db.add(outbox_event)

    # 5. ИНТЕГРАЦИЯ С БАНКОМ
    # Генерируем реальную ссылку и получаем ID транзакции
    try:
        payment_url, payment_id = await create_payment_link(
            amount=float(new_order.total_amount),
            order_id=new_order.id
        )
        new_order.payment_id = payment_id
    except PaymentGatewayError as e:
        # Если банк не отвечает, заказ не создастся (откат транзакции БД)
        raise e

    await db.commit()

    # 6. Очищаем корзину
    await delete_cart(request_data.session_id)

    return {
        "order_id": new_order.id,
        "payment_url": payment_url,
        "message": "Заказ успешно создан."
    }