"""Append-only snapshot of the indicators behind an emitted signal.

Why this exists
---------------
Nothing in the system records WHAT the market looked like when a signal fired.
Orders keep price and quantity; ``watchlist_signal_state`` keys on ``symbol``
and is overwritten on every evaluation. So a question as basic as "which
indicator combination produced the entries that worked?" cannot be answered
from stored data — only guessed from today's values, which is worse than not
answering it.

Bounded on purpose
------------------
One row per EMITTED signal, never one per evaluation. The evaluation loop runs
every cycle across ~29 symbols; recording all of it would repeat the
portfolio_loans mistake (unbounded growth plus write amplification, issue #504).
Signals are rare — 36 alert-driven entries in two months — so this table grows
in the order of hundreds of rows per year.
"""

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String
from sqlalchemy.sql import func

from app.database import Base


class SignalIndicatorSnapshot(Base):
    """Indicators and condition flags at the moment a signal was emitted."""

    __tablename__ = "signal_indicator_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(50), nullable=False, index=True)
    side = Column(String(10), nullable=False)  # BUY / SELL
    emitted_at_utc = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Which ruleset produced it. Presets are edited in place with no audit
    # trail, so the key alone is not enough: keep the thresholds that were
    # actually applied.
    strategy_key = Column(String(100), nullable=True, index=True)
    rsi_buy_below = Column(Float, nullable=True)
    volume_min_ratio = Column(Float, nullable=True)

    # Market state at emission.
    price = Column(Float, nullable=True)
    rsi = Column(Float, nullable=True)
    ma200 = Column(Float, nullable=True)
    ma50 = Column(Float, nullable=True)
    ema10 = Column(Float, nullable=True)
    atr = Column(Float, nullable=True)
    volume_ratio = Column(Float, nullable=True)

    # The five flags should_trigger_buy_signal() computes. Storing them
    # separately from the raw indicators means a later change to the rules does
    # not rewrite history: the verdict is preserved as it was taken.
    rsi_ok = Column(Boolean, nullable=True)
    ma_ok = Column(Boolean, nullable=True)
    trend_filters_ok = Column(Boolean, nullable=True)
    rsi_confirmation_ok = Column(Boolean, nullable=True)
    candle_confirmation_ok = Column(Boolean, nullable=True)

    # Links to follow the outcome: correlation_id ties to the signal trace,
    # order_id to the fill, so time-to-close and result join without guessing.
    correlation_id = Column(String(100), nullable=True, index=True)
    order_id = Column(String(100), nullable=True, index=True)

    def __repr__(self) -> str:
        return (
            f"<SignalIndicatorSnapshot({self.symbol} {self.side} "
            f"rsi={self.rsi} at={self.emitted_at_utc})>"
        )
