import datetime
import enum

from sqlalchemy import Column, Integer, String, JSON, DateTime, Boolean
from .base import Base

class OutboxStatus(str, enum.Enum):
    PENDING = "PENDING"
    WAITING_FOR_PAYMENT = "WAITING_FOR_PAYMENT"
    PROCESSED = "PROCESSED"
    ERROR = "ERROR"

class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String, index=True)
    payload = Column(JSON)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    processed = Column(Boolean, default=False, index=True)
    status = Column(String, default=OutboxStatus.PENDING.value, index=True)
    error_message = Column(String, nullable=True)