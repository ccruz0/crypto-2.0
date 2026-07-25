"""Feature extraction for Auto entry ML (runtime + offline-compatible).

Must stay in sync with scripts/auto_ml_features.FEATURE_NAMES / FEATURE_VERSION.
No I/O, no trading_config mutation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

FEATURE_NAMES: tuple[str, ...] = (
    "rsi",
    "ma50_dist",
    "ma200_dist",
    "ema10_dist",
    "volume_ratio",
    "atr_pct",
    "strategy_index",
    "side_buy",
    "hour_utc_norm",
)

FEATURE_VERSION = 1


def _f(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        x = float(val)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return x


def _rel_dist(price: float, level: Optional[float]) -> float:
    if price is None or price <= 0 or level is None:
        return 0.0
    try:
        lv = float(level)
    except (TypeError, ValueError):
        return 0.0
    if lv <= 0:
        return 0.0
    return (price - lv) / price


def extract_features(
    *,
    side: str,
    entry_price: float,
    entry_ts_ms: Optional[int] = None,
    rsi: Optional[float] = None,
    ma50: Optional[float] = None,
    ma200: Optional[float] = None,
    ema10: Optional[float] = None,
    volume_ratio: Optional[float] = None,
    atr: Optional[float] = None,
    strategy_index: Optional[float] = None,
    context: Optional[dict[str, Any]] = None,
) -> dict[str, float]:
    """Build named feature dict from live indicators or alert context."""
    ctx = context or {}
    price = _f(entry_price, 0.0)
    if price <= 0:
        for key in ("price", "current_price", "spot_price", "entry_price"):
            price = _f(ctx.get(key), 0.0)
            if price > 0:
                break

    rsi_v = rsi if rsi is not None else ctx.get("rsi", ctx.get("RSI"))
    rsi_out = max(0.0, min(100.0, _f(rsi_v, 50.0)))

    ma50_v = ma50 if ma50 is not None else ctx.get("ma50", ctx.get("MA50"))
    ma200_v = ma200 if ma200 is not None else ctx.get("ma200", ctx.get("MA200"))
    ema10_v = ema10 if ema10 is not None else ctx.get("ema10", ctx.get("EMA10"))

    vol = volume_ratio
    if vol is None:
        vol = ctx.get("volume_ratio", ctx.get("vol_ratio", ctx.get("volumeRatio")))
    if vol is None:
        cur = ctx.get("current_volume", ctx.get("volume"))
        avg = ctx.get("avg_volume")
        if cur is not None and avg is not None and _f(avg) > 0:
            vol = _f(cur) / _f(avg)
    volume_ratio_out = _f(vol, 1.0)

    atr_val = atr if atr is not None else ctx.get("atr", ctx.get("ATR", ctx.get("atr14")))
    atr_pct = (_f(atr_val) / price) if price > 0 and atr_val is not None else 0.0

    idx = strategy_index
    if idx is None:
        idx = ctx.get("strategy_index", ctx.get("index"))
        if idx is None and isinstance(ctx.get("strategy"), dict):
            idx = ctx["strategy"].get("index")
    # Live index is 0–100; normalize to 0–1
    strategy_index_out = _f(idx, 50.0)
    if strategy_index_out > 1.0:
        strategy_index_out = strategy_index_out / 100.0

    side_u = (side or "").strip().upper()
    side_buy = 1.0 if side_u == "BUY" else 0.0

    hour = 12.0
    if entry_ts_ms is not None:
        try:
            dt = datetime.fromtimestamp(int(entry_ts_ms) / 1000.0, tz=timezone.utc)
            hour = float(dt.hour)
        except (OverflowError, OSError, ValueError):
            hour = 12.0
    else:
        hour = float(datetime.now(timezone.utc).hour)
    hour_utc_norm = hour / 23.0 if hour <= 23 else 1.0

    return {
        "rsi": rsi_out,
        "ma50_dist": _rel_dist(price, ma50_v if ma50_v is not None else None),
        "ma200_dist": _rel_dist(price, ma200_v if ma200_v is not None else None),
        "ema10_dist": _rel_dist(price, ema10_v if ema10_v is not None else None),
        "volume_ratio": volume_ratio_out,
        "atr_pct": atr_pct,
        "strategy_index": strategy_index_out,
        "side_buy": side_buy,
        "hour_utc_norm": hour_utc_norm,
    }


def feature_vector(feats: dict[str, float]) -> list[float]:
    return [float(feats.get(name, 0.0)) for name in FEATURE_NAMES]
