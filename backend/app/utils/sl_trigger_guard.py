"""Validate / repair stop-loss and take-profit trigger prices against live market.

Crypto.com rejects triggers on the wrong side of the market with
INVALID_TRIGGER_PRICE (50007). Advanced conditional orders use
``ref_price_type=MARK_PRICE``; public tickers only expose last/bid/ask, so we
validate against a *conservative* reference (lowest of last/bid for levels that
must stay below market; highest of last/ask for levels that must stay above).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from app.utils.http_client import http_get

logger = logging.getLogger(__name__)

TICKERS_URL = "https://api.crypto.com/exchange/v1/public/get-tickers"
# Require SL/TP strictly clear of last by this fraction to avoid edge rejects.
_SIDE_BUFFER = 0.001  # 0.1%
_DEFAULT_SL_PCT = 10.0


def fetch_ticker_prices(symbol: str, *, timeout: float = 5.0) -> Optional[Dict[str, float]]:
    """Return last/bid/ask from public tickers, or None on failure.

    Crypto.com ``public/get-tickers`` fields:
      ``a`` = last trade, ``b`` = best bid, ``k`` = best ask.
    """
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
        row = data[0] or {}
        out: Dict[str, float] = {}
        for key, field in (("last", "a"), ("bid", "b"), ("ask", "k")):
            raw = row.get(field)
            if raw is None:
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value > 0:
                out[key] = value
        return out or None
    except Exception as exc:
        logger.warning("Ticker fetch failed for %s: %s", symbol, exc)
        return None


def fetch_last_price(symbol: str, *, timeout: float = 5.0) -> Optional[float]:
    """Return last trade price for instrument, or None on failure."""
    ticker = fetch_ticker_prices(symbol, timeout=timeout)
    if not ticker:
        return None
    return ticker.get("last") or next(iter(ticker.values()), None)


def reference_price_for_trigger(
    entry_side: str,
    *,
    is_tp: bool,
    ticker: Optional[Dict[str, float]] = None,
    last_price: Optional[float] = None,
) -> Optional[float]:
    """Conservative market reference for trigger validity checks.

    Short TP / long SL must stay *below* market → use min(last, bid).
    Long TP / short SL must stay *above* market → use max(last, ask).
    Falls back to ``last_price`` when the ticker dict is unavailable.
    """
    side = (entry_side or "BUY").upper()
    need_below = (side == "SELL" and is_tp) or (side != "SELL" and not is_tp)

    if ticker:
        if need_below:
            vals = [ticker[k] for k in ("last", "bid") if ticker.get(k)]
            if vals:
                return min(vals)
        else:
            vals = [ticker[k] for k in ("last", "ask") if ticker.get(k)]
            if vals:
                return max(vals)
        # Any positive field as last resort
        vals = [v for v in ticker.values() if v and v > 0]
        if vals:
            return min(vals) if need_below else max(vals)

    if last_price is not None and last_price > 0:
        return float(last_price)
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


def tp_round_up_for_closing_side(closing_side: str) -> bool:
    """Quantize TP away from market so tick rounding cannot flip validity.

    Long close (SELL TP above): ROUND_UP.
    Short close (BUY TP below): ROUND_DOWN.
    """
    return (closing_side or "").strip().upper() != "BUY"


def ensure_tp_clear_of_market_after_tick(
    *,
    entry_side: str,
    tp_price: float,
    market_price: float,
    tick_size: Optional[float] = None,
    buffer: float = _SIDE_BUFFER,
) -> float:
    """After quantization, nudge one more tick away if still on the wrong side."""
    if tp_price <= 0 or market_price <= 0:
        return tp_price
    if is_tp_trigger_valid(entry_side, tp_price, market_price, buffer=buffer):
        return tp_price

    side = (entry_side or "BUY").upper()
    tick = float(tick_size) if tick_size and float(tick_size) > 0 else None
    if side == "SELL":
        # Need TP strictly below market * (1 - buffer)
        ceiling = market_price * (1.0 - buffer)
        repaired = ceiling
        if tick:
            # Step down to a tick strictly below ceiling
            import math

            steps = math.floor(ceiling / tick) - 1
            if steps > 0:
                repaired = steps * tick
        return repaired if repaired > 0 else tp_price

    floor = market_price * (1.0 + buffer)
    repaired = floor
    if tick:
        import math

        steps = math.ceil(floor / tick) + 1
        repaired = steps * tick
    return repaired


def ensure_valid_tp_trigger(
    *,
    entry_side: str,
    tp_price: float,
    last_price: Optional[float],
    tp_percentage: Optional[float] = None,
    entry_price: Optional[float] = None,
    ticker: Optional[Dict[str, float]] = None,
) -> Tuple[float, Optional[str]]:
    """
    Return (tp_price, reason) where reason is set if the price was adjusted.

    Stale absolute TPs (e.g. short TP above last after a drop) are rejected by
    Crypto.com with INVALID_TRIGGER_PRICE — recompute from market using %.
    Prefer ``ticker`` so short TPs validate against min(last, bid).
    """
    ref = reference_price_for_trigger(
        entry_side, is_tp=True, ticker=ticker, last_price=last_price
    )
    if ref is None or ref <= 0:
        return tp_price, None
    if is_tp_trigger_valid(entry_side, tp_price, ref):
        return tp_price, None

    pct = derive_tp_percentage(entry_side, entry_price, tp_price, tp_percentage)
    repaired = compute_market_relative_tp(entry_side, ref, pct)
    reason = (
        f"stale/invalid TP {tp_price} vs market_ref {ref} "
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
    ticker: Optional[Dict[str, float]] = None,
) -> Tuple[float, Optional[str]]:
    """
    Return (sl_price, reason) where reason is set if the price was adjusted.

    If last_price/ticker is unavailable, returns the original price unchanged.
    """
    ref = reference_price_for_trigger(
        entry_side, is_tp=False, ticker=ticker, last_price=last_price
    )
    if ref is None or ref <= 0:
        return sl_price, None
    if is_sl_trigger_valid(entry_side, sl_price, ref):
        return sl_price, None

    pct = derive_sl_percentage(entry_side, entry_price, sl_price, sl_percentage)
    repaired = compute_market_relative_sl(entry_side, ref, pct)
    reason = (
        f"stale/invalid SL {sl_price} vs market_ref {ref} "
        f"(entry_side={entry_side}); recomputed to {repaired} using {pct:.4g}%"
    )
    logger.warning("SL trigger guard: %s", reason)
    return repaired, reason


def error_is_invalid_trigger_price(error: Optional[str]) -> bool:
    if not error:
        return False
    text = str(error).upper()
    return "INVALID_TRIGGER_PRICE" in text or "50007" in text


def summarize_format_variation_failure(
    *,
    order_kind: str,
    last_error: Optional[str],
    attempts: int,
    trigger_price: Any = None,
    market_ref: Any = None,
) -> str:
    """Surface the real exchange error instead of a generic variations wrapper."""
    err = (last_error or "Unknown error").strip()
    base = f"All {order_kind} format variations failed ({attempts} attempts). Last error: {err}"
    if error_is_invalid_trigger_price(err):
        detail = (
            f"INVALID_TRIGGER_PRICE: trigger={trigger_price} market_ref={market_ref}. "
            "Trigger is on the wrong side of market for this closing side "
            "(short BUY-TP must be below mark; long SELL-TP above)."
        )
        return f"{base} | {detail}"
    return base
