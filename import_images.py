import asyncio
import os
import shutil
import uuid
from contextlib import asynccontextmanager

import httpx
from pathlib import Path

# Импортируем настройки, сессию БД и модель
from core.config import settings  # Берем настройки из .env
from db.postgres import get_db_session
from models.product_meta import ProductMeta
from sqlalchemy.future import select

# ИСПРАВЛЕНО 1: Указываем папку точно как в main.py и catalog.py
SOURCE_IMAGES_DIR = Path("source_images")
UPLOADS_DIR = Path("uploads/images")


@asynccontextmanager
async def session_scope():
    async for session in get_db_session():
        yield session


async def run_import():
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    print("Получаем список товаров со склада...")

    # ИСПРАВЛЕНО 2: Добавляем токен авторизации в запрос
    headers = {"X-Service-Token": settings.SERVICE_API_KEY}

    # ИСПРАВЛЕНО 3: Используем WAREHOUSE_URL из настроек Docker
    async with httpx.AsyncClient(headers=headers) as client:
        response = await client.get(f"{settings.WAREHOUSE_URL}/api/products/")
        response.raise_for_status()  # Проверим, что нет ошибок 401/403/500
        warehouse_data = response.json()
        products = warehouse_data.get("results", warehouse_data) if isinstance(warehouse_data, dict) else warehouse_data

    code_to_id = {str(p["internal_code"]): p["id"] for p in products if p.get("internal_code")}

    async with session_scope() as db:
        for folder_path in SOURCE_IMAGES_DIR.iterdir():
            if not folder_path.is_dir():
                continue

            internal_code = folder_path.name
            product_id = code_to_id.get(internal_code)

            if not product_id:
                print(f"Пропуск: Товар с кодом {internal_code} не найден на складе.")
                continue

            stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id == product_id)
            result = await db.execute(stmt)
            meta = result.scalar_one_or_none()

            if not meta:
                meta = ProductMeta(warehouse_product_id=product_id, images=[])
                db.add(meta)

            image_urls = []

            for img_file in folder_path.iterdir():
                if img_file.is_file() and img_file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
                    new_filename = f"{uuid.uuid4()}{img_file.suffix.lower()}"
                    dest_path = UPLOADS_DIR / new_filename

                    shutil.copy2(img_file, dest_path)

                    # ИСПРАВЛЕНО 4: Путь в БД тоже должен совпадать с тем, что ждет фронт
                    image_urls.append(f"/uploads/images/{new_filename}")

            if image_urls:
                meta.images = image_urls
                print(f"Успех: Загружено {len(image_urls)} фото для товара {internal_code} (ID: {product_id})")

        await db.commit()
        print("Импорт успешно завершен!")


if __name__ == "__main__":
    asyncio.run(run_import())