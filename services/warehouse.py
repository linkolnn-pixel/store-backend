import httpx
from core.config import settings


async def deduct_inventory(order_id: int, items: list) -> bool:
    """
    Отправляет HTTP-запрос в складское приложение для списания проданных позиций.
    """
    payload = {
        "order_id": order_id,
        "items": [
            {"product_id": item.product_id, "quantity": item.quantity}
            for item in items
        ]
    }

    # timeout=10.0 защищает приложение от зависания, если склад недоступен
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                f"{settings.WAREHOUSE_API_URL}/inventory/deduct",
                json=payload
            )
            response.raise_for_status()
            return True
        except httpx.HTTPError as e:
            # В production здесь должно быть логирование (например, через logging или Sentry),
            # чтобы администратор увидел, что склад не ответил на списание заказа.
            print(f"Ошибка синхронизации со складом для заказа {order_id}: {e}")
            return False