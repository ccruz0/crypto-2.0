"""Unit tests for SL/TP strategy price adjustment."""
from app.services.sl_tp_price_adjust import compute_strategy_sl_tp_prices


def test_long_normal_levels():
    sl, tp, meta = compute_strategy_sl_tp_prices(
        entry_side="BUY",
        entry_price=100.0,
        sl_pct=10.0,
        tp_pct=1.0,
        current_price=100.0,
    )
    assert sl == 90.0
    assert tp == 101.0
    assert meta["sl_adjusted"] is False
    assert meta["tp_adjusted"] is False


def test_long_tp_already_passed_places_above_market():
    sl, tp, meta = compute_strategy_sl_tp_prices(
        entry_side="BUY",
        entry_price=100.0,
        sl_pct=10.0,
        tp_pct=1.0,
        current_price=105.0,  # already above TP 101
        buffer_pct=0.15,
    )
    assert sl == 90.0
    assert meta["tp_adjusted"] is True
    assert tp > 105.0
    assert abs(tp - 105.0 * 1.0015) < 0.01


def test_long_sl_already_passed_places_below_market():
    sl, tp, meta = compute_strategy_sl_tp_prices(
        entry_side="BUY",
        entry_price=100.0,
        sl_pct=10.0,
        tp_pct=1.0,
        current_price=85.0,  # already below SL 90
        buffer_pct=0.15,
    )
    assert tp == 101.0
    assert meta["sl_adjusted"] is True
    assert sl < 85.0
