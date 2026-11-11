from fastapi import APIRouter, HTTPException, Depends, Path, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import get_current_admin
from db.postgres import get_db_session
from schemas.product import ProductMetaUpdate
from services import catalog as catalog_service

router = APIRouter()


@router.get("/catalog/categories", summary="Получить список категорий со склада")
async def get_categories():
    try:
        return await catalog_service.fetch_categories()
    except catalog_service.WarehouseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/catalog", summary="Получить витрину (склад + PostgreSQL)")
async def get_catalog(db: AsyncSession = Depends(get_db_session)):
    try:
        return await catalog_service.get_full_catalog(db)
    except catalog_service.WarehouseUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except catalog_service.WarehouseAuthError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/catalog/{product_id}", summary="Получить детальную карточку товара")
async def get_product(
    product_id: int = Path(...),
    db: AsyncSession = Depends(get_db_session)
):
    try:
        return await catalog_service.get_product_detail(product_id, db)
    except catalog_service.ProductNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/catalog/{product_id}/meta", summary="Обновить описание, название и порядок фото")
async def update_product_meta(
        product_id: int,
        data: ProductMetaUpdate,
        db: AsyncSession = Depends(get_db_session),
        admin: str = Depends(get_current_admin)
):
    return await catalog_service.update_meta(product_id, data, db)


@router.post("/catalog/{product_id}/image", summary="Загрузить фото товара")
async def upload_product_image(
    product_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    admin: str = Depends(get_current_admin)
):
    try:
        return await catalog_service.save_product_image(product_id, file, db)
    except catalog_service.InvalidFileTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))