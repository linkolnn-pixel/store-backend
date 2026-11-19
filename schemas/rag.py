from pydantic import BaseModel, Field


class RecommendRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=500, examples=["Нужен увлажняющий крем для сухой кожи до 3000 рублей"])
    limit: int = Field(default=5, ge=1, le=10)


class RecommendedItem(BaseModel):
    product_id: int = Field(..., description="ID товара из переданного контекста")
    name: str = Field(..., description="Название товара")
    reason: str = Field(..., description="Почему этот товар подходит под запрос пользователя")


class RecommendResponse(BaseModel):
    answer: str = Field(..., description="Краткий дружелюбный ответ консультанта")
    items: list[RecommendedItem] = Field(
        default_factory=list,
        description="Список рекомендованных товаров строго из переданного контекста",
    )