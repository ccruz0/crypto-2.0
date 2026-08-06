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


def test_algo_short_favorable_1pct_tp_clamped_below_last():
    """ALGO short: entry 0.0914, last 0.0901, 1% TP sits above last → clamp."""
    sl, tp, meta = compute_strategy_sl_tp_prices(
        entry_side="SELL",
        entry_price=0.0914,
        sl_pct=3.0,
        tp_pct=1.0,
        current_price=0.0901,
        buffer_pct=0.15,
    )
    assert meta["tp_adjusted"] is True
    assert meta["tp_reason"] == "market_already_below_tp"
    assert tp < 0.0901
    assert abs(tp - 0.0901 * (1 - 0.0015)) < 1e-6
    assert sl > 0.0914


def test_short_tp_valid_when_market_not_yet_at_target():
    """Favorable move but still above the TP target → keep entry-based TP."""
    sl, tp, meta = compute_strategy_sl_tp_prices(
        entry_side="SELL",
        entry_price=0.0914,
        sl_pct=3.0,
        tp_pct=3.0,
        current_price=0.0901,  # only ~1.4% down; TP target is 3%
        buffer_pct=0.15,
    )
    assert meta["tp_adjusted"] is False
    assert abs(tp - 0.0914 * 0.97) < 1e-9
    assert tp < 0.0901


def test_short_unfavorable_keeps_entry_tp_below_market():
    """Price rose against short — entry TP remains valid below market."""
    sl, tp, meta = compute_strategy_sl_tp_prices(
        entry_side="SELL",
        entry_price=0.0914,
        sl_pct=3.0,
        tp_pct=1.0,
        current_price=0.0925,
        buffer_pct=0.15,
    )
    assert meta["tp_adjusted"] is False
    assert abs(tp - 0.0914 * 0.99) < 1e-9
    assert tp < 0.0925
