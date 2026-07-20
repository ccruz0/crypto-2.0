"""Tests for the daily Position Review service (snooze / reopen / close)."""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.position_review_state import PositionReviewState
from app.services import position_review_service as prs
from app.services.margin_decision_helper import DEFAULT_CONFIGURED_LEVERAGE
from app.services.risk_config import MAX_LEVERAGE

EXPECTED_CLOSE_LEVERAGE = min(DEFAULT_CONFIGURED_LEVERAGE, MAX_LEVERAGE)  # capped by risk_guard


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[PositionReviewState.__table__])
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _pos(symbol, side, qty=10.0, mv=-20.0):
    return {
        "currency": symbol.split("_")[0], "symbol": symbol, "side": side,
        "qty": qty, "market_value": mv, "key": f"{symbol}:{side}",
    }


# --- snooze / reopen state machine -----------------------------------------
def test_new_position_is_alerted(db):
    alerted = prs.evaluate_positions(db, [_pos("DOT_USD", "SHORT")])
    assert [p["key"] for p in alerted] == ["DOT_USD:SHORT"]


def test_snoozed_position_is_skipped(db):
    pos = _pos("DOT_USD", "SHORT")
    prs.evaluate_positions(db, [pos])          # first run: alert + record qty
    prs.snooze_position(db, "DOT_USD:SHORT")   # operator taps "Keep 30 days"
    assert prs.evaluate_positions(db, [pos]) == []  # continuous + snoozed -> skip


def test_reopen_clears_snooze_and_alerts_again(db):
    pos = _pos("DOT_USD", "SHORT")
    prs.evaluate_positions(db, [pos])
    prs.snooze_position(db, "DOT_USD:SHORT")
    prs.evaluate_positions(db, [])             # position closed (absent)
    alerted = prs.evaluate_positions(db, [pos])  # reopened -> fresh case
    assert [p["key"] for p in alerted] == ["DOT_USD:SHORT"]


def test_closed_position_resets_state(db):
    prs.evaluate_positions(db, [_pos("DOT_USD", "SHORT")])
    prs.snooze_position(db, "DOT_USD:SHORT")
    prs.evaluate_positions(db, [])
    row = db.query(PositionReviewState).filter_by(position_key="DOT_USD:SHORT").first()
    assert float(row.last_seen_qty) == 0
    assert row.snoozed_until is None


def test_snooze_sets_future_until(db):
    until = prs.snooze_position(db, "BTC_USD:LONG")
    assert until > datetime.now(timezone.utc)


def test_second_position_unaffected_by_first_snooze(db):
    dot, sol = _pos("DOT_USD", "SHORT"), _pos("SOL_USD", "SHORT")
    prs.evaluate_positions(db, [dot, sol])
    prs.snooze_position(db, "DOT_USD:SHORT")
    alerted = prs.evaluate_positions(db, [dot, sol])
    assert [p["key"] for p in alerted] == ["SOL_USD:SHORT"]  # DOT snoozed, SOL still asks


# --- enumeration ------------------------------------------------------------
def test_enumerate_filters_fiat_and_dust(db):
    accounts = [
        {"currency": "USD", "quantity": "-135000", "market_value": "-135000"},   # fiat
        {"currency": "DOT", "quantity": "-22.4", "market_value": "-19.4"},        # short
        {"currency": "BTC", "quantity": "2.49", "market_value": "156000"},        # long
        {"currency": "STRK", "quantity": "-0.008", "market_value": "-0.0002"},    # dust
        {"currency": "ZERO", "quantity": "0", "market_value": "0"},               # flat
    ]
    with patch("app.services.brokers.crypto_com_trade.trade_client") as tc, \
         patch.object(prs, "_resolve_symbol", side_effect=lambda db, c: f"{c}_USD"):
        tc.get_account_summary.return_value = {"accounts": accounts}
        positions = prs.enumerate_open_positions(db)
    assert sorted(p["key"] for p in positions) == ["BTC_USD:LONG", "DOT_USD:SHORT"]


def test_enumerate_excludes_all_stablecoins_and_fiat(db):
    # No stablecoin or fiat balance (positive or negative) should ever be a "position".
    accounts = [{"currency": c, "quantity": "-1000", "market_value": "-1000"}
                for c in ("USDT", "USDC", "DAI", "FDUSD", "PYUSD", "TUSD", "EUR", "EURT", "GBP")]
    accounts.append({"currency": "BTC", "quantity": "1.0", "market_value": "60000"})
    with patch("app.services.brokers.crypto_com_trade.trade_client") as tc, \
         patch.object(prs, "_resolve_symbol", side_effect=lambda db, c: f"{c}_USD"):
        tc.get_account_summary.return_value = {"accounts": accounts}
        positions = prs.enumerate_open_positions(db)
    assert [p["key"] for p in positions] == ["BTC_USD:LONG"]  # only the crypto


# --- callback parsing / routing --------------------------------------------
def test_confirm_key_parse_roundtrip():
    cd = f"{prs.PREFIX_CONFIRM}DOT_USD:SHORT"
    key = cd[len(prs.PREFIX_CONFIRM):]
    assert key == "DOT_USD:SHORT"
    assert key.rsplit(":", 1) == ["DOT_USD", "SHORT"]


def test_dispatch_ignores_non_posrev():
    assert prs.dispatch_callback("1", "menu:portfolio", None) is False


def test_dispatch_snooze_routes_and_snoozes(db):
    with patch("app.services.telegram_notifier.telegram_notifier"):
        handled = prs.dispatch_callback("1", f"{prs.PREFIX_SNOOZE}DOT_USD:SHORT", db)
    assert handled is True
    row = db.query(PositionReviewState).filter_by(position_key="DOT_USD:SHORT").first()
    assert row is not None and row.snoozed_until is not None


