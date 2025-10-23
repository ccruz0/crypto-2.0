from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey
from sqlalchemy.sql import func
from app.models.db import Base

class Instrument(Base):
    __tablename__ = "instruments"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    symbol = Column(String, nullable=False)
    venue = Column(String, nullable=False)  # "CRYPTO" or "STOCK"
    tick_size = Column(Numeric(precision=18, scale=8), nullable=True)
    lot_size = Column(Numeric(precision=18, scale=8), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
