from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.models.db import Base

class Position(Base):
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False)
    qty = Column(Numeric(precision=18, scale=8), nullable=False)
    avg_price = Column(Numeric(precision=18, scale=8), nullable=False)
    is_margin = Column(Boolean, default=False)
    leverage = Column(Numeric(precision=5, scale=2), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
