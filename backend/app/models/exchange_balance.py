"""Database model for exchange balances"""
from decimal import Decimal
from datetime import datetime

from sqlalchemy import Integer, String, DateTime, Numeric
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ExchangeBalance(Base):
    """Model for storing exchange balances from Crypto.com"""
    __tablename__ = "exchange_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    asset: Mapped[str] = mapped_column(String(20), nullable=False, index=True, unique=True)
    free: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    locked: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False, default=0)  # free + locked
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )
    
    def __repr__(self):
        return f"<ExchangeBalance(asset={self.asset}, free={self.free}, locked={self.locked})>"

