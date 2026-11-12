import uuid
import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core.config import settings
from models.order import Order, OrderStatus
from models.outbox import OutboxEvent


class PaymentNotFoundError(Exception):
    pass


class PaymentAlreadyProcessedError(Exception):
    pass


class PaymentGatewayError(Exception):
    pass


# ==========================================
# 1. ИСХОДЯЩАЯ ЛОГИКА (Генерация ссылки)
# Вызывается из services/checkout.py при оформлении заказа
# ==========================================
async def create_payment_link(amount: float, order_id: int) -> tuple[str, str]:
    idempotence_key = str(uuid.uuid4())

    # ... твой payload для ЮKassa ...

    # Пока нет реальных ключей — возвращаем моковые данные
    mock_payment_id = f"2c{order_id}b4-000f-5000-9000-{idempotence_key[:12]}"
    mock_confirmation_url = f"https://yookassa.ru/pay/{mock_payment_id}"

    return mock_confirmation_url, mock_payment_id

    # РЕАЛЬНЫЙ КОД ДЛЯ ПРОДАКШЕНА:
    # try:
    #     async with httpx.AsyncClient() as client:
    #         ... запрос к банку ...
    # except httpx.HTTPError as e:
    #     raise PaymentGatewayError(f"Не удалось инициализировать платеж: {e}")


# ==========================================
# 2. ВХОДЯЩАЯ ЛОГИКА (Обработка вебхука)
# Вызывается из api/payment.py, когда банк присылает подтверждение
# ==========================================
async def process_successful_payment(payment_id: str, db: AsyncSession) -> dict:
    stmt = select(Order).where(Order.payment_id == payment_id)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        raise PaymentNotFoundError(f"Заказ с payment_id {payment_id} не найден")

    if order.status == OrderStatus.PAID:
        raise PaymentAlreadyProcessedError("Заказ уже был оплачен ранее")

    # Меняем статус
    order.status = OrderStatus.PAID

    # Формируем событие оплаты для Outbox-воркера
    outbox_payload = {
        "local_order_id": order.id,
        "payment_id": payment_id,
        "amount": str(order.total_amount)
    }

    outbox_event = OutboxEvent(
        event_type="order_paid",
        payload=outbox_payload
    )

    db.add(outbox_event)
    await db.commit()

    return {"status": "success", "order_id": order.id}