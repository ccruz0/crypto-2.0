"""Phase 2 Auto ML SL/TP offline learning tests (#623)."""

from __future__ import annotations

from app.services.auto_sltp_learn import (
    evaluate_sltp_pair,
    normalize_outcome_row,
    simulate_bracket_pnl,
    walk_forward_learn,
)


def _outcome(side: str, entry: float, exit_p: float, reason: str, i: int) -> dict:
    return {
        "join_status": "COMPLETE",
        "side": side,
        "entry_price": entry,
        "exit_price": exit_p,
        "exit_reason": reason,
        "entry_ts": f"2026-01-{1 + (i % 28):02d}T12:00:00+00:00",
        "entry_exchange_order_id": f"oid-{i}",
    }


def test_simulate_bracket_pnl_long_tp_hit():
    pnl = simulate_bracket_pnl(
        side="BUY", entry_price=100.0, exit_price=104.0, sl_pct=3.0, tp_pct=3.0
    )
    assert pnl == 3.0


def test_simulate_bracket_pnl_long_sl_hit():
    pnl = simulate_bracket_pnl(
        side="BUY", entry_price=100.0, exit_price=96.0, sl_pct=3.0, tp_pct=5.0
    )
    assert pnl == -3.0


def test_simulate_bracket_pnl_short_tp_hit():
    pnl = simulate_bracket_pnl(
        side="SELL", entry_price=100.0, exit_price=97.0, sl_pct=3.0, tp_pct=3.0
    )
    assert pnl == 3.0


def test_walk_forward_learn_demo_grid():
    rows = []
    for i in range(24):
        if i % 3 == 0:
            rows.append(_outcome("BUY", 100.0, 96.5, "STOP_LOSS", i))
        elif i % 3 == 1:
            rows.append(_outcome("BUY", 100.0, 103.5, "TAKE_PROFIT", i))
        else:
            rows.append(_outcome("SELL", 50.0, 48.5, "TAKE_PROFIT", i))
    result, status = walk_forward_learn(rows, version=1, min_rows=20, holdout_frac=0.25)
    assert status == "ok"
    assert result is not None
    assert result.sl_pct > 0
    assert result.tp_pct > 0
    assert result.n_fit_rows + result.n_holdout_rows == 24
    manifest = result.to_manifest()
    assert manifest["phase"] == "auto_ml_sltp_p2"
    assert manifest["metrics"]["holdout"]["n"] >= 1


def test_normalize_outcome_row_rejects_incomplete():
    assert normalize_outcome_row({"join_status": "PARTIAL"}) is None
    assert normalize_outcome_row({"join_status": "COMPLETE", "entry_price": 0, "exit_price": 1}) is None


def test_evaluate_sltp_pair_expectancy():
    rows = [
        normalize_outcome_row(_outcome("BUY", 100, 103, "TAKE_PROFIT", 0)),
        normalize_outcome_row(_outcome("BUY", 100, 97, "STOP_LOSS", 1)),
    ]
    rows = [r for r in rows if r]
    m = evaluate_sltp_pair(rows, sl_pct=3.0, tp_pct=3.0)
    assert m["n"] == 2
    assert m["expectancy_pct"] == 0.0
