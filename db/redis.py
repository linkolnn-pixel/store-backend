import json
from redis.asyncio import Redis
from core.config import settings

# Инициализация асинхронного клиента Redis
# decode_responses=True автоматически декодирует байты в строки
redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)

async def save_cart(session_id: str, cart_data: dict, expire_seconds: int = 86400):
    """
    Сохраняет корзину в Redis. По умолчанию удаляется через 24 часа (86400 секунд).
    """
    await redis_client.setex(
        name=f"cart:{session_id}",
        time=expire_seconds,
        value=json.dumps(cart_data)
    )

async def get_cart(session_id: str) -> dict | None:
    """
    Извлекает корзину по session_id.
    """
    data = await redis_client.get(f"cart:{session_id}")
    if data:
        return json.loads(data)
    return None

async def delete_cart(session_id: str):
    """
    Удаляет корзину после успешного оформления заказа.
    """
    await redis_client.delete(f"cart:{session_id}")

