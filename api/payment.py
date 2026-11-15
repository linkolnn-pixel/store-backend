from core.exceptions import PaymentGatewayError, PaymentNotFoundError, PaymentAlreadyProcessedError
from fastapi import APIRouter, Depends, HTTPException, status, Query
from models.order import Order, OrderStatus
from models.outbox import OutboxStatus, OutboxEvent
from services.payment import process_successful_payment
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db_session
from schemas.order import CheckoutRequest
from services import checkout as checkout_service


router = APIRouter()

@router.post("/checkout", summary="Оформление заказа")
async def process_checkout(
        request_data: CheckoutRequest,
        db: AsyncSession = Depends(get_db_session)
):
    try:
        return await checkout_service.create_order_from_cart(request_data, db)
    except checkout_service.EmptyCartError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except PaymentGatewayError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Оплата временно недоступна, попробуйте позже. Ошибка: {str(e)}"
        )

@router.post("/webhook")
async def yookassa_webhook(payload: dict, db: AsyncSession = Depends(get_db_session)):
    try:
        print(f"📥 Получен вебхук: {payload}")

        # Раскручиваем возможные вложенности (включая мусор от Swagger)
        data = payload
        if "additionalProp1" in payload:
            data = payload["additionalProp1"]
        elif "object" in payload:
            data = payload["object"]

        # Достаем ID платежа
        payment_id = data.get("payment_id") or data.get("id")

        if not payment_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Не удалось обнаружить payment_id в запросе"
            )

        result = await process_successful_payment(str(payment_id), db)
        return result

    except PaymentNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except PaymentAlreadyProcessedError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get("/payment/mock-success")
async def mock_payment_success(
        order_id: int = Query(..., description="ID заказа для мок-оплаты"),
        db: AsyncSession = Depends(get_db_session)
):
    """Эндпоинт-заглушка: передает управление в process_successful_payment"""
    stmt = select(Order).where(Order.id == order_id)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise HTTPException(status_code=404, detail="Заказ не найден")

    # Убеждаемся, что payment_id существует
    payment_id_to_process = order.payment_id
    if not payment_id_to_process:
        payment_id_to_process = f"mock_paid_{order.id}"
        order.payment_id = payment_id_to_process
        await db.commit()

    # Если статус уже PAID, значит событие либо уже создано, либо это баг старого кода.
    # В моковом окружении мы можем принудительно сбросить статус, чтобы тест прошел:
    if order.status == OrderStatus.PAID:
        order.status = OrderStatus.PENDING
        await db.commit()

    try:
        # Вызываем единую функцию
        result = await process_successful_payment(payment_id_to_process, db)
        return {
            "status": "success",
            "message": f"Платёж для заказа №{order_id} успешно эмулирован!",
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))