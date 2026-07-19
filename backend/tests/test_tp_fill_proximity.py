"""Unit tests for TP fill-proximity (path progress entry → TP)."""

from app.services.expected_take_profit import tp_fill_proximity_pct


def test_long_at_entry_halfway_and_at_tp():
    assert tp_fill_proximity_pct(100, 100, 200) == 0.0
    assert tp_fill_proximity_pct(150, 100, 200) == 50.0
    assert tp_fill_proximity_pct(200, 100, 200) == 100.0
    assert tp_fill_proximity_pct(220, 100, 200) == 100.0


def test_long_underwater_btc_style_clamps_to_zero():
    # mark 64321, entry ~71100, TP 78000 → below entry → 0%
    assert tp_fill_proximity_pct(64321, 71100, 78000) == 0.0


def test_long_near_tp_approaches_100():
    prox = tp_fill_proximity_pct(77900, 71100, 78000)
    assert prox is not None
    assert prox > 95.0
    assert prox <= 100.0


def test_short_at_entry_halfway_and_at_tp():
    assert tp_fill_proximity_pct(200, 200, 100) == 0.0
    assert tp_fill_proximity_pct(150, 200, 100) == 50.0
    assert tp_fill_proximity_pct(100, 200, 100) == 100.0
    assert tp_fill_proximity_pct(90, 200, 100) == 100.0


def test_short_away_from_tp_clamps_to_zero():
    assert tp_fill_proximity_pct(250, 200, 100) == 0.0


def test_invalid_inputs_return_none():
    assert tp_fill_proximity_pct(None, 100, 200) is None
    assert tp_fill_proximity_pct(150, 0, 200) is None
    assert tp_fill_proximity_pct(150, 100, None) is None
