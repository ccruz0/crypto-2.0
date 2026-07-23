"""Compute SL/TP from entry + strategy %, adjusting if market already passed the level."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def _round_price(price: float) -> float:
    if price >= 100:
        return round(price, 2)
    if price >= 1:
        return round(price, 4)
    return round(price, 6)


def compute_strategy_sl_tp_prices(
    *,
    entry_side: str,
    entry_price: float,
    sl_pct: float,
    tp_pct: float,
    current_price: Optional[float] = None,
    buffer_pct: float = 0.15,
) -> Tuple[float, float, Dict[str, Any]]:
    """
    Return (sl_price, tp_price, meta).

    For a long (BUY entry):
      SL = entry * (1 - sl%), TP = entry * (1 + tp%)
      If market already <= SL → SL just below market
      If market already >= TP → TP just above market

    For a short (SELL entry): mirrored.
    """
    side = (entry_side or "BUY").upper()
    entry = float(entry_price)
    sl_pct = abs(float(sl_pct))
    tp_pct = abs(float(tp_pct))
    buf = abs(float(buffer_pct))
    meta: Dict[str, Any] = {
        "entry_side": side,
        "entry_price": entry,
        "sl_pct": sl_pct,
        "tp_pct": tp_pct,
        "current_price": current_price,
        "buffer_pct": buf,
        "sl_adjusted": False,
        "tp_adjusted": False,
    }

    if side == "SELL":
        sl = entry * (1 + sl_pct / 100.0)
        tp = entry * (1 - tp_pct / 100.0)
        if current_price and current_price > 0:
            if current_price >= sl:
                sl = current_price * (1 + buf / 100.0)
                meta["sl_adjusted"] = True
                meta["sl_reason"] = "market_already_above_sl"
            if current_price <= tp:
                tp = current_price * (1 - buf / 100.0)
                meta["tp_adjusted"] = True
                meta["tp_reason"] = "market_already_below_tp"
    else:
        sl = entry * (1 - sl_pct / 100.0)
        tp = entry * (1 + tp_pct / 100.0)
        if current_price and current_price > 0:
            if current_price <= sl:
                sl = current_price * (1 - buf / 100.0)
                meta["sl_adjusted"] = True
                meta["sl_reason"] = "market_already_below_sl"
            if current_price >= tp:
                tp = current_price * (1 + buf / 100.0)
                meta["tp_adjusted"] = True
                meta["tp_reason"] = "market_already_above_tp"

    sl = _round_price(max(sl, 0.0))
    tp = _round_price(max(tp, 0.0))
    meta["sl_price"] = sl
    meta["tp_price"] = tp
    return sl, tp, meta


def resolve_watchlist_percentages(watchlist_item: Any) -> Tuple[float, float, str]:
    """Return (sl_pct, tp_pct, mode) from watchlist or conservative defaults."""
    mode = (getattr(watchlist_item, "sl_tp_mode", None) or "conservative").lower()
    default_sl, default_tp = (2.0, 2.0) if mode == "aggressive" else (3.0, 3.0)
    sl_raw = getattr(watchlist_item, "sl_percentage", None) if watchlist_item else None
    tp_raw = getattr(watchlist_item, "tp_percentage", None) if watchlist_item else None
    sl_pct = abs(float(sl_raw)) if sl_raw is not None and float(sl_raw) > 0 else default_sl
    tp_pct = abs(float(tp_raw)) if tp_raw is not None and float(tp_raw) > 0 else default_tp
    return sl_pct, tp_pct, mode
