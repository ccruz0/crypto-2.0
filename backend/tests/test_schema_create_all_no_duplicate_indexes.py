"""Regression: OrderIntent/TradeOutcome create_all must not abort on duplicate index names."""
from __future__ import annotations

import os
import tempfile
import uuid

from sqlalchemy import create_engine, inspect


def test_order_intent_and_trade_outcome_create_all_without_duplicate_index_abort():
    """Fresh SQLite create_all must succeed without dedupe workarounds.

    Previously signal_id/symbol had both Column(index=True) and an explicit
    Index(...) with the same name, which aborted create_all on empty DBs.
    """
    from app.database import Base
    from app.models.order_intent import OrderIntent  # noqa: F401 — register metadata
    from app.models.trade_outcome import TradeOutcome  # noqa: F401 — register metadata

    db_path = os.path.join(tempfile.gettempdir(), f"test_schema_create_{uuid.uuid4().hex}.db")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    try:
        # Must not raise DuplicateTable / OperationalError on index names
        Base.metadata.create_all(
            bind=engine,
            tables=[OrderIntent.__table__, TradeOutcome.__table__],
        )
        insp = inspect(engine)
        assert insp.has_table("order_intents")
        assert insp.has_table("trade_outcomes")

        oi_index_names = {idx["name"] for idx in insp.get_indexes("order_intents")}
        to_index_names = {idx["name"] for idx in insp.get_indexes("trade_outcomes")}
        # Column(index=True) still creates these single-column indexes once
        assert "ix_order_intents_signal_id" in oi_index_names
        assert "ix_trade_outcomes_symbol" in to_index_names
        # Composite index from __table_args__ remains
        assert "ix_order_intents_symbol_side" in oi_index_names
    finally:
        engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(f"{db_path}{suffix}")
            except OSError:
                pass
