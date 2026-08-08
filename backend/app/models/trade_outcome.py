"""Database model for round-trip trade outcomes (Phase 1a learning labels)."""
from decimal import Decimal
from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, String, Text, DateTime, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class TradeOutcome(Base):
    """One closed (or attempted) round-trip attributed to an entry exchange order.

    Built offline by ``scripts/build_trade_outcomes.py`` from:
    telegram_messages ← order_intents ← exchange_orders (entry) ← SL/TP children.
    Phase 1b: labels feed Auto ML via
    ``scripts/build_auto_ml_dataset.py --label-source hybrid|trade_outcomes``.
    """

    __tablename__ = "trade_outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    telegram_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    order_intent_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    entry_exchange_order_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    exit_exchange_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    symbol: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)  # entry side BUY/SELL

    entry_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    exit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    pnl_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)
    pnl_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 8), nullable=True)

    exit_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    label: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    entry_ts: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    exit_ts: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    hold_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    join_status: Mapped[str] = mapped_column(String(32), nullable=False, default="COMPLETE")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="exchange_orders")
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Do NOT redeclare Index("ix_trade_outcomes_symbol") — symbol already has
    # index=True, and a duplicate name aborts Base.metadata.create_all on a fresh DB.
    __table_args__ = (
        UniqueConstraint("entry_exchange_order_id", name="uq_trade_outcomes_entry_exchange_order_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<TradeOutcome(entry={self.entry_exchange_order_id}, symbol={self.symbol}, "
            f"exit_reason={self.exit_reason}, label={self.label}, pnl_usd={self.pnl_usd})>"
        )
