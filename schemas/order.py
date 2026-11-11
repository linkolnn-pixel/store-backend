import re

from pydantic import BaseModel, EmailStr, Field, field_validator


class CheckoutRequest(BaseModel):
    session_id: str = Field(..., description="ID корзины из Redis")
    customer_name: str = Field(..., min_length=2, max_length=100)
    customer_phone: str = Field(..., min_length=10, max_length=20)
    customer_email: EmailStr | None = None

    @field_validator("customer_phone")
    @classmethod
    def validate_and_normalize_phone(cls, v: str) -> str:
        # 1. Очищаем от мусора
        cleaned = re.sub(r"[^\d+]", "", v)

        # 2. Приводим к формату +7
        if cleaned.startswith("8") and len(cleaned) == 11:
            cleaned = "+7" + cleaned[1:]
        elif cleaned.startswith("9") and len(cleaned) == 10:
            cleaned = "+7" + cleaned
        elif cleaned.startswith("7") and len(cleaned) == 11:
            cleaned = "+" + cleaned

        # 3. Жесткая проверка по регулярке
        if not re.fullmatch(r"\+7\d{10}", cleaned):
            raise ValueError("Введите телефон в формате +79999999999")

        return cleaned