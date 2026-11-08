import os
import shutil
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Depends, Path, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from api.auth import get_current_admin
from db.postgres import get_db_session
from models.product_meta import ProductMeta
from schemas.product import ProductMetaUpdate

router = APIRouter()
WAREHOUSE_URL = "http://127.0.0.1:8001"


@router.get("/catalog/categories", summary="Получить список категорий со склада")
async def get_categories():
    # Идем на склад за категориями
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            response = await client.get(f"{WAREHOUSE_URL}/api/categories/")
            response.raise_for_status()
            categories_data = response.json()

            # Возвращаем чистый список категорий (учитываем пагинацию Django, если есть)
            categories = categories_data.get("results", categories_data) if isinstance(categories_data,
                                                                                       dict) else categories_data
            return categories

        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Склад временно недоступен")


@router.get("/catalog", summary="Получить витрину (склад + PostgreSQL)")
async def get_catalog(db: AsyncSession = Depends(get_db_session)):
    # 1. Асинхронно идем на склад за остатками и ценами
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            response = await client.get(f"{WAREHOUSE_URL}/api/products/")
            response.raise_for_status()
            warehouse_data = response.json()
            products = warehouse_data.get("results", warehouse_data) if isinstance(warehouse_data,
                                                                                   dict) else warehouse_data
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="Склад временно недоступен")

    if not products:
        return []

    filtered_products = [
        p for p in products
        if "пакет" not in p.get("name", "").lower()
    ]

    # Если после фильтрации ничего не осталось
    if not filtered_products:
        return []

    # 2. Собираем ID всех полученных товаров
    product_ids = [p["id"] for p in filtered_products]

    # 3. АСИНХРОННЫЙ запрос в наш PostgreSQL за описаниями
    stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id.in_(product_ids))
    result = await db.execute(stmt)
    meta_records = result.scalars().all()

    # Делаем словарик для быстрого поиска
    meta_dict = {meta.warehouse_product_id: meta for meta in meta_records}

    # 4. Cклеиваем данные
    for p in filtered_products:
        meta = meta_dict.get(p["id"])

        # Описание (если есть)
        p["description"] = meta.description if meta and meta.description else ""

        # Маркетинговое имя (если переопределено для витрины)
        if meta and meta.marketing_name:
            p["title"] = meta.marketing_name

            # Массив картинок. Если в базе пусто, отдаем пустой массив,
        # чтобы фронтенд мог безопасно сделать images.map()
        p["images"] = meta.images if meta and meta.images else []

    return filtered_products


@router.get("/catalog/{product_id}", summary="Получить детальную карточку товара")
async def get_product(
    product_id: int = Path(...),
    db: AsyncSession = Depends(get_db_session)
):
    # 1. Идем на склад за ценой и остатками
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            response = await client.get(f"{WAREHOUSE_URL}/api/products/{product_id}/")
            response.raise_for_status()
            p = response.json()
        except httpx.HTTPError:
            raise HTTPException(status_code=404, detail="Товар не найден на складе")

    # 2. Идем в нашу БД за картинками и описанием
    stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id == product_id)
    result = await db.execute(stmt)
    meta = result.scalar_one_or_none()

    # 3. Склеиваем
    p["description"] = meta.description if meta and meta.description else "Описание пока не добавлено."
    p["title"] = meta.marketing_name if meta and meta.marketing_name else p.get("name", "Без названия")
    p["images"] = meta.images if meta and meta.images else []

    # Фикс цены, если фронт ждет 'price'
    if "sale_price" in p and "price" not in p:
        p["price"] = p["sale_price"]

    return p


@router.patch("/catalog/{product_id}/meta", summary="Обновить описание, название и порядок фото")
async def update_product_meta(
        product_id: int,
        data: ProductMetaUpdate,
        db: AsyncSession = Depends(get_db_session),
        admin: str = Depends(get_current_admin)
):
    # 1. Ищем существующую запись
    stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id == product_id)
    result = await db.execute(stmt)
    meta = result.scalar_one_or_none()

    # 2. Если записи еще нет — создаем её
    if not meta:
        meta = ProductMeta(warehouse_product_id=product_id, images=[])
        db.add(meta)

    # 3. Обновляем только те поля, которые пришли в запросе
    if data.description is not None:
        meta.description = data.description

    if data.marketing_name is not None:
        meta.marketing_name = data.marketing_name

    if data.images is not None:
        # ==========================================
        # НОВАЯ ЛОГИКА: ФИЗИЧЕСКОЕ УДАЛЕНИЕ ФАЙЛОВ
        # ==========================================
        old_images = set(meta.images) if meta.images else set()
        new_images = set(data.images)

        # Находим картинки, которые были удалены пользователем (есть в старом, но нет в новом)
        images_to_delete = old_images - new_images

        for image_url in images_to_delete:
            # Ссылка имеет вид "/uploads/images/file.jpg".
            # Убираем первый слэш, чтобы получить локальный путь: "uploads/images/file.jpg"
            file_path = image_url.lstrip("/")

            try:
                # Проверяем, существует ли файл физически, и удаляем
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"Ошибка при удалении файла {file_path}: {e}")
        # ==========================================

        # Сохраняем новый массив в базу
        meta.images = list(data.images)

    # 4. Сохраняем в базу
    await db.commit()
    await db.refresh(meta)

    return {
        "status": "success",
        "message": "Данные товара обновлены",
        "description": meta.description,
        "images": meta.images
    }


# Папка, куда будут сохраняться картинки (создастся в корне проекта FastAPI)
UPLOAD_DIR = "uploads/images"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("/catalog/{product_id}/image", summary="Загрузить фото товара")
async def upload_product_image(
    product_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin)
):
    # 1. Проверяем, что загружен именно файл изображения
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Файл должен быть изображением")

    # 2. Генерируем уникальное имя файла, сохраняя оригинальное расширение
    file_extension = file.filename.split(".")[-1]
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)

    # 3. Сохраняем файл на диск
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 4. Формируем URL, по которому картинка будет доступна фронтенду
    image_url = f"/{UPLOAD_DIR}/{unique_filename}"

    # 5. Ищем запись товара в базе данных PostgreSQL
    stmt = select(ProductMeta).where(ProductMeta.warehouse_product_id == product_id)
    result = await db.execute(stmt)
    meta = result.scalar_one_or_none()

    # 6. Если записи нет — создаем её
    if not meta:
        meta = ProductMeta(warehouse_product_id=product_id, images=[])
        db.add(meta)

    # 7. Добавляем новый URL в массив images
    current_images = list(meta.images) if meta.images else []
    current_images.append(image_url)
    meta.images = current_images

    # 8. Сохраняем изменения в БД
    await db.commit()
    await db.refresh(meta)

    return {
        "status": "success",
        "message": "Изображение успешно загружено",
        "uploaded_image": image_url,
        "all_images": meta.images
    }


