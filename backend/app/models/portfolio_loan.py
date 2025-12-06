"""Database model for portfolio loans/borrowed amounts"""
from sqlalchemy import Column, Integer, String, Numeric, DateTime, Float, Boolean
from sqlalchemy.sql import func
from app.database import Base


class PortfolioLoan(Base):
    """Model for storing borrowed/loan amounts"""
    __tablename__ = "portfolio_loans"
    
    id = Column(Integer, primary_key=True, index=True)
    currency = Column(String, nullable=False, index=True)
    borrowed_amount = Column(Numeric(20, 8), nullable=False, default=0)
    borrowed_usd_value = Column(Float, nullable=False, default=0)
    interest_rate = Column(Float, nullable=True)  # Annual interest rate (%)
    notes = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<PortfolioLoan(currency={self.currency}, borrowed_amount={self.borrowed_amount}, borrowed_usd_value=${self.borrowed_usd_value})>"

