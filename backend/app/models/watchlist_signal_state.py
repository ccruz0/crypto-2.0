from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Index,
)
from sqlalchemy.sql import func

from app.database import Base


class WatchlistSignalState(Base):
    """Stores per-symbol signal/alert/trade state for watchlist items."""

    __tablename__ = "watchlist_signal_states"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False, unique=True, index=True)
    strategy_key = Column(String(100), nullable=True)
    signal_side = Column(String(10), nullable=True, default="NONE")  # BUY / SELL / NONE
    last_price = Column(Float, nullable=True)
    evaluated_at_utc = Column(DateTime(timezone=True), nullable=True)
    alert_status = Column(String(20), nullable=True, default="NONE")  # SENT / BLOCKED / NONE
    alert_block_reason = Column(String(500), nullable=True)
    last_alert_at_utc = Column(DateTime(timezone=True), nullable=True)
    trade_status = Column(String(20), nullable=True, default="NONE")  # SUBMITTED / BLOCKED / NONE
    trade_block_reason = Column(String(500), nullable=True)
    last_trade_at_utc = Column(DateTime(timezone=True), nullable=True)
    correlation_id = Column(String(100), nullable=True)

    __table_args__ = (
        Index("ix_watchlist_signal_states_symbol", "symbol"),
    )

    def __repr__(self) -> str:
        return (
            f"<WatchlistSignalState(symbol={self.symbol}, signal_side={self.signal_side}, "
            f"alert_status={self.alert_status}, trade_status={self.trade_status})>"
        )
