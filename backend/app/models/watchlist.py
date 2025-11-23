from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, JSON, UniqueConstraint, text
from sqlalchemy.sql import func
from app.database import Base

class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False)
    exchange = Column(String, nullable=False)
    is_deleted = Column(
        Boolean,
        default=False,
        nullable=False,
        server_default=text("0")
    )  # Soft delete flag - only deleted entries are hidden
    
    # Unique constraint to prevent duplicates: one watchlist entry per (symbol, exchange) combination
    __table_args__ = (
        UniqueConstraint('symbol', 'exchange', name='uq_watchlist_symbol_exchange'),
    )
    buy_target = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    trade_enabled = Column(Boolean, default=False)
    trade_amount_usd = Column(Float, nullable=True)
    trade_on_margin = Column(Boolean, default=False)
    alert_enabled = Column(Boolean, default=False)  # Enable automatic alerts and order creation based on strategy
    sl_tp_mode = Column(String, default="conservative")  # 'conservative' or 'aggressive'
    min_price_change_pct = Column(Float, nullable=True)  # Minimum price change % required for order creation/alerts (default: 1.0)
    alert_cooldown_minutes = Column(Float, nullable=True)  # Cooldown in minutes between same-side alerts (default: 5.0)
    sl_percentage = Column(Float, nullable=True)  # Manual SL percentage (overrides calculated)
    tp_percentage = Column(Float, nullable=True)  # Manual TP percentage (overrides calculated)
    sl_price = Column(Float, nullable=True)  # Calculated SL price from strategy
    tp_price = Column(Float, nullable=True)  # Calculated TP price from strategy
    order_status = Column(String, default="PENDING")
    order_date = Column(DateTime, nullable=True)
    purchase_price = Column(Float, nullable=True)
    quantity = Column(Float, nullable=True)
    sold = Column(Boolean, default=False)
    sell_price = Column(Float, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    
    # Market data (updated regularly)
    price = Column(Float, nullable=True)
    rsi = Column(Float, nullable=True)
    atr = Column(Float, nullable=True)
    ma50 = Column(Float, nullable=True)
    ma200 = Column(Float, nullable=True)
    ema10 = Column(Float, nullable=True)
    res_up = Column(Float, nullable=True)
    res_down = Column(Float, nullable=True)
    signals = Column(JSON, nullable=True)  # {"buy": true/false, "sell": true/false}
    skip_sl_tp_reminder = Column(Boolean, default=False)  # Skip SL/TP reminder for this symbol

