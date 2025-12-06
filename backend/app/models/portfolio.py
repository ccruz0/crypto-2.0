"""Database model for portfolio balances"""
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Float
from sqlalchemy.sql import func
from app.database import Base


class PortfolioBalance(Base):
    """Model for storing portfolio balance snapshots"""
    __tablename__ = "portfolio_balances"
    
    id = Column(Integer, primary_key=True, index=True)
    currency = Column(String, nullable=False, index=True)
    balance = Column(Numeric(20, 8), nullable=False)
    usd_value = Column(Float, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<PortfolioBalance(currency={self.currency}, balance={self.balance}, usd_value={self.usd_value})>"


class PortfolioSnapshot(Base):
    """Model for storing total portfolio value snapshots"""
    __tablename__ = "portfolio_snapshots"
    
    id = Column(Integer, primary_key=True, index=True)
    total_usd = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f"<PortfolioSnapshot(total_usd={self.total_usd}, created_at={self.created_at})>"
