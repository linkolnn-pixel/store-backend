import json

from fastapi import APIRouter, Depends, Request, BackgroundTasks, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from starlette import status

from db.postgres import get_db_session
from models.order import Order, OrderStatus, OrderItem
from services.warehouse import deduct_inventory

router = APIRouter()


@router.post("/webhook/payment", summary="Прием вебхука от банка")
async def payment_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
        db: AsyncSession = Depends(get_db_session)
):
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пустое или некорректное тело запроса (ожидался JSON)"
        )

    payment_id = payload.get("object", {}).get("id")
    status_payment = payload.get("object", {}).get("status")

    if status_payment != "succeeded":
        return {"status": "ignored"}

    # Ищем заказ в PostgreSQL по ID транзакции
    result = await db.execute(select(Order).where(Order.payment_id == payment_id))
    order = result.scalars().first()

    if not order or order.status == OrderStatus.PAID:
        return {"status": "ok"}  # Заказ не найден или уже был успешно обработан

    # Фиксируем успешную оплату
    order.status = OrderStatus.PAID

    # Загружаем позиции заказа, чтобы передать их на склад
    result_items = await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))
    items = result_items.scalars().all()

    await db.commit()

    # Передаем команду списания остатков в фоновую задачу
    background_tasks.add_task(deduct_inventory, order.id, items)

    # Моментально отвечаем банку, что вебхук принят
    return {"status": "success"}