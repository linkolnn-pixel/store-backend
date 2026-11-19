from openai import AsyncOpenAI

from core.config import settings
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


from models.product_embedding import ProductEmbedding
from schemas.rag import RecommendResponse

SYSTEM_PROMPT = """
Ты — AI-консультант интернет-магазина. Твоя задача — подобрать товары под запрос клиента.
ПРАВИЛА:
1. Рекомендуй ТОЛЬКО товары из предоставленного ниже контекста (раздел КАТАЛОГ).
2. Не выдумывай несуществующие товары, цены или характеристики.
3. Если подходящих товаров нет в контексте, честно скажи об этом и верни пустой список items.
4. Отвечай кратко, по делу и на русском языке.
"""


class ProductRAGService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL
        )
        self.embed_model = settings.EMBEDDING_MODEL
        self.chat_model = settings.CHAT_MODEL

    async def _get_embedding(self, text_value: str) -> list[float]:
        response = await self.client.embeddings.create(
            model=self.embed_model,
            input=text_value.replace("\n", " "),
        )
        return response.data[0].embedding

    async def reindex_catalog(self, catalog_items: list[dict]) -> int:
        indexed_count = 0
        for item in catalog_items:
            pid = item["id"]
            name = item.get("title") or item.get("name", "")
            price = item.get("sale_price") or item.get("price", 0)
            description = item.get("description") or "нет описания"

            content = (
                f"ID: {pid}. Название: {name}. "
                f"Бренд: {item.get('brand') or 'не указан'}. "
                f"Цена: {price} руб. "
                f"Описание: {description}."
            )
            vector = await self._get_embedding(content)

            stmt = (
                insert(ProductEmbedding)
                .values(product_id=pid, content=content, embedding=vector)
                .on_conflict_do_update(
                    index_elements=[ProductEmbedding.product_id],
                    set_={"content": content, "embedding": vector},
                )
            )
            await self.session.execute(stmt)
            indexed_count += 1

        await self.session.commit()
        return indexed_count

    async def recommend(self, query: str, in_stock_ids: list[int], limit: int = 5) -> RecommendResponse:
        """Выполняет семантический поиск в pgvector и генерирует ответ через LLM."""
        if not in_stock_ids:
            return RecommendResponse(
                answer="К сожалению, сейчас нет товаров в наличии.",
                items=[],
            )
        query_vector = await self._get_embedding(query)

        # Косинусное расстояние (<=>): чем меньше значение, тем выше релевантность.
        # Фильтруем только товары в наличии (stock > 0).
        stmt = (
            select(
                ProductEmbedding.content,
                ProductEmbedding.embedding.cosine_distance(query_vector).label("distance"),
            )
            .where(ProductEmbedding.product_id.in_(in_stock_ids))
            .order_by("distance")
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()

        # Отсекаем нерелевантные совпадения (порог косинусного расстояния)
        relevant_docs = [row.content for row in rows if row.distance < 0.65]

        if not relevant_docs:
            return RecommendResponse(
                answer="К сожалению, по вашему запросу не нашлось подходящих товаров в наличии.",
                items=[],
            )

        context_block = "\n".join(f"- {doc}" for doc in relevant_docs)

        completion = await self.client.beta.chat.completions.parse(
            model=self.chat_model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"КАТАЛОГ:\n{context_block}\n\nЗАПРОС КЛИЕНТА: {query}",
                },
            ],
            response_format=RecommendResponse,
        )

        return completion.choices[0].message.parsed