from pydantic import BaseModel


class PromoValidationResult(BaseModel):
    is_valid: bool
    code: str | None = None
    discount_type: str | None = None
    discount_value: float | None = None
    min_order_amount: float | None = None
    message: str | None = None

class PromoApplyRequest(BaseModel):
    promo_code: str