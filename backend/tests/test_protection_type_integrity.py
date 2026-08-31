"""#521: fake STOP_LOSS rows (exchange holds plain LIMIT) must not count as protected."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services import sl_tp_checker as checker
from app.services.dashboard_position_counts import compute_protection_leg_stats
from app.services.position_review_service import _get_protection_status
from app.services.sl_tp_protection import (
    order_counts_as_protection,
    protection_type_matches_role,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[ExchangeOrder.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _order(
    db,
    oid: str,
    *,
    order_type: str = "LIMIT",
    order_role: str | None = None,
    side=OrderSideEnum.BUY,
    status=OrderStatusEnum.ACTIVE,
    symbol: str = "ETH_USD",
    qty: float = 0.0006,
    parent: str | None = None,
):
    row = ExchangeOrder(
        exchange_order_id=oid,
        symbol=symbol,
        side=side,
        order_type=order_type,
        order_role=order_role,
        status=status,
        price=2048.72,
        quantity=qty,
        parent_order_id=parent,
    )
    db.add(row)
    db.commit()
    return row


def test_stop_loss_limit_role_mismatch_does_not_count():
    assert protection_type_matches_role("STOP_LOSS", "LIMIT") is False
    assert order_counts_as_protection(
        role="STOP_LOSS", order_role="STOP_LOSS", order_type="LIMIT"
    ) is False


def test_real_stop_limit_still_counts():
    assert order_counts_as_protection(
        role="STOP_LOSS", order_role="STOP_LOSS", order_type="STOP_LIMIT"
    ) is True


def test_classify_open_leg_ignores_fake_stop_role():
    fake = {
        "order_id": "73817490102074667",
        "order_type": "LIMIT",
        "order_role": "STOP_LOSS",
        "side": "BUY",
    }
    real = {
        "order_id": "sl-real",
        "order_type": "STOP_LIMIT",
        "order_role": "STOP_LOSS",
        "side": "BUY",
    }
    assert checker._classify_open_protection_leg(fake) is None
    assert checker._classify_open_protection_leg(real) == "SL"


def test_db_active_protection_qty_excludes_fake_stop(db):
    _order(
        db,
        "73817490102074667",
        order_type="LIMIT",
        order_role="STOP_LOSS",
        side=OrderSideEnum.BUY,
        parent="5755600492576908808",
    )
    qty = checker._db_active_protection_qty(db, ["ETH_USD"], "STOP_LOSS")
    assert qty == 0.0


def test_db_active_protection_qty_includes_real_stop(db):
    _order(
        db,
        "sl-real",
        order_type="STOP_LIMIT",
        order_role="STOP_LOSS",
        side=OrderSideEnum.BUY,
        qty=0.004,
    )
    qty = checker._db_active_protection_qty(db, ["ETH_USD"], "STOP_LOSS")
    assert qty == 0.004


def test_position_review_db_fallback_not_protected_for_fake_stop(db, monkeypatch):
    _order(
        db,
        "73817490102074667",
        order_type="LIMIT",
        order_role="STOP_LOSS",
        side=OrderSideEnum.BUY,
    )
    monkeypatch.setattr(
        "app.services.unified_open_orders_fetch.fetch_unified_open_orders",
        lambda *a, **k: {"all_raw_orders": [], "data": [], "data_verified": True},
    )
    status = _get_protection_status(db, "ETH_USD")
    assert status["has_sl"] is False


def test_dashboard_protection_leg_stats_ignore_fake_stop():
    from types import SimpleNamespace

    fake = SimpleNamespace(
        order_type="LIMIT",
        order_role="STOP_LOSS",
        status="ACTIVE",
        base_symbol="ETH",
        symbol="ETH_USD",
        quantity=0.0006,
        order_id="73817490102074667",
        side="BUY",
    )
    tp_counts, protective, _alerts = compute_protection_leg_stats(
        [fake], [{"currency": "ETH", "balance": -0.00471327}]
    )
    assert tp_counts.get("ETH", 0) == 0
    assert protective.get("ETH", 0) == 0


def test_exchange_sync_reconciles_order_type_from_exchange(db, monkeypatch):
    from app.models.trade_signal import TradeSignal
    from app.services.exchange_sync import ExchangeSyncService

    real_query = db.query

    def patched_query(*entities, **kwargs):
        if entities and entities[0] is TradeSignal:
            mock = MagicMock()
            mock.filter.return_value.first.return_value = None
            return mock
        return real_query(*entities, **kwargs)

    monkeypatch.setattr(db, "query", patched_query)

    existing = _order(
        db,
        "73817490102074667",
        order_type="STOP_LIMIT",
        order_role="STOP_LOSS",
        side=OrderSideEnum.BUY,
    )
    svc = ExchangeSyncService()
    payload = {
        "orders": [],
        "all_raw_orders": [
            {
                "order_id": existing.exchange_order_id,
                "instrument_name": "ETH_USD",
                "side": "BUY",
                "status": "ACTIVE",
                "order_type": "LIMIT",
                "quantity": "0.0006",
                "limit_price": "2048.72",
                "create_time": 1700000000000,
                "update_time": 1700000001000,
            }
        ],
        "regular_raw": [],
        "trigger_raw": [],
        "sync_status": "ok",
        "data_verified": True,
    }
    with patch(
        "app.services.unified_open_orders_fetch.fetch_unified_open_orders",
        return_value=payload,
    ), patch("app.services.exchange_sync.update_open_orders_cache"), patch(
        "app.services.open_orders_sync_status.record_open_orders_sync_success"
    ), patch.object(svc, "_reconcile_misclassified_protection_fills", return_value=0), patch.object(
        svc, "_sweep_orphaned_oco_siblings", return_value=0
    ):
        svc.sync_open_orders(db)

    db.refresh(existing)
    assert existing.order_type == "LIMIT"
    assert existing.order_role == "STOP_LOSS"
    assert (
        order_counts_as_protection(
            role="STOP_LOSS",
            order_role=existing.order_role,
            order_type=existing.order_type,
        )
        is False
    )
