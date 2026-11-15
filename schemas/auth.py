# store-backend/schemas/auth.py
from pydantic import BaseModel, Field, field_validator
from schemas.validators import normalize_phone_number

class PhoneRequest(BaseModel):
    phone: str = Field(..., description="Номер телефона в формате +79991234567")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return normalize_phone_number(v)

class VerifyRequest(BaseModel):
    phone: str = Field(..., description="Номер телефона в формате +79991234567")
    code: str = Field(..., min_length=4, max_length=4, description="4-значный код из СМС")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return normalize_phone_number(v)