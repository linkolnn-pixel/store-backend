import httpx
from fastapi import APIRouter, HTTPException, Depends, status
from schemas.promo import PromoApplyRequest
from sqlalchemy.ext.asyncio import AsyncSession

from db.postgres import get_db_session
from schemas.cart import CartItemAddSchema, CartUpdateSchema, CartRemoveSchema

from services import cart as cart_service
from services.promo_service import validate_promo_with_warehouse

router = APIRouter()

@router.post("/cart/add", summary="Добавить товар или услугу в корзину")
async def add_item_to_cart(item: CartItemAddSchema, session_id: str | None = None):
    try:
        new_session, updated_cart = await cart_service.add_product_to_cart(session_id, item)
        return {"session_id": new_session, "cart": updated_cart}
    except cart_service.ProductNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/cart/{session_id}", summary="Получить состав корзины")
async def view_cart(session_id: str, db: AsyncSession = Depends(get_db_session)):
    try:
        return await cart_service.get_cart_with_meta(session_id, db)
    except cart_service.CartNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/cart/update", summary="Обновить количество товара")
async def update_item_quantity(data: CartUpdateSchema):
    try:
        cart = await cart_service.update_item_quantity(data.session_id, data.product_id, data.quantity)
        return {"message": "Количество обновлено", "cart": cart}
    except cart_service.CartNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/cart/remove", summary="Удалить товар из корзины")
async def remove_item_from_cart(data: CartRemoveSchema):
    try:
        cart = await cart_service.remove_item_from_cart(data.session_id, data.product_id)
        return {"message": "Товар удален", "cart": cart}
    except cart_service.CartNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/promo/apply", summary="Применить промокод к корзине")
async def apply_promo_api(
        payload: PromoApplyRequest,
        session_id: str
):
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id обязателен")

    # 1. Спрашиваем у Django
    promo_result = await validate_promo_with_warehouse(payload.promo_code)

    if not promo_result.is_valid:
        # Отдаем ошибку с сообщением от Django (например, "Промокод истек")
        raise HTTPException(status_code=400, detail=promo_result.message)

    # 2. Сохраняем в Redis
    await cart_service.apply_promo_to_cart(session_id, promo_result)

    return {
        "success": True,
        "message": f"Промокод {promo_result.code} успешно применен!"
    }


@router.delete("/promo/remove", summary="Удалить промокод из корзины")
async def remove_promo_api(session_id: str):
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id обязателен")

    await cart_service.remove_promo_from_cart(session_id)
    return {"success": True, "message": "Промокод удален"}


@router.get("/certificates/validate/", summary="Проверить баланс подарочного сертификата")
async def validate_gift_certificate(code: str):
    # Роутер просто вызывает сервис. Все проверки и ошибки (HTTPException) обрабатываются там!
    return await cart_service.validate_certificate_with_warehouse(code)