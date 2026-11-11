import os
import shutil
import uuid
import httpx
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core.config import settings
from models.product_meta import ProductMeta
from schemas.product import ProductMetaUpdate


# --- Исключения ---
class WarehouseUnavailableError(Exception):
    pass


class WarehouseAuthError(Exception):
    pass


class ProductNotFoundError(Exception):
    pass


class InvalidFileTypeError(Exception):
    pass


UPLOAD_DIR = "uploads/images"
os.makedirs(UPLOAD_DIR, exist_ok=True)


async def fetch_categories() -> list | dict:
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            response = await client.get(f"{settings.WAREHOUSE_URL}/api/categories/")
            response.raise_for_status()
            categories_data = response.json()
            return categories_data.get("results", categories_data) if isinstance(categories_data,
                                                                                 dict) else categories_data
        except httpx.RequestError as e:
            print(f"Ошибка сети при запросе категорий: {e}")
            raise WarehouseUnavailableError("Склад временно недоступен")


async def get_full_catalog(db: AsyncSession) -> list:
    headers = {"X-Service-Token": settings.SERVICE_API_KEY}

    async with httpx.AsyncClient(headers=headers, timeout=5.0) as client:
        try:
            response = await client.get(f"{settings.WAREHOUSE_URL}/api/products/")
            response.raise_for_status()
            warehouse_data = response.json()
            products = warehouse_data.get("results", warehouse_data) if isinstance(warehouse_data,
                                                                                   dict) else warehouse_data
        except httpx.RequestError as e:
            print(f"Ошибка сети: {e}")
            raise WarehouseUnavailableError("Склад временно недоступен")
        except httpx.HTTPStatusError as e:
            print(f"Ошибка ответа Django: {e.response.status_code} {e.response.text}")
            raise WarehouseAuthError("Ошибка авторизации на складе")

    if not products:
        return []

    filtered_products = [p for p in products if "пакет" not in p.get("brand", "").lower()
                         and "dmk" not in p.get("brand", "").lower()]
    if not filtered_products:
        return []

    product_ids = [p["id"] for p in filtered_products]

    stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id.in_(product_ids))
    result = await db.execute(stmt)
    meta_records = result.scalars().all()
    meta_dict = {meta.warehouse_product_id: meta for meta in meta_records}

    for p in filtered_products:
        meta = meta_dict.get(p["id"])
        p["description"] = meta.description if meta and meta.description else ""
        if meta and meta.marketing_name:
            p["title"] = meta.marketing_name
        p["images"] = meta.images if meta and meta.images else []

    return filtered_products


async def get_product_detail(product_id: int, db: AsyncSession) -> dict:
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            response = await client.get(f"{settings.WAREHOUSE_URL}/api/products/{product_id}/")
            response.raise_for_status()
            p = response.json()
        except httpx.HTTPError:
            raise ProductNotFoundError("Товар не найден на складе")

    stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id == product_id)
    result = await db.execute(stmt)
    meta = result.scalar_one_or_none()

    p["description"] = meta.description if meta and meta.description else "Описание пока не добавлено."
    p["title"] = meta.marketing_name if meta and meta.marketing_name else p.get("name", "Без названия")
    p["images"] = meta.images if meta and meta.images else []

    if "sale_price" in p and "price" not in p:
        p["price"] = p["sale_price"]

    return p


async def update_meta(product_id: int, data: ProductMetaUpdate, db: AsyncSession) -> dict:
    stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id == product_id)
    result = await db.execute(stmt)
    meta = result.scalar_one_or_none()

    if not meta:
        meta = ProductMeta(warehouse_product_id=product_id, images=[])
        db.add(meta)

    if data.description is not None:
        meta.description = data.description
    if data.marketing_name is not None:
        meta.marketing_name = data.marketing_name

    if data.images is not None:
        old_images = set(meta.images) if meta.images else set()
        new_images = set(data.images)
        images_to_delete = old_images - new_images

        for image_url in images_to_delete:
            file_path = image_url.lstrip("/")
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Ошибка при удалении файла {file_path}: {e}")

        meta.images = list(data.images)

    await db.commit()
    await db.refresh(meta)

    return {
        "status": "success",
        "message": "Данные товара обновлены",
        "description": meta.description,
        "images": meta.images
    }


async def save_product_image(product_id: int, file: UploadFile, db: AsyncSession) -> dict:
    if not file.content_type.startswith("image/"):
        raise InvalidFileTypeError("Файл должен быть изображением")

    file_extension = file.filename.split(".")[-1]
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    image_url = f"/{UPLOAD_DIR}/{unique_filename}"

    stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id == product_id)
    result = await db.execute(stmt)
    meta = result.scalar_one_or_none()

    if not meta:
        meta = ProductMeta(warehouse_product_id=product_id, images=[])
        db.add(meta)

    current_images = list(meta.images) if meta.images else []
    current_images.append(image_url)
    meta.images = current_images

    await db.commit()
    await db.refresh(meta)

    return {
        "status": "success",
        "message": "Изображение успешно загружено",
        "uploaded_image": image_url,
        "all_images": meta.images
    }