import secrets

import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm

from core.config import settings

router = APIRouter()

ALGORITHM = getattr(settings, "ALGORITHM", "HS256")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/admin/login")

# Функция проверки токена
def get_current_admin(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный или просроченный токен",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        secret = settings.SECRET_KEY.get_secret_value() if hasattr(settings.SECRET_KEY,
                                                                   'get_secret_value') else settings.SECRET_KEY
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        username: str = payload.get("sub")

        # Защита от пустых токенов и сверка с админом
        if not username or not secrets.compare_digest(username, settings.ADMIN_USERNAME):
            raise credentials_exception

    except jwt.PyJWTError:
        raise credentials_exception

    return username


@router.post("/admin/login", summary="Авторизация администратора")
async def login_admin(data: OAuth2PasswordRequestForm = Depends()):
    admin_pass = settings.ADMIN_PASSWORD.get_secret_value() if hasattr(settings.ADMIN_PASSWORD,
                                                                       'get_secret_value') else settings.ADMIN_PASSWORD

    # Безопасное сравнение строк за константное время
    is_username_correct = secrets.compare_digest(data.username, settings.ADMIN_USERNAME)
    is_password_correct = secrets.compare_digest(data.password, admin_pass)

    if not (is_username_correct and is_password_correct):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    expire_minutes = getattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", 60 * 24)
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)

    secret = settings.SECRET_KEY.get_secret_value() if hasattr(settings.SECRET_KEY,
                                                               'get_secret_value') else settings.SECRET_KEY
    token = jwt.encode({"sub": data.username, "exp": expire}, secret, algorithm=ALGORITHM)

    return {"access_token": token, "token_type": "bearer"}