"""Issue #624: no live Telegram SELL SIGNAL when MA200 regime already blocks the short."""

import os
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.services.system_core_trade_guards as scg
from app.services.signal_monitor import SignalMonitorService
from app.utils.decision_reason import ReasonCode


def _market_db(*, symbol: str, ma200: float):
    eng = create_engine("sqlite:///:memory:")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE market_data (symbol TEXT, ma200 REAL, price REAL)"))
        c.execute(
            text("INSERT INTO market_data VALUES (:s, :m, :p)"),
            {"s": symbol, "m": ma200, "p": ma200 * 1.2},
        )
    return sessionmaker(bind=eng)()


def _margin_short_item(*, trade_enabled=True, trade_on_margin=True, trade_amount_usd=10.0):
    item = MagicMock()
    item.trade_enabled = trade_enabled
    item.trade_on_margin = trade_on_margin
    item.trade_amount_usd = trade_amount_usd
    return item


@pytest.fixture(autouse=True)
def _guards_on(monkeypatch):
    monkeypatch.setenv("SYSTEM_CORE_GUARDS_ENABLED", "true")
    monkeypatch.setattr(scg, "_GUARDS_ON", True)
    monkeypatch.setattr(scg, "_SHORT_REGIME_ON", True)
    monkeypatch.setattr(scg, "_LONG_BTC_REGIME_ON", False)
    monkeypatch.setattr(scg, "_daily_drawdown_violation", lambda db: (False, ""))
    monkeypatch.setattr(scg, "count_distinct_symbols_with_open_positions", lambda db: 0)
    from app.services import order_position_service

    monkeypatch.setattr(
        order_position_service, "count_open_short_positions_for_symbol", lambda db, b, **k: 0
    )
    monkeypatch.setattr(
        order_position_service, "wallet_has_material_short", lambda db, b, **k: False
    )


def test_would_regime_block_when_price_above_ma200():
    svc = SignalMonitorService()
    db = _market_db(symbol="BONK_USD", ma200=0.00001)
    item = _margin_short_item()
    with patch("app.services.risk_guard.shorting_enabled", return_value=True):
        with patch(
            "app.services.margin_info_service.instrument_allows_margin_short",
            return_value=True,
        ):
            blocked, reason = svc._would_regime_block_margin_short(
                db, "BONK_USD", 0.000012, item
            )
    assert blocked is True
    assert reason and "short_regime_price_above_ma200" in reason


def test_would_not_regime_block_when_price_below_ma200():
    svc = SignalMonitorService()
    db = _market_db(symbol="BONK_USD", ma200=0.00002)
    item = _margin_short_item()
    with patch("app.services.risk_guard.shorting_enabled", return_value=True):
        with patch(
            "app.services.margin_info_service.instrument_allows_margin_short",
            return_value=True,
        ):
            blocked, reason = svc._would_regime_block_margin_short(
                db, "BONK_USD", 0.00001, item
            )
    assert blocked is False
    assert reason is None


def test_would_not_regime_block_when_trade_disabled():
    svc = SignalMonitorService()
    db = _market_db(symbol="BONK_USD", ma200=0.00001)
    item = _margin_short_item(trade_enabled=False)
    blocked, reason = svc._would_regime_block_margin_short(
        db, "BONK_USD", 0.000012, item
    )
    assert blocked is False
    assert reason is None


def test_would_not_regime_block_for_non_margin_sell():
    svc = SignalMonitorService()
    db = _market_db(symbol="BONK_USD", ma200=0.00001)
    item = _margin_short_item(trade_on_margin=False)
    blocked, reason = svc._would_regime_block_margin_short(
        db, "BONK_USD", 0.000012, item
    )
    assert blocked is False
    assert reason is None


def test_persist_regime_filter_blocked_writes_db_not_live_telegram():
    svc = SignalMonitorService()
    db = MagicMock()
    reason = "short_regime_price_above_ma200 price=0.000012 ma200=0.00001"
    now = datetime.now(timezone.utc)

    with patch("app.api.routes_monitoring.add_telegram_message") as add_msg:
        with patch("app.services.telegram_notifier.telegram_notifier.send_message") as send_msg:
            with patch("app.services.telegram_notifier.telegram_notifier.send_sell_signal") as send_sell:
                with patch.object(svc, "_upsert_watchlist_signal_state") as upsert:
                    svc._persist_regime_filter_blocked_sell(
                        db,
                        symbol="BONK_USD",
                        normalized_symbol="BONK_USD",
                        reason=reason,
                        evaluation_id="eval-624",
                        current_price=0.000012,
                        now_utc=now,
                    )

    add_msg.assert_called_once()
    send_msg.assert_not_called()
    send_sell.assert_not_called()
    kwargs = add_msg.call_args.kwargs
    assert kwargs["reason_code"] == ReasonCode.REGIME_FILTER_BLOCKED.value
    assert kwargs["blocked"] is True
    assert kwargs["decision_type"] == "SKIPPED"
    assert "REGIME_FILTER_BLOCKED" in add_msg.call_args.args[0]
    assert "short_regime_price_above_ma200" in add_msg.call_args.args[0]
    upsert.assert_called_once()
    upsert_kwargs = upsert.call_args.kwargs
    assert upsert_kwargs["alert_block_reason"] == "REGIME_FILTER"
    assert upsert_kwargs["trade_block_reason"] == "REGIME_FILTER"


def test_add_telegram_message_persist_only_no_live_send():
    """add_telegram_message is DB/Monitoring only — must not page ATP Control."""
    from app.api.routes_monitoring import add_telegram_message

    db = MagicMock()
    db.execute.return_value = None
    db.flush.return_value = None
    db.query.return_value.filter.return_value.first.return_value = None

    with patch("app.services.telegram_notifier.telegram_notifier.send_message") as send_msg:
        with patch("app.services.telegram_notifier.telegram_notifier.send_sell_signal") as send_sell:
            add_telegram_message(
                "REGIME_FILTER_BLOCKED | BONK_USD SELL",
                symbol="BONK_USD",
                blocked=True,
                reason_code=ReasonCode.REGIME_FILTER_BLOCKED.value,
                db=db,
            )

    send_msg.assert_not_called()
    send_sell.assert_not_called()
    db.add.assert_called_once()


def test_suppress_order_failure_telegram_for_regime_filter():
    from app.services.trade_block_telegram_policy import suppress_order_failure_telegram

    err = "short_regime_price_above_ma200 price=0.09328 ma200=0.084435"
    assert (
        suppress_order_failure_telegram(err, reason_code=ReasonCode.REGIME_FILTER_BLOCKED.value)
        is True
    )


def test_real_exchange_error_still_pages_telegram():
    from app.services.trade_block_telegram_policy import suppress_order_failure_telegram

    assert (
        suppress_order_failure_telegram(
            "Insufficient funds for order",
            reason_code=ReasonCode.INSUFFICIENT_FUNDS.value,
        )
        is False
    )
