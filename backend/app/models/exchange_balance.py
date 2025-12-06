"""Database model for exchange balances"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Numeric
from sqlalchemy.sql import func
from app.database import Base


class ExchangeBalance(Base):
    """Model for storing exchange balances from Crypto.com"""
    __tablename__ = "exchange_balances"
    
    id = Column(Integer, primary_key=True, index=True)
    asset = Column(String(20), nullable=False, index=True, unique=True)
    free = Column(Numeric(20, 8), nullable=False, default=0)
    locked = Column(Numeric(20, 8), nullable=False, default=0)
    total = Column(Numeric(20, 8), nullable=False, default=0)  # free + locked
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)
    
    def __repr__(self):
        return f"<ExchangeBalance(asset={self.asset}, free={self.free}, locked={self.locked})>"

