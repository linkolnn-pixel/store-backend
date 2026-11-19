from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


from api.dependencies import get_current_admin
from db.postgres import get_db_session
from schemas.rag import RecommendRequest, RecommendResponse
from services import catalog as catalog_service
from services.rag_service import ProductRAGService

router = APIRouter(prefix="/api/assistant", tags=["AI Assistant (RAG)"])


@router.post("/recommend", response_model=RecommendResponse)
async def recommend_products(
    payload: RecommendRequest,
    db: AsyncSession = Depends(get_db_session),
) -> RecommendResponse:
    try:
        catalog = await catalog_service.get_full_catalog(db)
    except (catalog_service.WarehouseUnavailableError, catalog_service.WarehouseAuthError) as e:
        raise HTTPException(status_code=503, detail=str(e))

    in_stock_ids = [
        item["id"] for item in catalog
        if item.get("stock", 1) > 0
    ]

    service = ProductRAGService(db)
    return await service.recommend(
        query=payload.query,
        in_stock_ids=in_stock_ids,
        limit=payload.limit,
    )


@router.post("/reindex")
async def reindex_products(
    db: AsyncSession = Depends(get_db_session),
    _admin: str = Depends(get_current_admin),
) -> dict[str, int | str]:
    try:
        catalog = await catalog_service.get_full_catalog(db)
    except (catalog_service.WarehouseUnavailableError, catalog_service.WarehouseAuthError) as e:
        raise HTTPException(status_code=503, detail=str(e))

    service = ProductRAGService(db)
    count = await service.reindex_catalog(catalog_items=catalog)
    return {"status": "ok", "indexed_products": count}