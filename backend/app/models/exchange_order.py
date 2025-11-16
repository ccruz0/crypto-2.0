"""Database model for exchange orders"""
from sqlalchemy import Column, Integer, String, Float, DateTime, Numeric, Enum as SQLEnum
from sqlalchemy.sql import func
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


class ExchangeOrder(Base):
    """Model for storing exchange orders from Crypto.com"""
    __tablename__ = "exchange_orders"
    
    id = Column(Integer, primary_key=True, index=True)
    exchange_order_id = Column(String(100), nullable=False, unique=True, index=True)
    client_oid = Column(String(100), nullable=True, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    side = Column(SQLEnum(OrderSideEnum, name="order_side_enum"), nullable=False)
    order_type = Column(String(20), nullable=True)  # LIMIT, MARKET, etc.
    status = Column(SQLEnum(OrderStatusEnum, name="order_status_enum"), nullable=False, default=OrderStatusEnum.NEW, index=True)
    
    # Price and quantity
    price = Column(Numeric(20, 8), nullable=True)
    quantity = Column(Numeric(20, 8), nullable=False)
    cumulative_quantity = Column(Numeric(20, 8), nullable=True, default=0)
    cumulative_value = Column(Numeric(20, 8), nullable=True, default=0)
    avg_price = Column(Numeric(20, 8), nullable=True)
    trigger_condition = Column(Numeric(20, 8), nullable=True)  # Trigger condition for stop/limit orders
    
    # Timestamps from exchange
    exchange_create_time = Column(DateTime(timezone=True), nullable=True)
    exchange_update_time = Column(DateTime(timezone=True), nullable=True)
    
    # Local timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)
    imported_at = Column(DateTime(timezone=True), nullable=True, index=True)  # Timestamp when order was imported from CSV
    
    # Link to trade signal (optional)
    trade_signal_id = Column(Integer, nullable=True, index=True)
    
    # OCO (One-Cancels-Other) linking for SL/TP pairs
    parent_order_id = Column(String(100), nullable=True, index=True)  # Parent order that triggered SL/TP creation
    oco_group_id = Column(String(100), nullable=True, index=True)  # Group ID to link SL and TP orders together
    order_role = Column(String(20), nullable=True)  # PARENT, STOP_LOSS, TAKE_PROFIT
    
    def __repr__(self):
        return f"<ExchangeOrder(exchange_order_id={self.exchange_order_id}, symbol={self.symbol}, side={self.side}, status={self.status})>"
