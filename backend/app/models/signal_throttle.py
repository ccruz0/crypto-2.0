from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Boolean,
    UniqueConstraint,
    Index,
)
from sqlalchemy.sql import func

from app.database import Base


class SignalThrottleState(Base):
    """Stores last emitted signal per (symbol, strategy, side) for throttling."""

    __tablename__ = "signal_throttle_states"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    strategy_key = Column(String(100), nullable=False, index=True)
    side = Column(String(10), nullable=False, index=True)  # BUY / SELL / INDEX
    last_price = Column(Float, nullable=True)
    previous_price = Column(Float, nullable=True)  # Price from previous signal event
    last_time = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_source = Column(String(20), nullable=True)  # alert / order
    force_next_signal = Column(Boolean, default=False, nullable=False, server_default=func.false())  # Force bypass throttle on next evaluation

    __table_args__ = (
        UniqueConstraint("symbol", "strategy_key", "side", name="uq_signal_throttle_state"),
        Index("ix_signal_throttle_symbol_strategy", "symbol", "strategy_key"),
    )

    def __repr__(self) -> str:
        return (
            f"<SignalThrottleState(symbol={self.symbol}, strategy={self.strategy_key}, "
            f"side={self.side}, price={self.last_price}, time={self.last_time})>"
        )
