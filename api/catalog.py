import httpx
from fastapi import APIRouter, HTTPException, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select


# Ваши импорты БД и модели
from db.postgres import get_db_session
from models.product_meta import ProductMeta

router = APIRouter()
WAREHOUSE_URL = "http://127.0.0.1:8001"


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