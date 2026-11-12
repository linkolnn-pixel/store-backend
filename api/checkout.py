from fastapi import APIRouter, Depends, HTTPException, status
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
        # Передаем всю работу сервису
        result = await checkout_service.create_order_from_cart(request_data, db)
        return result
    except checkout_service.EmptyCartError as e:
        # Ловим бизнес-ошибку и превращаем ее в HTTP 400
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )