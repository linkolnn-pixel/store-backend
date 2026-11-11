import enum
from datetime import datetime, timezone
from decimal import Decimal
from typing import List

from sqlalchemy import ForeignKey, String, Numeric, DateTime, Enum, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    # Контактные данные пациента
    customer_name: Mapped[str] = mapped_column(String(100))
    customer_phone: Mapped[str] = mapped_column(String(20))
    customer_email: Mapped[str] = mapped_column(String(100), nullable=True)

    payment_id: Mapped[str] = mapped_column(String(100), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    items: Mapped[List["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))

    # ID товара или услуги из warehouse_project
    product_id: Mapped[int] = mapped_column(Integer, index=True)

    quantity: Mapped[int] = mapped_column(default=1)
    price_at_purchase: Mapped[Decimal] = mapped_column(Numeric(10, 2))

    order: Mapped["Order"] = relationship(back_populates="items")