import asyncio
import os
import shutil
import uuid
from contextlib import asynccontextmanager

import httpx
from pathlib import Path

# Импортируйте вашу сессию БД и модель
from db.postgres import get_db_session
from models.product_meta import ProductMeta
from sqlalchemy.future import select

WAREHOUSE_URL = "http://127.0.0.1:8001"
SOURCE_IMAGES_DIR = Path("source_images")  # Папка, куда вы скачали ваши отсортированные картинки
UPLOADS_DIR = Path("uploads/products")  # Папка, откуда FastAPI раздает статику


@asynccontextmanager
async def session_scope():
    async for session in get_db_session():
        yield session

async def run_import():
    # 1. Создаем папку для публичных картинок, если ее нет
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    # 2. Получаем все товары со склада (Django), чтобы сопоставить internal_code и id
    print("Получаем список товаров со склада...")
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{WAREHOUSE_URL}/api/products/")
        warehouse_data = response.json()
        products = warehouse_data.get("results", warehouse_data) if isinstance(warehouse_data, dict) else warehouse_data

    # Создаем словарь: { "0001": 1, "0002": 2 }  (internal_code -> id)
    code_to_id = {str(p["internal_code"]): p["id"] for p in products if p.get("internal_code")}

    # 3. Открываем сессию к базе данных FastAPI
    async with session_scope() as db:

        # 4. Проходимся по всем папкам (внутренним кодам)
        for folder_path in SOURCE_IMAGES_DIR.iterdir():
            if not folder_path.is_dir():
                continue

            internal_code = folder_path.name
            product_id = code_to_id.get(internal_code)

            if not product_id:
                print(f"Пропуск: Товар с кодом {internal_code} не найден на складе.")
                continue

            # 5. Ищем или создаем ProductMeta
            stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id == product_id)
            result = await db.execute(stmt)
            meta = result.scalar_one_or_none()

            if not meta:
                meta = ProductMeta(warehouse_product_id=product_id, images=[])
                db.add(meta)

            image_urls = []

            # 6. Копируем картинки из папки товара в публичную папку uploads/
            for img_file in folder_path.iterdir():
                if img_file.is_file() and img_file.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
                    # Генерируем уникальное имя, чтобы не было конфликтов
                    new_filename = f"{uuid.uuid4()}{img_file.suffix.lower()}"
                    dest_path = UPLOADS_DIR / new_filename

                    # Копируем файл
                    shutil.copy2(img_file, dest_path)

                    # Формируем URL
                    image_urls.append(f"/uploads/products/{new_filename}")

            if image_urls:
                meta.images = image_urls
                print(f"Успех: Загружено {len(image_urls)} фото для товара {internal_code} (ID: {product_id})")

        # 7. Сохраняем все изменения в базу PostgreSQL
        await db.commit()
        print("Импорт успешно завершен!")


if __name__ == "__main__":
    # Запускаем асинхронный скрипт
    asyncio.run(run_import())