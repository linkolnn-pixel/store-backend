from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from models.base import Base


class ProductMeta(Base):
    __tablename__ = "product_meta"

    # ID товара со склада (используем как первичный ключ, чтобы связать базы)
    # Если на складе ID числовой, используйте Integer. Если строковый (UUID) - String
    warehouse_product_id = Column(Integer, primary_key=True, index=True)

    # Поля для витрины
    marketing_name = Column(String, nullable=True)  # Если захотим переименовать для сайта
    description = Column(Text, nullable=True)
    # Храним список URL картинок. По умолчанию пустой список []
    images = Column(JSONB, default=list, server_default='[]')