# --- close execution --------------------------------------------------------
def test_execute_close_short_covers_with_margin_buy(db):
    accounts = [{"currency": "DOT", "quantity": "-11.32", "market_value": "-10.0"}]
    with patch("app.services.brokers.crypto_com_trade.trade_client") as tc:
        tc.get_account_summary.return_value = {"accounts": accounts}
        tc.place_market_order.return_value = {"order_id": "close-1"}
        result = prs.execute_close(db, "DOT_USD", "SHORT")
    assert result["order_id"] == "close-1"
    kwargs = tc.place_market_order.call_args.kwargs
    assert kwargs["side"] == "BUY"
    assert kwargs["is_margin"] is True
    # Margin orders REQUIRE leverage, but it must stay within the risk cap
    # (prod raised "Margin trade requires leverage" without it, then "Leverage 10 exceeds cap 5").
    assert kwargs["leverage"] == EXPECTED_CLOSE_LEVERAGE
    assert kwargs["leverage"] <= MAX_LEVERAGE
    assert kwargs["notional"] == pytest.approx(10.0)
    assert kwargs["dry_run"] is False


def test_execute_close_spot_long_sells_spot_without_leverage(db):
    # available ~= qty (spot holding) -> plain spot SELL, no leverage.
    accounts = [{"currency": "SUI", "quantity": "9.23135826591", "available": "9.23135826",
                 "market_value": "6.8"}]
    with patch("app.services.brokers.crypto_com_trade.trade_client") as tc:
        tc.get_account_summary.return_value = {"accounts": accounts}
        tc.place_market_order.return_value = {"order_id": "sell-1"}
        prs.execute_close(db, "SUI_USD", "LONG")
    kwargs = tc.place_market_order.call_args.kwargs
    assert kwargs["side"] == "SELL"
    assert kwargs["is_margin"] is False
    assert kwargs["leverage"] is None
    assert kwargs["qty"] == pytest.approx(9.23135826591)


def test_execute_close_margin_long_passes_leverage(db):
    # available << qty (base locked on margin) -> margin SELL WITH leverage.
    accounts = [{"currency": "BTC", "quantity": "2.0", "available": "0.1", "market_value": "120000"}]
    with patch("app.services.brokers.crypto_com_trade.trade_client") as tc:
        tc.get_account_summary.return_value = {"accounts": accounts}
        tc.place_market_order.return_value = {"order_id": "sell-2"}
        prs.execute_close(db, "BTC_USD", "LONG")
    kwargs = tc.place_market_order.call_args.kwargs
    assert kwargs["side"] == "SELL"
    assert kwargs["is_margin"] is True
    assert kwargs["leverage"] == EXPECTED_CLOSE_LEVERAGE
    assert kwargs["leverage"] <= MAX_LEVERAGE


def test_execute_close_flat_returns_error(db):
    with patch("app.services.brokers.crypto_com_trade.trade_client") as tc:
        tc.get_account_summary.return_value = {"accounts": []}
        result = prs.execute_close(db, "DOT_USD", "SHORT")
    assert result["error"] == "POSITION_NOT_FOUND"


# --- alert copy / keyboard (unprotected vs protected) ----------------------
def test_format_alert_unprotected_states_problem_and_options():
    text = prs._format_alert({
        **_pos("DOT_USD", "SHORT", qty=22.4, mv=-19.4),
        "has_sl": False,
        "has_tp": False,
    })
    assert "Problema" in text
    assert "sin SL y TP" in text
    assert "Crear un SL" in text
    assert "Crear un TP" in text
    assert "Cerrar la posición (comprar" in text
    assert "BUY" in text


def test_format_alert_long_close_says_sell():
    text = prs._format_alert({
        **_pos("BTC_USD", "LONG", qty=0.01, mv=600.0),
        "has_sl": True,
        "has_tp": False,
    })
    assert "sin TP" in text
    assert "Crear un TP" in text
    assert "Crear un SL" not in text
    assert "Cerrar la posición (vender" in text
    assert "SELL" in text


def test_format_alert_protected_keeps_simple_close_prompt():
    text = prs._format_alert({
        **_pos("ETH_USD", "LONG", qty=1.0, mv=2000.0),
        "has_sl": True,
        "has_tp": True,
    })
    assert "ya tiene SL y TP" in text
    assert "Problema" not in text
    assert "vender" in text


def test_alert_keyboard_unprotected_offers_sl_tp_and_close():
    kb = prs._alert_keyboard({
        **_pos("DOT_USD", "SHORT"),
        "has_sl": False,
        "has_tp": False,
    })
    flat = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    labels = [b["text"] for row in kb["inline_keyboard"] for b in row]
    assert "create_sl_DOT_USD" in flat
    assert "create_tp_DOT_USD" in flat
    assert "create_sl_tp_DOT_USD" in flat
    assert f"{prs.PREFIX_CLOSE}DOT_USD:SHORT" in flat
    assert any("Cerrar (comprar)" in t for t in labels)


def test_alert_keyboard_protected_only_close_and_snooze():
    kb = prs._alert_keyboard({
        **_pos("BTC_USD", "LONG", qty=1.0, mv=60000.0),
        "has_sl": True,
        "has_tp": True,
    })
    flat = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    assert flat == [
        f"{prs.PREFIX_CLOSE}BTC_USD:LONG",
        f"{prs.PREFIX_SNOOZE}BTC_USD:LONG",
    ]
    assert "create_sl_" not in "".join(flat)
