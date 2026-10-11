from pydantic import BaseModel, EmailStr, Field

class CheckoutRequest(BaseModel):
    session_id: str = Field(..., description="ID корзины из Redis")
    customer_name: str = Field(..., min_length=2, max_length=100)
    customer_phone: str = Field(..., min_length=10, max_length=20)
    customer_email: EmailStr | None = None