"""SL/TP reliability: no dual fallthrough, qty cap, reject retry gates."""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.exchange_sync import ExchangeSyncService
from app.services.sl_tp_protection import cap_protection_quantity_to_wallet


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    for table in Base.metadata.tables.values():
        try:
            table.create(bind=engine, checkfirst=True)
        except OperationalError as e:
            if "already exists" not in str(e).lower():
                raise
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_cap_protection_quantity_to_wallet_long():
    qty, reason = cap_protection_quantity_to_wallet("ALGO_USD", "BUY", 100.0, 14.5)
    assert qty == 14.5
    assert reason == "capped_to_wallet_balance"


def test_cap_protection_quantity_prefers_available_over_total():
    qty, reason = cap_protection_quantity_to_wallet(
        "DOGE_USD",
        "BUY",
        1000.0,
        wallet_balance=1000.0,
        wallet_available=0.0,
    )
    assert qty == 1000.0
    assert reason == "wallet_empty_long"


def test_cap_protection_quantity_uses_available_when_lower():
    qty, reason = cap_protection_quantity_to_wallet(
        "DOGE_USD",
        "BUY",
        500.0,
        wallet_balance=1000.0,
        wallet_available=120.0,
    )
    assert qty == 120.0
    assert reason == "capped_to_wallet_balance"


def test_cap_protection_quantity_skips_when_wallet_none():
    qty, reason = cap_protection_quantity_to_wallet("ALGO_USD", "BUY", 10.0, None)
    assert qty == 10.0
    assert reason is None


def test_spot_oco_fail_both_missing_refuses_dual(db_session, monkeypatch):
    monkeypatch.setenv("SLTP_NATIVE_OCO", "true")
    legacy = []

    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.ensure_spot_oco_protection",
        lambda **kwargs: {
            "sl_result": {"order_id": None, "error": "oco_failed"},
            "tp_result": {"order_id": None, "error": "oco_failed"},
            "oco_group_id": None,
            "error": "oco_failed",
        },
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_take_profit_order",
        lambda **kwargs: legacy.append("tp") or {"order_id": "x", "error": None},
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.create_stop_loss_order",
        lambda **kwargs: legacy.append("sl") or {"order_id": "y", "error": None},
    )
    monkeypatch.setattr(
        "app.services.tp_sl_order_creator.resolve_sltp_margin_context",
        lambda db, symbol: (False, None),
    )

    svc = ExchangeSyncService()
    result = svc._create_sl_tp_impl(
        db_session,
        symbol="ALGO_USD",
        side_upper="BUY",
        filled_price_f=0.25,
        filled_qty=14.0,
        order_id="parent-new",
        source="test",
        strict_percentages=False,
        sl_price_override_f=None,
        tp_price_override_f=None,
    )
    assert legacy == []
    assert result.get("error") == "oco_failed"
    assert not result["sl_result"].get("order_id")


def test_normalize_refuses_minqty_inflation(monkeypatch):
    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    client = CryptoComTradeClient()
    monkeypatch.setattr(
        client,
        "_get_instrument_metadata",
        lambda symbol: {
            "quantity_decimals": 0,
            "qty_tick_size": "1",
            "min_quantity": "10",
            "price_tick_size": "0.0001",
            "price_decimals": 4,
        },
    )
    # Zero after tick rounding — must not inflate to min_quantity (10).
    qty_str, diag = client.normalize_quantity_safe_with_fallback(
        "ALGO_USD", raw_quantity=0.4, for_sl_tp=True
    )
    assert qty_str is None
    assert "min_quantity_skipped" in str(diag.get("strategies_tried", [])) or diag.get(
        "final_reason"
    ) in ("below_minqty_cannot_inflate", "all_strategies_failed")


def test_retry_protection_after_reject_skips_old_parent(db_session):
    svc = ExchangeSyncService()
    old_parent = ExchangeOrder(
        exchange_order_id="old-parent",
        symbol="ALGO_USD",
        side=OrderSideEnum.BUY,
        order_type="MARKET",
        status=OrderStatusEnum.FILLED,
        price=Decimal("0.2"),
        quantity=Decimal("10"),
        cumulative_quantity=Decimal("10"),
        avg_price=Decimal("0.2"),
        exchange_update_time=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    prot = ExchangeOrder(
        exchange_order_id="sl-rej",
        symbol="ALGO_USD",
        side=OrderSideEnum.SELL,
        order_type="STOP_LIMIT",
        status=OrderStatusEnum.REJECTED,
        price=Decimal("0.19"),
        quantity=Decimal("10"),
        parent_order_id="old-parent",
        order_role="STOP_LOSS",
    )
    db_session.add(old_parent)
    db_session.add(prot)
    db_session.commit()

    with patch.object(svc, "_create_sl_tp_for_filled_order") as mock_create:
        svc._retry_protection_after_reject(
            db_session,
            protection_order=prot,
            reject_reason="INSUFFICIENT_ACC_BALANCE",
        )
        mock_create.assert_not_called()


def test_confirmed_fill_skips_wallet_side_mismatch(db_session, monkeypatch):
    """Margin / confirmed FILLED parent must not abort SL/TP with wallet_side_mismatch."""
    parent = ExchangeOrder(
        exchange_order_id="parent-margin",
        symbol="DOGE_USD",
        side=OrderSideEnum.BUY,
        order_type="MARKET",
        status=OrderStatusEnum.FILLED,
        price=Decimal("0.07"),
        quantity=Decimal("100"),
        cumulative_quantity=Decimal("100"),
        avg_price=Decimal("0.07"),
    )
    db_session.add(parent)
    from app.models.watchlist import WatchlistItem

    db_session.add(
        WatchlistItem(
            symbol="DOGE_USD",
            exchange="CRYPTO_COM",
            trade_enabled=True,
            trade_amount_usd=1.0,
            trade_on_margin=True,
        )
    )
    db_session.commit()

    svc = ExchangeSyncService()
    monkeypatch.setattr(
        "app.services.exchange_sync.trade_client.get_account_summary",
        lambda: {"accounts": [{"currency": "DOGE", "balance": "0"}]},
    )
    called = []

    def fake_impl(*args, **kwargs):
        called.append(True)
        return {"sl_result": {"order_id": "sl1"}, "tp_result": {"order_id": "tp1"}}

    monkeypatch.setattr(svc, "_create_sl_tp_impl", fake_impl)

    result = svc._create_sl_tp_for_filled_order(
        db=db_session,
        symbol="DOGE_USD",
        side="BUY",
        filled_price=0.07,
        filled_qty=100.0,
        order_id="parent-margin",
        source="test",
        skip_gate=True,
    )
    assert called == [True]
    assert result.get("status") != "wallet_side_mismatch"
