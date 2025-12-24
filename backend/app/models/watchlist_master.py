"""WatchlistMaster model - source of truth for Watchlist UI data"""

from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, UniqueConstraint, text
from sqlalchemy.sql import func
from app.database import Base
import json
from datetime import datetime, timezone
from typing import Dict, Optional


class WatchlistMaster(Base):
    """Master table for watchlist data - single source of truth for UI.
    
    This table stores all watchlist fields with per-field timestamp tracking.
    All backend processes that update watchlist values must write to this table.
    """
    __tablename__ = "watchlist_master"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False)
    exchange = Column(String, nullable=False, default="CRYPTO_COM")
    is_deleted = Column(Boolean, default=False, nullable=False, server_default=text("0"))
    
    # Unique constraint
    __table_args__ = (
        UniqueConstraint('symbol', 'exchange', name='uq_watchlist_master_symbol_exchange'),
    )
    
    # User-configurable fields
    buy_target = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    trade_enabled = Column(Boolean, default=False)
    trade_amount_usd = Column(Float, nullable=True)
    trade_on_margin = Column(Boolean, default=False)
    alert_enabled = Column(Boolean, default=False)
    buy_alert_enabled = Column(Boolean, default=False)
    sell_alert_enabled = Column(Boolean, default=False)
    sl_tp_mode = Column(String, default="conservative")
    min_price_change_pct = Column(Float, nullable=True)
    alert_cooldown_minutes = Column(Float, nullable=True)
    sl_percentage = Column(Float, nullable=True)
    tp_percentage = Column(Float, nullable=True)
    sl_price = Column(Float, nullable=True)
    tp_price = Column(Float, nullable=True)
    notes = Column(String, nullable=True)
    signals = Column(Text, nullable=True)  # JSON string
    skip_sl_tp_reminder = Column(Boolean, default=False)
    
    # Market data fields (updated by background jobs)
    price = Column(Float, nullable=True)
    rsi = Column(Float, nullable=True)
    atr = Column(Float, nullable=True)
    ma50 = Column(Float, nullable=True)
    ma200 = Column(Float, nullable=True)
    ema10 = Column(Float, nullable=True)
    res_up = Column(Float, nullable=True)
    res_down = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)
    current_volume = Column(Float, nullable=True)
    avg_volume = Column(Float, nullable=True)
    volume_24h = Column(Float, nullable=True)
    
    # Order/position fields
    order_status = Column(String, default="PENDING")
    order_date = Column(DateTime, nullable=True)
    purchase_price = Column(Float, nullable=True)
    quantity = Column(Float, nullable=True)
    sold = Column(Boolean, default=False)
    sell_price = Column(Float, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Per-field update timestamps (stored as JSON string)
    # Format: {"price": "2024-01-01T12:00:00Z", "rsi": "2024-01-01T12:01:00Z", ...}
    field_updated_at = Column(Text, nullable=True)
    
    def get_field_updated_at(self) -> Dict[str, str]:
        """Get field update timestamps as a dictionary."""
        if not self.field_updated_at:
            return {}
        try:
            return json.loads(self.field_updated_at)
        except (json.JSONDecodeError, TypeError):
            return {}
    
    def set_field_updated_at(self, field_name: str, timestamp: Optional[datetime] = None):
        """Update the timestamp for a specific field.
        
        Args:
            field_name: Name of the field that was updated
            timestamp: Optional datetime (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        timestamps = self.get_field_updated_at()
        timestamps[field_name] = timestamp.isoformat()
        self.field_updated_at = json.dumps(timestamps)
        self.updated_at = timestamp
    
    def get_field_last_updated(self, field_name: str) -> Optional[datetime]:
        """Get the last update timestamp for a specific field.
        
        Args:
            field_name: Name of the field
            
        Returns:
            datetime if found, None otherwise
        """
        timestamps = self.get_field_updated_at()
        timestamp_str = timestamps.get(field_name)
        if not timestamp_str:
            return None
        
        try:
            # Parse ISO format timestamp
            if timestamp_str.endswith('Z'):
                timestamp_str = timestamp_str[:-1] + '+00:00'
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None
    
    def update_field(self, field_name: str, value: any, timestamp: Optional[datetime] = None):
        """Update a field and its timestamp atomically.
        
        Args:
            field_name: Name of the field to update
            value: New value for the field
            timestamp: Optional datetime (defaults to now)
        """
        if hasattr(self, field_name):
            setattr(self, field_name, value)
            self.set_field_updated_at(field_name, timestamp)
        else:
            raise ValueError(f"Field '{field_name}' does not exist on WatchlistMaster")

