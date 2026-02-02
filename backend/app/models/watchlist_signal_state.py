"""Model for watchlist_signal_state table (AWS DB schema)."""
from sqlalchemy import Column, DateTime, Float, String
from sqlalchemy.sql import func

from app.database import Base


class WatchlistSignalState(Base):
    """Stores per-symbol signal/alert/trade state for watchlist items."""

    # Align with existing AWS DB table (watchlist_signal_state, symbol as PK)
    __tablename__ = "watchlist_signal_state"

    symbol = Column(String(50), primary_key=True)
    strategy_key = Column(String(100), nullable=True)
    signal_side = Column(String(10), nullable=False, default="NONE", server_default="NONE")  # BUY / SELL / NONE
    last_price = Column(Float, nullable=True)
    evaluated_at_utc = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    alert_status = Column(String(20), nullable=True, default="NONE")  # SENT / BLOCKED / NONE
    alert_block_reason = Column(String(500), nullable=True)
    last_alert_at_utc = Column(DateTime(timezone=True), nullable=True)
    trade_status = Column(String(20), nullable=True, default="NONE")  # SUBMITTED / BLOCKED / NONE
    trade_block_reason = Column(String(500), nullable=True)
    last_trade_at_utc = Column(DateTime(timezone=True), nullable=True)
    correlation_id = Column(String(100), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<WatchlistSignalState(symbol={self.symbol}, signal_side={self.signal_side}, "
            f"alert_status={self.alert_status}, trade_status={self.trade_status})>"
        )
