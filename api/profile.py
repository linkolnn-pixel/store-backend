import httpx
from fastapi import APIRouter, Depends, HTTPException, status

from core.config import settings
from api.dependencies import get_current_customer  # Импортируем нашу зависимость

router = APIRouter(prefix="/profile", tags=["Customer Profile"])


@router.get("/orders", summary="Получить историю заказов")
async def get_my_orders(phone: str = Depends(get_current_customer)):
    """
    Отдает историю заказов текущего авторизованного клиента.
    Телефон автоматически извлекается из JWT токена.
    """
    # Авторизуемся в Django как внутренний сервис
    headers = {"X-Service-Token": settings.SERVICE_API_KEY}

    async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
        try:
            # Идем в Django Склад и передаем телефон для фильтрации
            response = await client.get(
                f"{settings.WAREHOUSE_URL}/api/sales/",
                params={"phone": phone}
            )
        except httpx.RequestError as e:
            print(f"Сетевая ошибка при обращении к Django: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Сервис истории заказов временно недоступен"
            )

        if response.status_code != 200:
            print(f"Ошибка Django API: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось получить историю заказов"
            )

        data = response.json()

        if isinstance(data, dict):
            return data.get("results", [])
        return data