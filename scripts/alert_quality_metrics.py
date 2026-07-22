"""Pure metric helpers for Phase 1 offline alert-quality scorecards (M1–M5, M7).

No I/O, no secrets, no trading_config mutation. See:
docs/project-history/alert-quality-eval-phase1-2026-07-22.md
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Optional, Sequence

Side = Literal["BUY", "SELL"]

DEFAULT_DELTA = 0.005  # 0.5%
HORIZONS_MIN = {"15m": 15, "1h": 60, "4h": 240}
DEFAULT_MFE_HORIZON_MIN = 240  # 4h; scalp uses 60


@dataclass(frozen=True)
class Candle:
    """OHLCV bar with open time in UTC milliseconds."""

    t: int
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0


def parse_side_from_message(message: str) -> Optional[Side]:
    text = message or ""
    upper = text.upper()
    if "BUY SIGNAL" in upper or "🟢" in text:
        return "BUY"
    if "SELL SIGNAL" in upper or "🔴" in text:
        return "SELL"
    return None


def parse_price_from_message(message: str) -> Optional[float]:
    """Extract entry/spot price from Telegram alert body."""
    if not message:
        return None
    patterns = (
        r"(?:Entry\s+Price|Price)\s*:\s*\$?\s*([\d,]+(?:\.\d+)?)",
        r"@\s*\$\s*([\d,]+(?:\.\d+)?)",
    )
    for pat in patterns:
        m = re.search(pat, message, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def parse_strategy_from_message(message: str) -> tuple[Optional[str], Optional[str]]:
    """Return (strategy_type, risk_approach) from alert text if present."""
    if not message:
        return None, None
    strat = None
    approach = None
    m = re.search(r"Strategy:\s*(?:<b>)?([A-Za-z]+)(?:</b>)?", message, re.I)
    if m:
        strat = m.group(1).strip()
    m = re.search(r"Approach:\s*(?:<b>)?([A-Za-z]+)(?:</b>)?", message, re.I)
    if m:
        approach = m.group(1).strip()
    return strat, approach


def strategy_key(strategy: Optional[str], approach: Optional[str]) -> str:
    s = (strategy or "swing").strip().lower()
    a = (approach or "conservative").strip().lower()
    return f"{s}-{a}"


def parse_context_json(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        import json

        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def resolve_entry_price(
    *,
    message: str,
    context: Optional[dict[str, Any]] = None,
    trade_entry: Optional[float] = None,
    fill_price: Optional[float] = None,
) -> Optional[float]:
    ctx = context or {}
    for key in ("entry_price", "price", "current_price", "spot_price"):
        val = ctx.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass
    parsed = parse_price_from_message(message)
    if parsed is not None:
        return parsed
    if trade_entry is not None:
        try:
            return float(trade_entry)
        except (TypeError, ValueError):
            pass
    if fill_price is not None:
        try:
            return float(fill_price)
        except (TypeError, ValueError):
            pass
    return None


def to_utc_ms(ts: Any) -> Optional[int]:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        # Heuristic: seconds vs ms
        v = float(ts)
        if v < 1e12:
            return int(v * 1000)
        return int(v)
    if isinstance(ts, datetime):
        dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    if isinstance(ts, str):
        text = ts.strip()
        if not text:
            return None
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            return None
    return None


def _clip01(x: float) -> float:
    if math.isnan(x) or math.isinf(x):
        return 0.0
    return max(0.0, min(1.0, x))


def forward_return(entry: float, close_t: float, side: Side) -> Optional[float]:
    if entry is None or entry <= 0 or close_t is None:
        return None
    raw = (close_t - entry) / entry
    return raw if side == "BUY" else -raw


def trend_hit(
    entry: float,
    close_t: float,
    side: Side,
    delta: float = DEFAULT_DELTA,
) -> Optional[bool]:
    """M1: BUY close > entry*(1+δ); SELL close < entry*(1−δ)."""
    if entry is None or entry <= 0 or close_t is None:
        return None
    if side == "BUY":
        return close_t > entry * (1.0 + delta)
    return close_t < entry * (1.0 - delta)


def direction_accuracy(
    entry: float,
    close_t: float,
    side: Side,
) -> Optional[bool]:
    """M2: sign(return) matches side (zero return = miss)."""
    if entry is None or entry <= 0 or close_t is None:
        return None
    ret = (close_t - entry) / entry
    if ret == 0:
        return False
    if side == "BUY":
        return ret > 0
    return ret < 0


def mfe_mae(
    entry: float,
    side: Side,
    candles: Sequence[Candle],
) -> tuple[Optional[float], Optional[float]]:
    """M3: max favorable / adverse excursion as fractions of entry.

    Returns (mfe_pct, mae_pct) where both are >= 0 fractions (0.01 = 1%).
    """
    if entry is None or entry <= 0 or not candles:
        return None, None
    mfe = 0.0
    mae = 0.0
    for c in candles:
        if side == "BUY":
            fav = (c.h - entry) / entry
            adv = (entry - c.l) / entry
        else:
            fav = (entry - c.l) / entry
            adv = (c.h - entry) / entry
        if fav > mfe:
            mfe = fav
        if adv > mae:
            mae = adv
    return mfe, mae


def compute_sl_tp(
    entry: float,
    side: Side,
    *,
    atr: Optional[float] = None,
    atr_mult: float = 1.5,
    fallback_pct: float = 0.03,
    rr: float = 1.5,
) -> tuple[float, float]:
    """Derive SL/TP prices from entry + ATR (or fallback %) and reward:risk."""
    if atr is not None and atr > 0:
        dist = atr * atr_mult
    else:
        dist = entry * fallback_pct
    if side == "BUY":
        sl = entry - dist
        tp = entry + dist * rr
    else:
        sl = entry + dist
        tp = entry - dist * rr
    return sl, tp


def tp_before_sl(
    entry: float,
    side: Side,
    candles: Sequence[Candle],
    sl: float,
    tp: float,
) -> Optional[bool]:
    """M4: True if TP touched before SL; False if SL first; None if neither."""
    if not candles or entry <= 0:
        return None
    for c in candles:
        if side == "BUY":
            hit_sl = c.l <= sl
            hit_tp = c.h >= tp
        else:
            hit_sl = c.h >= sl
            hit_tp = c.l <= tp
        if hit_tp and hit_sl:
            # Ambiguous same-bar: treat as neither decisive (null)
            return None
        if hit_tp:
            return True
        if hit_sl:
            return False
    return None


def expectancy_proxy(
    hit_rate: float,
    avg_mfe: float,
    miss_rate: float,
    avg_mae: float,
) -> float:
    """M5: hit_rate×avg_MFE − miss_rate×avg_MAE (fractions)."""
    return hit_rate * avg_mfe - miss_rate * avg_mae


def composite_score(
    *,
    dir_1h: Optional[bool],
    trend_4h: Optional[bool],
    tp_sl: Optional[bool],
    mfe: Optional[float],
    mae: Optional[float],
) -> Optional[float]:
    """M7: 0.35·dir_1h + 0.25·trend_4h + 0.25·tp_before_sl + 0.15·clip(MFE−MAE).

    Missing terms are skipped and remaining weights are renormalized.
    """
    terms: list[tuple[float, float]] = []
    if dir_1h is not None:
        terms.append((0.35, 1.0 if dir_1h else 0.0))
    if trend_4h is not None:
        terms.append((0.25, 1.0 if trend_4h else 0.0))
    if tp_sl is not None:
        terms.append((0.25, 1.0 if tp_sl else 0.0))
    if mfe is not None and mae is not None:
        terms.append((0.15, _clip01(mfe - mae)))
    if not terms:
        return None
    w_sum = sum(w for w, _ in terms)
    if w_sum <= 0:
        return None
    return sum(w * v for w, v in terms) / w_sum


def close_at_horizon(
    entry_ts_ms: int,
    horizon_min: int,
    candles: Sequence[Candle],
) -> Optional[float]:
    """Close of the last candle whose open time is <= entry+horizon."""
    if not candles:
        return None
    target = entry_ts_ms + horizon_min * 60_000
    best: Optional[Candle] = None
    for c in candles:
        if c.t <= target:
            best = c
        elif c.t > target:
            break
    if best is None:
        # If first candle starts after target, use first close as approximation
        if candles[0].t <= target + horizon_min * 60_000:
            return candles[0].c
        return None
    return best.c


def candles_in_window(
    entry_ts_ms: int,
    horizon_min: int,
    candles: Sequence[Candle],
) -> list[Candle]:
    end = entry_ts_ms + horizon_min * 60_000
    return [c for c in candles if entry_ts_ms <= c.t <= end]


def label_alert(
    *,
    side: Side,
    entry: float,
    entry_ts_ms: int,
    candles: Sequence[Candle],
    atr: Optional[float] = None,
    atr_mult: float = 1.5,
    fallback_pct: float = 0.03,
    rr: float = 1.5,
    delta: float = DEFAULT_DELTA,
    mfe_horizon_min: int = DEFAULT_MFE_HORIZON_MIN,
) -> dict[str, Any]:
    """Compute per-alert metric payload (M1–M4 pieces + M7)."""
    sorted_c = sorted(candles, key=lambda c: c.t)
    window = candles_in_window(entry_ts_ms, mfe_horizon_min, sorted_c)
    mfe, mae = mfe_mae(entry, side, window)
    sl, tp = compute_sl_tp(
        entry, side, atr=atr, atr_mult=atr_mult, fallback_pct=fallback_pct, rr=rr
    )
    tp_sl = tp_before_sl(entry, side, window, sl, tp)

    out: dict[str, Any] = {
        "entry_price": entry,
        "sl_price": sl,
        "tp_price": tp,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "horizon_min": mfe_horizon_min,
        "tp_before_sl": tp_sl,
        "ret_15m": None,
        "ret_1h": None,
        "ret_4h": None,
        "trend_hit_15m": None,
        "trend_hit_1h": None,
        "trend_hit_4h": None,
        "dir_acc_15m": None,
        "dir_acc_1h": None,
        "dir_acc_4h": None,
        "composite_score": None,
    }

    for name, mins in HORIZONS_MIN.items():
        close = close_at_horizon(entry_ts_ms, mins, sorted_c)
        ret = forward_return(entry, close, side) if close is not None else None
        th = trend_hit(entry, close, side, delta=delta) if close is not None else None
        da = direction_accuracy(entry, close, side) if close is not None else None
        out[f"ret_{name}"] = ret
        out[f"trend_hit_{name}"] = th
        out[f"dir_acc_{name}"] = da

    out["composite_score"] = composite_score(
        dir_1h=out["dir_acc_1h"],
        trend_4h=out["trend_hit_4h"],
        tp_sl=tp_sl,
        mfe=mfe,
        mae=mae,
    )
    return out


def _mean(vals: Iterable[float]) -> Optional[float]:
    xs = [float(v) for v in vals]
    if not xs:
        return None
    return sum(xs) / len(xs)


def _rate(bools: Sequence[Optional[bool]]) -> Optional[float]:
    known = [b for b in bools if b is not None]
    if not known:
        return None
    return sum(1 for b in known if b) / len(known)


def rollup_segment(rows: Sequence[dict[str, Any]], min_n: int = 20) -> dict[str, Any]:
    """Aggregate labeled alerts for one symbol×strategy×side segment."""
    n = len(rows)
    dir_1h = _rate([r.get("dir_acc_1h") for r in rows])
    trend_4h = _rate([r.get("trend_hit_4h") for r in rows])
    tp_sl = _rate([r.get("tp_before_sl") for r in rows])
    mfes = [r["mfe_pct"] for r in rows if r.get("mfe_pct") is not None]
    maes = [r["mae_pct"] for r in rows if r.get("mae_pct") is not None]
    composites = [r["composite_score"] for r in rows if r.get("composite_score") is not None]

    # M5: treat trend_hit_1h as hit/miss for expectancy proxy
    hits = [r for r in rows if r.get("trend_hit_1h") is True]
    misses = [r for r in rows if r.get("trend_hit_1h") is False]
    labeled = len(hits) + len(misses)
    hit_rate = (len(hits) / labeled) if labeled else 0.0
    miss_rate = (len(misses) / labeled) if labeled else 0.0
    avg_mfe = _mean([r["mfe_pct"] for r in hits if r.get("mfe_pct") is not None]) or 0.0
    avg_mae = _mean([r["mae_pct"] for r in misses if r.get("mae_pct") is not None]) or 0.0
    expectancy = expectancy_proxy(hit_rate, avg_mfe, miss_rate, avg_mae) if labeled else None

    def _median(xs: list[float]) -> Optional[float]:
        if not xs:
            return None
        ys = sorted(xs)
        mid = len(ys) // 2
        if len(ys) % 2:
            return ys[mid]
        return (ys[mid - 1] + ys[mid]) / 2.0

    return {
        "n": n,
        "rankable": n >= min_n,
        "dir_acc_1h": dir_1h,
        "trend_hit_4h": trend_4h,
        "tp_before_sl_rate": tp_sl,
        "median_mfe": _median(mfes),
        "median_mae": _median(maes),
        "mean_composite": _mean(composites),
        "expectancy_proxy": expectancy,
        "hit_rate_1h": hit_rate if labeled else None,
    }
