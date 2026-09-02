"""Offline Auto ML SL/TP learning from COMPLETE trade_outcomes (Phase 2 / #623).

Walk-forward grid search over (sl_pct, tp_pct) pairs using bracket simulation on
realized entry/exit prices. Produces a merit report vs conservative 3%/3% baseline.

No live orders, no trading_config mutation, no invent-heal.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Sequence


DEFAULT_BASELINE_SL_PCT = 3.0
DEFAULT_BASELINE_TP_PCT = 3.0

# Grid for conservative search (percent distances from entry).
DEFAULT_SL_GRID: tuple[float, ...] = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0)
DEFAULT_TP_GRID: tuple[float, ...] = (1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0)


def _f(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        x = float(val)
    except (TypeError, ValueError):
        return default
    if x != x:
        return default
    return x


def signed_move_pct(*, side: str, entry_price: float, exit_price: float) -> float:
    """Signed PnL % from entry to exit (positive = winning direction)."""
    entry = _f(entry_price)
    exit_p = _f(exit_price)
    if entry <= 0 or exit_p <= 0:
        return 0.0
    side_u = (side or "BUY").upper()
    if side_u == "SELL":
        return (entry - exit_p) / entry * 100.0
    return (exit_p - entry) / entry * 100.0


def simulate_bracket_pnl(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    sl_pct: float,
    tp_pct: float,
) -> float:
    """Approximate bracket PnL %% using only entry/exit (path-free).

    If move crosses SL first → -sl_pct; if TP → +tp_pct; else realized move capped.
    """
    move = signed_move_pct(side=side, entry_price=entry_price, exit_price=exit_price)
    sl = abs(float(sl_pct))
    tp = abs(float(tp_pct))
    if sl <= 0 or tp <= 0:
        return move
    if move <= -sl:
        return -sl
    if move >= tp:
        return tp
    return move


def _outcome_ts(row: dict[str, Any]) -> float:
    ts = row.get("entry_ts") or row.get("entry_ts_ms") or row.get("alert_timestamp")
    if ts is None:
        return 0.0
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, datetime):
        dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def normalize_outcome_row(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Keep COMPLETE rows with prices and side."""
    if (row.get("join_status") or "COMPLETE") != "COMPLETE":
        return None
    entry = _f(row.get("entry_price"))
    exit_p = _f(row.get("exit_price"))
    if entry <= 0 or exit_p <= 0:
        return None
    side = str(row.get("side") or "BUY").upper()
    if side not in ("BUY", "SELL"):
        return None
    return {
        "symbol": row.get("symbol"),
        "side": side,
        "entry_price": entry,
        "exit_price": exit_p,
        "exit_reason": row.get("exit_reason"),
        "pnl_pct": _f(row.get("pnl_pct")),
        "pnl_usd": _f(row.get("pnl_usd")),
        "hold_seconds": row.get("hold_seconds"),
        "entry_ts": row.get("entry_ts") or row.get("alert_timestamp"),
        "entry_ts_sort": _outcome_ts(row),
        "label": row.get("label"),
        "telegram_message_id": row.get("telegram_message_id"),
        "entry_exchange_order_id": row.get("entry_exchange_order_id"),
    }


def evaluate_sltp_pair(
    outcomes: Sequence[dict[str, Any]],
    *,
    sl_pct: float,
    tp_pct: float,
    indices: Optional[Sequence[int]] = None,
) -> dict[str, Any]:
    """Compute expectancy / win-rate / max drawdown on a subset."""
    idxs = list(range(len(outcomes))) if indices is None else list(indices)
    pnls: list[float] = []
    wins = 0
    for i in idxs:
        row = outcomes[i]
        pnl = simulate_bracket_pnl(
            side=row["side"],
            entry_price=row["entry_price"],
            exit_price=row["exit_price"],
            sl_pct=sl_pct,
            tp_pct=tp_pct,
        )
        pnls.append(pnl)
        if pnl > 0:
            wins += 1
    n = len(pnls)
    if n == 0:
        return {
            "n": 0,
            "sl_pct": sl_pct,
            "tp_pct": tp_pct,
            "expectancy_pct": None,
            "win_rate": None,
            "max_drawdown_pct": None,
            "total_pnl_pct": None,
        }
    expectancy = sum(pnls) / n
    peak = 0.0
    equity = 0.0
    max_dd = 0.0
    for p in pnls:
        equity += p
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return {
        "n": n,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "expectancy_pct": round(expectancy, 6),
        "win_rate": round(wins / n, 6),
        "max_drawdown_pct": round(max_dd, 6),
        "total_pnl_pct": round(sum(pnls), 6),
    }


