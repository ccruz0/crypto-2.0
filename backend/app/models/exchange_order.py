"""Database model for exchange orders"""
from decimal import Decimal
from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, DateTime, Numeric, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import ENUM
from app.database import Base
import enum


class OrderSideEnum(str, enum.Enum):
    """Order side types"""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatusEnum(str, enum.Enum):
    """Order status types from Crypto.com"""
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class ExchangeOrder(Base):
    """Model for storing exchange orders from Crypto.com"""
    __tablename__ = "exchange_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    exchange_order_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    client_oid: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    side: Mapped[OrderSideEnum] = mapped_column(SQLEnum(OrderSideEnum, name="order_side_enum"), nullable=False)
    order_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # LIMIT, MARKET, etc.
    status: Mapped[OrderStatusEnum] = mapped_column(
        SQLEnum(OrderStatusEnum, name="order_status_enum"), nullable=False, default=OrderStatusEnum.NEW, index=True
    )

    # Price and quantity
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    cumulative_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True, default=0)
    cumulative_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True, default=0)
    avg_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    trigger_condition: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)

    # Timestamps from exchange
    exchange_create_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    exchange_update_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Local timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True
    )
    imported_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # Link to trade signal (optional)
    trade_signal_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # OCO (One-Cancels-Other) linking for SL/TP pairs
    parent_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    oco_group_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    order_role: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # When we sent Telegram "ORDER EXECUTED" for this order (avoids history-sync spam and duplicates)
    execution_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<ExchangeOrder(exchange_order_id={self.exchange_order_id}, symbol={self.symbol}, side={self.side}, status={self.status})>"
