"""Validate / repair stop-loss trigger prices against live market.

Crypto.com rejects STOP triggers on the wrong side of the market with
INVALID_TRIGGER_PRICE (e.g. long SL above last after price dropped).
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from app.utils.http_client import http_get

logger = logging.getLogger(__name__)

TICKERS_URL = "https://api.crypto.com/exchange/v1/public/get-tickers"
# Require SL strictly clear of last by this fraction to avoid edge rejects.
_SIDE_BUFFER = 0.001  # 0.1%
_DEFAULT_SL_PCT = 10.0


def fetch_last_price(symbol: str, *, timeout: float = 5.0) -> Optional[float]:
    """Return last trade price for instrument, or None on failure."""
    try:
        response = http_get(
            TICKERS_URL,
            params={"instrument_name": symbol},
            timeout=timeout,
            calling_module="sl_trigger_guard",
        )
        if response.status_code != 200:
            logger.warning(
                "Ticker fetch HTTP %s for %s", response.status_code, symbol
            )
            return None
        payload = response.json()
        data = (payload.get("result") or {}).get("data") or []
        if not data:
            return None
        last = data[0].get("a")
        if last is None:
            return None
        value = float(last)
        return value if value > 0 else None
    except Exception as exc:
        logger.warning("Ticker fetch failed for %s: %s", symbol, exc)
        return None


def is_sl_trigger_valid(
    entry_side: str,
    sl_price: float,
    last_price: float,
    *,
    buffer: float = _SIDE_BUFFER,
) -> bool:
    """True if SL trigger is on the exchange-valid side of last."""
    if sl_price <= 0 or last_price <= 0:
        return False
    side = (entry_side or "BUY").upper()
    if side == "SELL":
        # Short: buy-stop must be above market
        return sl_price > last_price * (1.0 + buffer)
    # Long: sell-stop must be below market
    return sl_price < last_price * (1.0 - buffer)


def derive_sl_percentage(
    entry_side: str,
    entry_price: Optional[float],
    sl_price: Optional[float],
    explicit_pct: Optional[float] = None,
) -> float:
    if explicit_pct is not None and explicit_pct > 0:
        return float(explicit_pct)
    if entry_price and entry_price > 0 and sl_price and sl_price > 0:
        side = (entry_side or "BUY").upper()
        if side == "SELL":
            return abs((sl_price - entry_price) / entry_price * 100.0)
        return abs((entry_price - sl_price) / entry_price * 100.0)
    return _DEFAULT_SL_PCT


def compute_market_relative_sl(
    entry_side: str,
    last_price: float,
    sl_percentage: float,
) -> float:
    pct = abs(float(sl_percentage)) if sl_percentage else _DEFAULT_SL_PCT
    # Ensure at least the side buffer so the result is valid immediately.
    pct = max(pct, _SIDE_BUFFER * 100.0 * 2)
    side = (entry_side or "BUY").upper()
    if side == "SELL":
        return last_price * (1.0 + pct / 100.0)
    return last_price * (1.0 - pct / 100.0)


def is_tp_trigger_valid(
    entry_side: str,
    tp_price: float,
    last_price: float,
    *,
    buffer: float = _SIDE_BUFFER,
) -> bool:
    """True if TP trigger is on the exchange-valid side of last.

    Long (BUY entry): sell-TP must be above market.
    Short (SELL entry): buy-TP must be below market.
    """
    if tp_price <= 0 or last_price <= 0:
        return False
    side = (entry_side or "BUY").upper()
    if side == "SELL":
        return tp_price < last_price * (1.0 - buffer)
    return tp_price > last_price * (1.0 + buffer)


def is_abs_level_valid_vs_entry(
    entry_side: str,
    level: float,
    entry_price: float,
    *,
    is_tp: bool,
) -> bool:
    """True when an absolute SL/TP sits on the profit/loss side of entry."""
    if level <= 0 or entry_price <= 0:
        return False
    side = (entry_side or "BUY").upper()
    if side == "SELL":
        # Short: TP buys lower, SL buys higher
        return level < entry_price if is_tp else level > entry_price
    # Long: TP sells higher, SL sells lower
    return level > entry_price if is_tp else level < entry_price


def derive_tp_percentage(
    entry_side: str,
    entry_price: Optional[float],
    tp_price: Optional[float],
    explicit_pct: Optional[float] = None,
) -> float:
    if explicit_pct is not None and explicit_pct > 0:
        return float(explicit_pct)
    if entry_price and entry_price > 0 and tp_price and tp_price > 0:
        side = (entry_side or "BUY").upper()
        if side == "SELL":
            return abs((entry_price - tp_price) / entry_price * 100.0)
        return abs((tp_price - entry_price) / entry_price * 100.0)
    return 1.0


def compute_market_relative_tp(
    entry_side: str,
    last_price: float,
    tp_percentage: float,
) -> float:
    pct = abs(float(tp_percentage)) if tp_percentage else 1.0
    pct = max(pct, _SIDE_BUFFER * 100.0 * 2)
    side = (entry_side or "BUY").upper()
    if side == "SELL":
        return last_price * (1.0 - pct / 100.0)
    return last_price * (1.0 + pct / 100.0)


def ensure_valid_tp_trigger(
    *,
    entry_side: str,
    tp_price: float,
    last_price: Optional[float],
    tp_percentage: Optional[float] = None,
    entry_price: Optional[float] = None,
) -> Tuple[float, Optional[str]]:
    """
    Return (tp_price, reason) where reason is set if the price was adjusted.

    Stale absolute TPs (e.g. short TP above last after a drop) are rejected by
    Crypto.com with INVALID_TRIGGER_PRICE — recompute from last using %.
    """
    if last_price is None or last_price <= 0:
        return tp_price, None
    if is_tp_trigger_valid(entry_side, tp_price, last_price):
        return tp_price, None

    pct = derive_tp_percentage(entry_side, entry_price, tp_price, tp_percentage)
    repaired = compute_market_relative_tp(entry_side, last_price, pct)
    reason = (
        f"stale/invalid TP {tp_price} vs last {last_price} "
        f"(entry_side={entry_side}); recomputed to {repaired} using {pct:.4g}%"
    )
    logger.warning("TP trigger guard: %s", reason)
    return repaired, reason


def ensure_valid_sl_trigger(
    *,
    entry_side: str,
    sl_price: float,
    last_price: Optional[float],
    sl_percentage: Optional[float] = None,
    entry_price: Optional[float] = None,
) -> Tuple[float, Optional[str]]:
    """
    Return (sl_price, reason) where reason is set if the price was adjusted.

    If last_price is unavailable, returns the original price unchanged.
    """
    if last_price is None or last_price <= 0:
        return sl_price, None
    if is_sl_trigger_valid(entry_side, sl_price, last_price):
        return sl_price, None

    pct = derive_sl_percentage(entry_side, entry_price, sl_price, sl_percentage)
    repaired = compute_market_relative_sl(entry_side, last_price, pct)
    reason = (
        f"stale/invalid SL {sl_price} vs last {last_price} "
        f"(entry_side={entry_side}); recomputed to {repaired} using {pct:.4g}%"
    )
    logger.warning("SL trigger guard: %s", reason)
    return repaired, reason


def error_is_invalid_trigger_price(error: Optional[str]) -> bool:
    if not error:
        return False
    text = str(error).upper()
    return "INVALID_TRIGGER_PRICE" in text or "50007" in text
