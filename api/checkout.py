from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db_session
from db.redis import get_cart, delete_cart
from models.order import Order, OrderItem
from schemas.order import CheckoutRequest

# from services.payment import create_payment_link  # Подключим позже

router = APIRouter()


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
            detail="Корзина пуста или время сессии истекло"
        )

    # 2. Создаем запись о заказе в PostgreSQL
    new_order = Order(
        customer_name=request_data.customer_name,
        customer_phone=request_data.customer_phone,
        customer_email=request_data.customer_email,
        total_amount=cart["total"]
    )
    db.add(new_order)
    # Делаем flush, чтобы БД присвоила заказу ID, но транзакция еще не завершилась
    await db.flush()

    # 3. Привязываем позиции из корзины к созданному заказу
    for item in cart["items"]:
        order_item = OrderItem(
            order_id=new_order.id,
            product_id=item["product_id"],
            quantity=item["quantity"],
            price_at_purchase=item["price"]
        )
        db.add(order_item)

    # 4. Имитация вызова эквайринга (напишем этот сервис следующим)
    # payment_url, payment_id = await create_payment_link(amount=new_order.total_amount, order_id=new_order.id)
    payment_id = f"mock_payment_{new_order.id}"
    payment_url = "http://localhost:5174/success"

    # Записываем ID транзакции банка и окончательно сохраняем всё в базу
    new_order.payment_id = payment_id
    await db.commit()

    # 5. Очищаем корзину в Redis после успешного формирования заказа
    await delete_cart(request_data.session_id)

    return {
        "order_id": new_order.id,
        "payment_url": payment_url,
        "message": "Заказ успешно создан."
    }