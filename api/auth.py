import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel

from core.config import settings

router = APIRouter()

ALGORITHM = "HS256"
# Указываем, куда фронтенд должен стучаться за токеном
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/admin/login")

# 1. Создаем простую схему для JSON-запроса
class LoginRequest(BaseModel):
    username: str
    password: str

# 2. Функция проверки токена (Замок)
def get_current_admin(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username != settings.ADMIN_USERNAME:
            raise HTTPException(status_code=401, detail="Нет прав")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Неверный или просроченный токен")
    return username


# 3. Эндпоинт для логина (Выдача ключа)
@router.post("/admin/login", summary="Авторизация администратора")
async def login_admin(data: LoginRequest):
    if data.username != settings.ADMIN_USERNAME or data.password != settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=400, detail="Неверный логин или пароль")

    # Создаем токен, действительный 1 день
    expire = datetime.now(timezone.utc) + timedelta(days=1)
    token = jwt.encode({"sub": data.username, "exp": expire}, settings.SECRET_KEY, algorithm=ALGORITHM)

    return {"access_token": token, "token_type": "bearer"}