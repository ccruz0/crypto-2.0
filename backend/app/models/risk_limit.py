from sqlalchemy import Column, Integer, String, DateTime, Numeric, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.models.db import Base

class InstrumentRiskLimit(Base):
    __tablename__ = "instrument_risk_limits"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    instrument_id = Column(Integer, ForeignKey("instruments.id", ondelete="CASCADE"), unique=True, nullable=False)
    max_open_orders = Column(Integer, default=1)
    max_buy_usd = Column(Numeric(precision=18, scale=2), default=1000)
    allow_margin = Column(Boolean, default=False)
    max_leverage = Column(Numeric(precision=5, scale=2), default=1.0)
    preferred_exchange = Column(String, default="CRYPTO_COM")  # "BINANCE" or "CRYPTO_COM"
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
