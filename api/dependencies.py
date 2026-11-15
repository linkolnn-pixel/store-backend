import secrets
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
from core.config import settings

ALGORITHM = getattr(settings, "ALGORITHM", "HS256")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/admin/login")
customer_scheme = HTTPBearer()


def get_current_admin(token: str = Depends(oauth2_scheme)):
    """Проверка токена админа"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный или просроченный токен админа",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        secret = settings.SECRET_KEY.get_secret_value() if hasattr(settings.SECRET_KEY,
                                                                   'get_secret_value') else settings.SECRET_KEY
        payload = jwt.decode(token, secret, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username or not secrets.compare_digest(username, settings.ADMIN_USERNAME):
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    return username


def get_current_customer(credentials: HTTPAuthorizationCredentials = Depends(customer_scheme)):
    """Проверка токена клиента"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Неверный токен клиента",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        secret = settings.SECRET_KEY.get_secret_value() if hasattr(settings.SECRET_KEY,
                                                                   'get_secret_value') else settings.SECRET_KEY
        payload = jwt.decode(credentials.credentials, secret, algorithms=[ALGORITHM])

        phone: str = payload.get("sub")
        role: str = payload.get("role")
        if not phone or role != "customer":
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    return phone