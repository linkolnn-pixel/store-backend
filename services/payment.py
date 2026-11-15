import uuid

from core.exceptions import PaymentNotFoundError, PaymentAlreadyProcessedError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core.config import settings
from models.order import Order, OrderStatus
from models.outbox import OutboxEvent, OutboxStatus


# ==========================================
# 1. ИСХОДЯЩАЯ ЛОГИКА (Генерация ссылки)
# Вызывается из services/checkout.py при оформлении заказа
# ==========================================
async def create_payment_link(amount: float, order_id: int) -> tuple[str, str]:
    idempotence_key = str(uuid.uuid4())

    # ... твой payload для ЮKassa ...

    # Генерируем моковый payment_id
    mock_payment_id = f"mock_paid_{order_id}_{idempotence_key[:8]}"
    mock_confirmation_url = f"http://localhost:8000/api/v1/payment/mock-success?order_id={order_id}"

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
    print(f"👉 [DEBUG] Начало process_successful_payment для payment_id: {payment_id}")

    stmt = select(Order).where(Order.payment_id == payment_id)
    result = await db.execute(stmt)
    order = result.scalar_one_or_none()

    if not order:
        print(f"👉 [DEBUG] Ошибка: Заказ с payment_id {payment_id} не найден!")
        raise PaymentNotFoundError(f"Заказ с payment_id {payment_id} не найден")

    print(f"👉 [DEBUG] Заказ найден. Текущий статус: {order.status}")

    if order.status == OrderStatus.PAID:
        print("👉 [DEBUG] Заказ УЖЕ БЫЛ ОПЛАЧЕН. Выходим без создания outbox_event.")
        raise PaymentAlreadyProcessedError("Заказ уже был оплачен ранее")

    # Меняем статус
    order.status = OrderStatus.PAID
    print("👉 [DEBUG] Статус изменён на PAID. Формируем событие outbox...")

    outbox_payload = {
        "local_order_id": order.id,
        "payment_id": payment_id,
        "amount": str(order.total_amount)
    }

    outbox_event = OutboxEvent(
        event_type="order_paid",
        payload=outbox_payload,
        status=OutboxStatus.PENDING.value,
        processed=False  # Явно указываем False на всякий случай
    )

    db.add(outbox_event)
    await db.commit()
    print("👉 [DEBUG] Событие успешно сохранено в БД (db.commit выполнен!)")

    return {"status": "success", "order_id": order.id}