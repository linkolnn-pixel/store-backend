from pydantic import BaseModel, EmailStr, Field, field_validator
from schemas.validators import normalize_phone_number

class CheckoutRequest(BaseModel):
    session_id: str = Field(..., description="ID корзины из Redis")
    customer_name: str = Field(..., min_length=2, max_length=100)
    customer_phone: str = Field(..., min_length=10, max_length=20)
    customer_email: EmailStr | None = None
    gift_certificate: str | None = Field(None, description="Код подарочного сертификата")
    comment: str | None = Field(None, description="Комментарий клиента к заказу")

    @field_validator("customer_phone")
    @classmethod
    def validate_and_normalize_phone(cls, v: str) -> str:
        # Просто вызываем общую функцию
        return normalize_phone_number(v)