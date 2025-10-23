from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.models.db import Base

class Order(Base):
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    side = Column(String, nullable=False)  # "BUY" or "SELL"
    type = Column(String, nullable=False)  # "MARKET" or "LIMIT"
    price = Column(Numeric(precision=18, scale=8), nullable=False)
    qty = Column(Numeric(precision=18, scale=8), nullable=False)
    status = Column(String, nullable=False)  # "NEW", "FILLED", "REJECTED_LIMIT"
    exchange = Column(String, nullable=False)
    is_margin = Column(Boolean, default=False)
    leverage = Column(Numeric(precision=5, scale=2), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    filled_at = Column(DateTime(timezone=True), nullable=True)
