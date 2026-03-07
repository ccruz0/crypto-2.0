"""Database model for trade signals"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Float, Boolean, DateTime, Text, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, mapped_column
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    preset: Mapped[PresetEnum] = mapped_column(
        SQLEnum(PresetEnum, name="preset_enum"), nullable=False, default=PresetEnum.SWING
    )
    sl_profile: Mapped[RiskProfileEnum] = mapped_column(
        SQLEnum(RiskProfileEnum, name="risk_profile_enum"), nullable=False, default=RiskProfileEnum.CONSERVATIVE
    )

    # Technical indicators
    rsi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ma50: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ma200: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ema10: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ma10w: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Weekly MA
    atr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    resistance_up: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    resistance_down: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Price fields
    entry_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    volume_24h: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Signal status
    status: Mapped[SignalStatusEnum] = mapped_column(
        SQLEnum(SignalStatusEnum, name="signal_status_enum"), default=SignalStatusEnum.PENDING, index=True
    )
    should_trade: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Exchange order tracking
    exchange_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Timestamps
    last_update_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Additional metadata (for future use)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    def __repr__(self):
        return f"<TradeSignal(symbol={self.symbol}, preset={self.preset}, status={self.status}, should_trade={self.should_trade})>"
