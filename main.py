import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from core.config import settings
from api.checkout import router as checkout_router
from api.webhooks import router as webhook_router
from api.cart import router as cart_router
from api.catalog import router as catalog_router

from api.auth import router as auth_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Бэкенд магазина и онлайн-записи",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:3000", "https://ваш-домен.ру"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("uploads/images", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Подключение роутеров
app.include_router(auth_router, prefix="/api/v1", tags=["Авторизация"])
app.include_router(checkout_router, prefix="/api/v1", tags=["Заказы"])
app.include_router(webhook_router, prefix="/api/v1", tags=["Интеграции"])
app.include_router(cart_router, prefix="/api/v1", tags=["Корзина"])
app.include_router(catalog_router, prefix="/api/v1", tags=["Catalog"])

@app.get("/health", tags=["Система"])
async def health_check():
    """Проверка доступности сервера"""
    return {"status": "ok", "message": "API функционирует нормально"}