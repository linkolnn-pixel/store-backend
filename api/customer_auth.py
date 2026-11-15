import random
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException
from core.config import settings
from db.redis import redis_client
from schemas.auth import PhoneRequest, VerifyRequest

router = APIRouter(prefix="/customer", tags=["Customer Auth"])
ALGORITHM = getattr(settings, "ALGORITHM", "HS256")



@router.post("/request-code", summary="Запросить код подтверждения")
async def request_code(data: PhoneRequest):
    code = str(random.randint(1000, 9999))
    redis_key = f"auth_code_{data.phone}"
    await redis_client.setex(redis_key, 180, code)
    print(f"🚨 КОД ДЛЯ {data.phone}: {code}")
    return {"message": "Код отправлен"}


@router.post("/verify-code", summary="Подтвердить код и получить токен")
async def verify_code(data: VerifyRequest):
    redis_key = f"auth_code_{data.phone}"
    saved_code = await redis_client.get(redis_key)

    if not saved_code or saved_code != data.code:
        raise HTTPException(status_code=400, detail="Неверный или истекший код")

    await redis_client.delete(redis_key)

    expire = datetime.now(timezone.utc) + timedelta(days=30)
    secret = settings.SECRET_KEY.get_secret_value() if hasattr(settings.SECRET_KEY,
                                                               'get_secret_value') else settings.SECRET_KEY

    token = jwt.encode({"sub": data.phone, "exp": expire, "role": "customer"}, secret, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}