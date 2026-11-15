from typing import Optional

from pydantic import BaseModel, Field
from decimal import Decimal


class CartItemAddSchema(BaseModel):
    product_id: int
    quantity: int = Field(..., gt=0, description="Количество должно быть больше нуля")
    price: Decimal


class CartItemResponseSchema(BaseModel):
    product_id: int
    quantity: int
    price: Decimal
    name: str | None = None
    image: str | None = None


class CartUpdateSchema(BaseModel):
    session_id: str
    product_id: int
    quantity: int = Field(..., gt=0)


class CartRemoveSchema(BaseModel):
    session_id: str
    product_id: int