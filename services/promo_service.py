import httpx
from core.config import settings
from schemas.promo import PromoValidationResult


async def validate_promo_with_warehouse(promo_code: str) -> PromoValidationResult:
    """
    Делает запрос к Django API для проверки промокода.
    """
    warehouse_url = f"{settings.WAREHOUSE_URL}/api/promocodes/validate/"
    headers = {"X-Service-Token": settings.SERVICE_API_KEY}

    try:
        async with httpx.AsyncClient(headers=headers, timeout=5.0) as client:
            response = await client.get(
                warehouse_url,
                params={"code": promo_code},
            )
            response.raise_for_status()

            data = response.json()

            if response.status_code == 200 and data.get("is_valid"):
                return PromoValidationResult(
                    is_valid=True,
                    code=data["code"],
                    discount_type=data["discount_type"],
                    discount_value=float(data["discount_value"]),
                    min_order_amount=float(data["min_order_amount"])
                )
            else:
                return PromoValidationResult(
                    is_valid=False,
                    message=data.get("message", "Промокод недействителен")
                )
    except Exception as e:
        # Если склад упал или не отвечает
        return PromoValidationResult(is_valid=False, message="Сервис проверки временно недоступен")