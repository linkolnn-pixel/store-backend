import httpx
from decimal import Decimal

from core.exceptions import EmptyCartError, PaymentGatewayError
from services.payment import create_payment_link
from sqlalchemy.ext.asyncio import AsyncSession

from db.redis import delete_cart
from services.cart import get_cart_with_meta, remove_promo_from_cart
from core.config import settings

from models.order import Order, OrderItem, OrderStatus
from models.outbox import OutboxEvent, OutboxStatus
from schemas.order import CheckoutRequest


async def get_certificate_balance(code: str) -> Decimal:
    """Стучится в Django API и узнает баланс сертификата"""
    try:
        headers = {"X-Service-Token": settings.SERVICE_API_KEY}
        async with httpx.AsyncClient(headers=headers, timeout=3.0) as client:
            response = await client.get(
                f"{settings.WAREHOUSE_URL}/api/certificates/validate/",
                params={"code": code},
            )
            if response.status_code == 200:
                data = response.json()
                return Decimal(str(data.get("current_balance", "0.00")))
    except Exception as e:
        print(f"Ошибка проверки сертификата {code}: {e}")

    return Decimal("0.00")


async def create_order_from_cart(request_data: CheckoutRequest, db: AsyncSession) -> dict:
    """Бизнес-логика оформления заказа"""

    # 1. Достаем корзину
    cart = await get_cart_with_meta(request_data.session_id, db)

    if not cart or not cart.get("items"):
        raise EmptyCartError("Корзина пуста")

    # 2. РАСЧЕТ ОПЛАТЫ С УЧЕТОМ ПОДАРОЧНОЙ КАРТЫ
    cart_total = Decimal(str(cart["total"]))
    total_to_pay = cart_total
    certificate_amount_used = Decimal("0.00")

    if request_data.gift_certificate:
        balance = await get_certificate_balance(request_data.gift_certificate)
        if balance > 0:
            # Берем меньшее из двух: либо всю сумму корзины, либо весь остаток карты
            certificate_amount_used = min(cart_total, balance)
            total_to_pay -= certificate_amount_used

    # 3. Создаем заказ локально (в total_amount пишем СУММУ К ОПЛАТЕ ДЕНЬГАМИ)
    new_order = Order(
        customer_name=request_data.customer_name,
        customer_phone=request_data.customer_phone,
        customer_email=request_data.customer_email,
        total_amount=float(total_to_pay)
    )
    db.add(new_order)
    await db.flush()

    # 4. Привязываем товары
    for item in cart["items"]:
        order_item = OrderItem(
            order_id=new_order.id,
            product_id=item["product_id"],
            quantity=item["quantity"],
            price_at_purchase=item["price"]
        )
        db.add(order_item)

    # 5. ФОРМИРУЕМ OUTBOX EVENT для воркера (ПРОКИДЫВАЕМ НОВЫЕ ПОЛЯ)
    outbox_payload = {
        "local_order_id": new_order.id,
        "customer_name": request_data.customer_name,
        "customer_phone": request_data.customer_phone,
        "customer_email": request_data.customer_email,
        "comment": request_data.comment,  # <-- Передаем коммент в Django
        "gift_certificate": request_data.gift_certificate,  # <-- Передаем код карты в Django
        "order_details": {
            "subtotal": float(cart["subtotal"]),
            "promo_code": cart.get("promo_code"),
            "discount_amount": float(cart.get("discount_amount", 0.0)),
            "certificate_amount_used": float(certificate_amount_used),  # Сколько сняли с карты
            "total_to_pay": float(total_to_pay)  # Сколько доплатили
        },
        "items": [
            {
                "product_id": item["product_id"],
                "quantity": item["quantity"],
                "price": float(item["price"]),
                "name": item.get("title") or item.get("name", f"Товар ID {item['product_id']}")
            }
            for item in cart["items"]
        ]
    }

    # ДЛЯ ТЕСТОВ (МОК ОПЛАТЫ): Сразу ставим PENDING и PAID, чтобы воркер забрал без вебхука
    new_order.status = OrderStatus.PENDING

    outbox_event = OutboxEvent(
        event_type="order_created",
        payload=outbox_payload,
        status=OutboxStatus.PENDING.value,
        processed=False
    )
    db.add(outbox_event)

    # 6. ИНТЕГРАЦИЯ С БАНКОМ
    payment_url = None
    if total_to_pay > 0:
        # Дергаем эквайринг только если есть что оплачивать
        try:
            payment_url, payment_id = await create_payment_link(
                amount=float(total_to_pay),
                order_id=new_order.id
            )
            new_order.payment_id = payment_id
        except PaymentGatewayError as e:
            raise e
    else:
        # Карта полностью покрыла заказ!
        import uuid
        new_order.payment_id = f"CERT_{new_order.id}_{uuid.uuid4().hex[:8]}"

    await db.commit()

    # 7. Очищаем корзину И УДАЛЯЕМ ПРОМОКОД
    await delete_cart(request_data.session_id)
    await remove_promo_from_cart(request_data.session_id)

    return {
        "order_id": new_order.id,
        "payment_url": payment_url,
        "message": "Заказ успешно создан." if total_to_pay > 0 else "Заказ полностью оплачен подарочной картой!"
    }