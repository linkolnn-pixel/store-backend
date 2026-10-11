from pydantic import BaseModel, Field
from typing import List

class CartItemSchema(BaseModel):
    product_id: str = Field(..., description="ID товара из склада")
    quantity: int = Field(..., gt=0, description="Количество (строго больше 0)")
    price: float = Field(..., ge=0, description="Цена за единицу")

class CartSchema(BaseModel):
    session_id: str
    items: List[CartItemSchema]
    total: float = Field(..., ge=0)

class CartUpdateSchema(BaseModel):
    session_id: str
    product_id: str
    quantity: int

class CartRemoveSchema(BaseModel):
    session_id: str
    product_id: str
