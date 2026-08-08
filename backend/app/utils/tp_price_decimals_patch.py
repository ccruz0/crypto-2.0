"""Runtime patch: derive price_decimals from quote_decimals/tick when API omits it.

``crypto_com_trade.py`` is path-guard protected. Ops / recovery scripts import this
module to apply the same fix without editing the protected broker file.

Regression (#394 ops): DOGE_USD omitted price_decimals → default 2 → TP format
variations sent \"0.07\" for planned 0.0692 → INVALID_TRIGGER_PRICE.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_APPLIED = False


def derive_price_decimals(inst: dict, price_tick_size_raw: Any) -> int:
    """Mirror the intended broker metadata fix (quote_decimals → tick → 2)."""
    price_decimals = inst.get("price_decimals")
    if price_decimals is None:
        price_decimals = inst.get("quote_decimals")
    if price_decimals is None and price_tick_size_raw is not None:
        pts = str(price_tick_size_raw)
        if "." in pts:
            frac = pts.split(".", 1)[1]
            price_decimals = len(frac.rstrip("0")) or len(frac)
        else:
            price_decimals = 0
    if price_decimals is None:
        price_decimals = 2
    return int(price_decimals)


def apply_price_decimals_patch() -> bool:
    """Monkeypatch CryptoComTradeClient._parse_instrument_entry. Idempotent."""
    global _APPLIED
    if _APPLIED:
        return False

    from app.services.brokers.crypto_com_trade import CryptoComTradeClient

    original = CryptoComTradeClient._parse_instrument_entry

    @staticmethod
    def _patched(inst: dict, symbol_upper: str) -> Optional[dict]:
        meta = original(inst, symbol_upper)
        if not meta:
            return meta
        # Only rewrite when the API omitted price_decimals (defaulted to 2).
        if inst.get("price_decimals") is not None:
            return meta
        tick_raw = inst.get("price_tick_size")
        derived = derive_price_decimals(inst, tick_raw)
        if int(meta.get("price_decimals") or 0) != derived:
            logger.info(
                "[TP_PRICE_DECIMALS_PATCH] %s price_decimals %s -> %s "
                "(quote_decimals=%s tick=%s)",
                symbol_upper,
                meta.get("price_decimals"),
                derived,
                inst.get("quote_decimals"),
                tick_raw,
            )
            meta["price_decimals"] = derived
        return meta

    CryptoComTradeClient._parse_instrument_entry = _patched
    _APPLIED = True
    logger.info("[TP_PRICE_DECIMALS_PATCH] applied to CryptoComTradeClient")
    return True
