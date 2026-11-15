# store-backend/schemas/validators.py
import re

def normalize_phone_number(v: str) -> str:
    """Универсальная функция очистки и валидации телефона"""
    cleaned = re.sub(r"[^\d+]", "", v)

    if cleaned.startswith("8") and len(cleaned) == 11:
        cleaned = "+7" + cleaned[1:]
    elif cleaned.startswith("9") and len(cleaned) == 10:
        cleaned = "+7" + cleaned
    elif cleaned.startswith("7") and len(cleaned) == 11:
        cleaned = "+" + cleaned

    if not re.fullmatch(r"\+7\d{10}", cleaned):
        raise ValueError("Введите телефон в формате +79999999999")

    return cleaned