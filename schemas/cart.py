from pydantic import BaseModel, Field, EmailStr
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
    type: str | None = "product"


class CartUpdateSchema(BaseModel):
    session_id: str
    product_id: int | str
    quantity: int = Field(..., gt=0)


class CartRemoveSchema(BaseModel):
    session_id: str
    product_id: int | str


class CertificateAddRequest(BaseModel):
    price: int
    recipient_email: EmailStr
    sender_name: str | None = None
    message: str | None = None
    quantity: int = 1