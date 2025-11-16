"""Database model for trade signals"""
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import ENUM
from app.database import Base
import enum


class PresetEnum(str, enum.Enum):
    """Trading preset types"""
    SWING = "swing"
    INTRADAY = "intraday"
    SCALP = "scalp"


class RiskProfileEnum(str, enum.Enum):
    """Risk profile types"""
    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"


class SignalStatusEnum(str, enum.Enum):
    """Signal status types"""
    PENDING = "pending"
    ORDER_PLACED = "order_placed"
    FILLED = "filled"
    CLOSED = "closed"
    ARCHIVED = "archived"


class TradeSignal(Base):
    """Model for storing trade signals (replaces Google Sheet)"""
    __tablename__ = "trade_signals"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    preset = Column(SQLEnum(PresetEnum, name="preset_enum"), nullable=False, default=PresetEnum.SWING)
    sl_profile = Column(SQLEnum(RiskProfileEnum, name="risk_profile_enum"), nullable=False, default=RiskProfileEnum.CONSERVATIVE)
    
    # Technical indicators
    rsi = Column(Float, nullable=True)
    ma50 = Column(Float, nullable=True)
    ma200 = Column(Float, nullable=True)
    ema10 = Column(Float, nullable=True)
    ma10w = Column(Float, nullable=True)  # Weekly MA
    atr = Column(Float, nullable=True)
    resistance_up = Column(Float, nullable=True)
    resistance_down = Column(Float, nullable=True)
    
    # Price fields
    entry_price = Column(Float, nullable=True)  # Price when signal was CREATED (never updated)
    current_price = Column(Float, nullable=True)  # Current/latest price (updated regularly)
    
    volume_24h = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)  # Current vs average volume
    
    # Signal status
    status = Column(SQLEnum(SignalStatusEnum, name="signal_status_enum"), default=SignalStatusEnum.PENDING, index=True)
    should_trade = Column(Boolean, default=False, index=True)
    
    # Exchange order tracking
    exchange_order_id = Column(String(100), nullable=True, index=True)
    
    # Timestamps
    last_update_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Additional metadata (for future use)
    notes = Column(Text, nullable=True)
    
    def __repr__(self):
        return f"<TradeSignal(symbol={self.symbol}, preset={self.preset}, status={self.status}, should_trade={self.should_trade})>"
