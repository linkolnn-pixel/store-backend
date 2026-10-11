import uuid
import httpx
from core.config import settings


# Если добавите ключи в config.py, раскомментируйте:
# SHOP_ID = settings.YOOKASSA_SHOP_ID
# SECRET_KEY = settings.YOOKASSA_SECRET_KEY

async def create_payment_link(amount: float, order_id: int) -> tuple[str, str]:
    """
    Отправляет запрос в API банка для создания платежа.
    Возвращает URL для перенаправления клиента и ID транзакции в системе банка.
    """

    # Ключ идемпотентности гарантирует, что при сбое сети
    # банк не создаст два одинаковых платежа
    idempotence_key = str(uuid.uuid4())

    payload = {
        "amount": {
            "value": f"{amount:.2f}",
            "currency": "RUB"
        },
        "capture": True,  # Деньги списываются сразу
        "confirmation": {
            "type": "redirect",
            "return_url": "https://ваш-домен.ру/success"  # Куда вернуть клиента после оплаты
        },
        "description": f"Оплата заказа №{order_id}",
        "metadata": {
            "order_id": order_id
        }
    }

    async with httpx.AsyncClient() as client:
        # Пример базовой аутентификации для ЮKassa
        # auth=(SHOP_ID, SECRET_KEY)

        # Имитация ответа от банка (пока нет реальных ключей)
        mock_payment_id = f"2c{order_id}b4-000f-5000-9000-{idempotence_key[:12]}"
        mock_confirmation_url = f"https://yookassa.ru/pay/{mock_payment_id}"

        return mock_confirmation_url, mock_payment_id

        """ 
        # РЕАЛЬНЫЙ КОД ДЛЯ ПРОДАКШЕНА:
        try:
            response = await client.post(
                "https://api.yookassa.ru/v3/payments",
                json=payload,
                auth=auth,
                headers={"Idempotence-Key": idempotence_key}
            )
            response.raise_for_status()
            data = response.json()

            return data["confirmation"]["confirmation_url"], data["id"]
        except httpx.HTTPError as e:
            print(f"Ошибка создания платежа для заказа {order_id}: {e}")
            raise ValueError("Не удалось инициализировать платеж")
        """