def grid_search_best_pair(
    outcomes: Sequence[dict[str, Any]],
    *,
    train_indices: Sequence[int],
    sl_grid: Sequence[float] = DEFAULT_SL_GRID,
    tp_grid: Sequence[float] = DEFAULT_TP_GRID,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (best_metrics, all_ranked_candidates_on_train)."""
    ranked: list[dict[str, Any]] = []
    for sl in sl_grid:
        for tp in tp_grid:
            if tp < sl * 0.5:
                continue
            m = evaluate_sltp_pair(outcomes, sl_pct=sl, tp_pct=tp, indices=train_indices)
            if m["n"] == 0:
                continue
            ranked.append(m)
    ranked.sort(
        key=lambda x: (
            x.get("expectancy_pct") if x.get("expectancy_pct") is not None else -1e9,
            -(x.get("max_drawdown_pct") or 1e9),
        ),
        reverse=True,
    )
    best = ranked[0] if ranked else {}
    return best, ranked


@dataclass
class SltpLearnResult:
    version: int
    n_fit_rows: int
    n_holdout_rows: int
    sl_pct: float
    tp_pct: float
    baseline_sl_pct: float
    baseline_tp_pct: float
    train_metrics: dict[str, Any]
    holdout_metrics: dict[str, Any]
    baseline_holdout_metrics: dict[str, Any]
    merit_delta_expectancy: Optional[float]
    dataset_meta: dict[str, Any]
    top_candidates: list[dict[str, Any]]

    def to_manifest(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "phase": "auto_ml_sltp_p2",
            "n_fit_rows": self.n_fit_rows,
            "n_holdout_rows": self.n_holdout_rows,
            "sl_pct": self.sl_pct,
            "tp_pct": self.tp_pct,
            "baseline_sl_pct": self.baseline_sl_pct,
            "baseline_tp_pct": self.baseline_tp_pct,
            "metrics": {
                "train": self.train_metrics,
                "holdout": self.holdout_metrics,
                "baseline_holdout": self.baseline_holdout_metrics,
                "merit_delta_expectancy": self.merit_delta_expectancy,
            },
            "dataset_meta": self.dataset_meta,
            "top_candidates": self.top_candidates[:5],
            "note": "Phase 2 Auto ML SL/TP proposal — promote via human gate only",
        }


def walk_forward_learn(
    raw_outcomes: Sequence[dict[str, Any]],
    *,
    version: int = 1,
    holdout_frac: float = 0.2,
    min_rows: int = 20,
    sl_grid: Sequence[float] = DEFAULT_SL_GRID,
    tp_grid: Sequence[float] = DEFAULT_TP_GRID,
    baseline_sl: float = DEFAULT_BASELINE_SL_PCT,
    baseline_tp: float = DEFAULT_BASELINE_TP_PCT,
) -> tuple[Optional[SltpLearnResult], str]:
    """Time-ordered walk-forward: train grid search, evaluate best on holdout."""
    rows: list[dict[str, Any]] = []
    for raw in raw_outcomes:
        norm = normalize_outcome_row(raw if isinstance(raw, dict) else dict(raw))
        if norm is not None:
            rows.append(norm)
    if len(rows) < min_rows:
        return None, f"n_rows={len(rows)}<{min_rows}"

    rows.sort(key=lambda r: r.get("entry_ts_sort") or 0.0)
    n_holdout = max(1, int(len(rows) * holdout_frac))
    if n_holdout >= len(rows):
        n_holdout = max(1, len(rows) // 5)
    train_end = len(rows) - n_holdout
    if train_end < min_rows - n_holdout:
        return None, f"train_split_too_small train={train_end} holdout={n_holdout}"

    train_idx = list(range(train_end))
    holdout_idx = list(range(train_end, len(rows)))

    best, ranked = grid_search_best_pair(
        rows, train_indices=train_idx, sl_grid=sl_grid, tp_grid=tp_grid
    )
    if not best or best.get("expectancy_pct") is None:
        return None, "grid_search_empty"

    sl_pct = float(best["sl_pct"])
    tp_pct = float(best["tp_pct"])
    train_m = evaluate_sltp_pair(rows, sl_pct=sl_pct, tp_pct=tp_pct, indices=train_idx)
    holdout_m = evaluate_sltp_pair(rows, sl_pct=sl_pct, tp_pct=tp_pct, indices=holdout_idx)
    baseline_h = evaluate_sltp_pair(
        rows, sl_pct=baseline_sl, tp_pct=baseline_tp, indices=holdout_idx
    )

    delta = None
    if (
        holdout_m.get("expectancy_pct") is not None
        and baseline_h.get("expectancy_pct") is not None
    ):
        delta = round(holdout_m["expectancy_pct"] - baseline_h["expectancy_pct"], 6)

    long_n = sum(1 for r in rows if r.get("side") == "BUY")
    short_n = sum(1 for r in rows if r.get("side") == "SELL")
    by_reason: dict[str, int] = {}
    for r in rows:
        reason = str(r.get("exit_reason") or "UNKNOWN")
        by_reason[reason] = by_reason.get(reason, 0) + 1

    result = SltpLearnResult(
        version=version,
        n_fit_rows=len(train_idx),
        n_holdout_rows=len(holdout_idx),
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        baseline_sl_pct=baseline_sl,
        baseline_tp_pct=baseline_tp,
        train_metrics=train_m,
        holdout_metrics=holdout_m,
        baseline_holdout_metrics=baseline_h,
        merit_delta_expectancy=delta,
        dataset_meta={
            "source": "trade_outcomes",
            "n_complete": len(rows),
            "n_long": long_n,
            "n_short": short_n,
            "exit_reason_counts": by_reason,
            "holdout_frac": holdout_frac,
        },
        top_candidates=ranked[:10],
    )
    return result, "ok"


def format_merit_report(manifest: dict[str, Any]) -> str:
    """Human-readable merit report for operators / Jarvis CEO."""
    m = manifest.get("metrics") if isinstance(manifest.get("metrics"), dict) else {}
    hold = m.get("holdout") if isinstance(m.get("holdout"), dict) else {}
    base = m.get("baseline_holdout") if isinstance(m.get("baseline_holdout"), dict) else {}
    lines = [
        "Auto ML SL/TP merit report (Phase 2)",
        f"version={manifest.get('version')} sl={manifest.get('sl_pct')}% tp={manifest.get('tp_pct')}%",
        f"baseline={manifest.get('baseline_sl_pct')}%/{manifest.get('baseline_tp_pct')}%",
        "",
        "Holdout (learned): "
        f"n={hold.get('n')} expectancy={hold.get('expectancy_pct')}% "
        f"win_rate={hold.get('win_rate')} max_dd={hold.get('max_drawdown_pct')}%",
        "Holdout (baseline): "
        f"n={base.get('n')} expectancy={base.get('expectancy_pct')}% "
        f"win_rate={base.get('win_rate')} max_dd={base.get('max_drawdown_pct')}%",
        f"Delta expectancy: {m.get('merit_delta_expectancy')}",
    ]
    meta = manifest.get("dataset_meta") if isinstance(manifest.get("dataset_meta"), dict) else {}
    if meta:
        lines.append(
            f"Dataset: n={meta.get('n_complete')} long={meta.get('n_long')} "
            f"short={meta.get('n_short')} reasons={json.dumps(meta.get('exit_reason_counts') or {})}"
        )
    return "\n".join(lines)
