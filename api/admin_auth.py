import secrets
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from core.config import settings

router = APIRouter(tags=["Admin Auth"])
ALGORITHM = getattr(settings, "ALGORITHM", "HS256")


@router.post("/admin/login", summary="Авторизация администратора")
async def login_admin(data: OAuth2PasswordRequestForm = Depends()):
    admin_pass = settings.ADMIN_PASSWORD.get_secret_value() if hasattr(settings.ADMIN_PASSWORD,
                                                                       'get_secret_value') else settings.ADMIN_PASSWORD

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

    token = jwt.encode({"sub": data.username, "exp": expire, "role": "admin"}, secret, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer"}