"""
Week 6: Exchange order formatting layer for Crypto.com (TP/SL).

- Decimal-only internally; string only at request boundary.
- No scientific notation, no commas.
- Quantize to instrument tick/step; validate before send.
- trigger_condition format for exchange expectations.
"""
from __future__ import annotations

import logging
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Optional, Any

logger = logging.getLogger(__name__)

# Crypto.com error codes (for classification)
EXCHANGE_CODE_INVALID_PRICE_FORMAT = 308
EXCHANGE_CODE_API_DISABLED = 140001

# Reason codes for structured logging
REASON_INVALID_PRICE_FORMAT = "INVALID_PRICE_FORMAT"
REASON_EXCHANGE_API_DISABLED = "EXCHANGE_API_DISABLED"


def _to_decimal(x: Any) -> Decimal:
    """Convert to Decimal; never use float for precision."""
    if isinstance(x, Decimal):
        return x
    if x is None:
        raise ValueError("None not allowed")
    return Decimal(str(x))


def normalize_decimal_str(x: Any, max_dp: int = 8, min_dp: Optional[int] = None) -> str:
    """
    Format value as plain decimal string: no commas, no scientific notation.
    Accepts Decimal or numeric; uses '.' decimal separator only.
    Optionally strip trailing zeros; keep at least min_dp decimal places if required.
    """
    if not isinstance(x, Decimal):
        x = _to_decimal(x)
    # Format with fixed decimals then strip trailing zeros
    s = format(x.quantize(Decimal(10) ** -max_dp), f".{max_dp}f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if min_dp is not None and "." in s:
        parts = s.split(".", 1)
        if len(parts[1]) < min_dp:
            s = f"{parts[0]}.{parts[1].ljust(min_dp, '0')}"
    if s in ("-0", "-0.0", ""):
        s = "0"
    return s


def quantize_price(symbol_meta: dict, price: Decimal, round_up: bool = False) -> Decimal:
    """Quantize price to instrument tick size. symbol_meta: price_tick_size (str)."""
    price = _to_decimal(price)
    tick_str = symbol_meta.get("price_tick_size") or "0.01"
    tick = _to_decimal(tick_str)
    if tick <= 0:
        return price
    rounding = ROUND_UP if round_up else ROUND_DOWN
    q = (price / tick).quantize(Decimal("1"), rounding=rounding) * tick
    return q


def quantize_qty(symbol_meta: dict, qty: Decimal) -> Decimal:
    """Quantize quantity to instrument step (qty_tick_size). Always ROUND_DOWN."""
    qty = _to_decimal(qty)
    step_str = symbol_meta.get("qty_tick_size") or symbol_meta.get("quantity_step") or "0.01"
    step = _to_decimal(step_str)
    if step <= 0:
        return qty
    q = (qty / step).quantize(Decimal("1"), rounding=ROUND_DOWN) * step
    return q


def validate_price_tick(symbol_meta: dict, price: Decimal) -> None:
    """Raise ValueError if price is not aligned to tick (optional strict check)."""
    price = _to_decimal(price)
    tick_str = symbol_meta.get("price_tick_size") or "0.01"
    tick = _to_decimal(tick_str)
    if tick <= 0:
        return
    remainder = (price / tick) % 1
    if remainder != 0:
        raise ValueError(f"Price {price} not aligned to tick {tick}")


def validate_qty_step(symbol_meta: dict, qty: Decimal) -> None:
    """Raise ValueError if qty is not aligned to step or below min_quantity."""
    qty = _to_decimal(qty)
    step_str = symbol_meta.get("qty_tick_size") or "0.01"
    min_str = symbol_meta.get("min_quantity") or step_str
    step = _to_decimal(step_str)
    min_q = _to_decimal(min_str)
    if qty < min_q:
        raise ValueError(f"Quantity {qty} below min_quantity {min_q}")
    remainder = (qty / step) % 1 if step > 0 else Decimal("0")
    if remainder != 0:
        raise ValueError(f"Quantity {qty} not aligned to step {step}")


def format_price_for_exchange(symbol_meta: dict, price: Any, round_up: bool = False) -> str:
    """
    Quantize price to instrument tick size and return a string suitable for Crypto.com API.
    - Uses '.' decimal separator only.
    - No scientific notation.
    - Preserves enough decimal places for the tick size.
    """
    price_q = quantize_price(symbol_meta, price, round_up=round_up)
    tick_str = symbol_meta.get("price_tick_size") or "0.01"
    tick = _to_decimal(tick_str)
    max_dp = 8
    if tick > 0:
        if "." in str(tick_str):
            frac = str(tick_str).split(".", 1)[1].rstrip("0")
            max_dp = max(max_dp, len(frac))
    return normalize_decimal_str(price_q, max_dp=max_dp, min_dp=None)


def format_qty_for_exchange(symbol_meta: dict, qty: Any) -> str:
    """
    Quantize quantity to lot size and return a string suitable for Crypto.com API.
    - Uses '.' decimal separator only; no scientific notation.
    """
    qty_q = quantize_qty(symbol_meta, qty)
    step_str = symbol_meta.get("qty_tick_size") or symbol_meta.get("quantity_step") or "0.01"
    step = _to_decimal(step_str)
    max_dp = 8
    if step > 0 and "." in str(step_str):
        frac = str(step_str).split(".", 1)[1].rstrip("0")
        max_dp = max(max_dp, len(frac))
    return normalize_decimal_str(qty_q, max_dp=max_dp, min_dp=None)


def format_trigger_condition(tp_or_sl: str, trigger_price: Decimal, comparator: str = ">=") -> str:
    """
    Build trigger_condition string for Crypto.com.
    TP: typically ">= {price}" (trigger when market >= TP price).
    SL: typically "<= {price}" (trigger when market <= SL price).
    Returns e.g. ">= 2984.41" or "<= 2659.37".
    """
    price = _to_decimal(trigger_price)
    # Plain decimal string, no scientific notation
    p_str = normalize_decimal_str(price, max_dp=8)
    op = (comparator or ">=").strip()
    return f"{op} {p_str}"


def classify_exchange_error_code(code: Optional[int]) -> Optional[str]:
    """
    Map exchange response code to reason_code for structured logging.
    - 308 -> INVALID_PRICE_FORMAT
    - 140001 -> EXCHANGE_API_DISABLED
    """
    if code is None:
        return None
    if code == EXCHANGE_CODE_INVALID_PRICE_FORMAT:
        return REASON_INVALID_PRICE_FORMAT
    if code == EXCHANGE_CODE_API_DISABLED:
        return REASON_EXCHANGE_API_DISABLED
    return None


def operator_action_for_api_disabled() -> str:
    """Short operator checklist for 140001 (no secrets)."""
    return (
        "Enable API trading / conditional orders for this account; "
        "check IP allowlist and sub-account permissions; "
        "see docs/CRYPTOCOM_SL_TP_CREATION.md"
    )


def _is_scientific_notation(s: str) -> bool:
    """True if string looks like a numeric in scientific notation (e.g. 1e-5, 2E+3)."""
    if not isinstance(s, str) or not s:
        return False
    s = s.strip().lower()
    if "e" not in s:
        return False
    parts = s.split("e", 1)
    return len(parts) == 2 and parts[0].strip() != "" and parts[1].strip() != ""


def validate_sltp_payload_numeric(params: dict) -> tuple[bool, list[str]]:
    """
    Validate that a payload has no floats and no scientific notation in numeric fields.
    Returns (ok, list of error descriptions). Used before sending SL/TP to API.
    """
    errors: list[str] = []
    numeric_keys = ("price", "quantity", "trigger_price", "ref_price", "stop_price")
    for k, v in params.items():
        if k not in numeric_keys:
            continue
        if v is None:
            errors.append(f"missing numeric field: {k}")
            continue
        if isinstance(v, str):
            s = v.strip()
            if s == "":
                errors.append(f"missing numeric field: {k}")
                continue
            if s.lower() == "none":
                errors.append(f"invalid numeric field: {k}=None")
                continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            errors.append(f"field {k} is numeric (int/float), must be string")
            continue
        if isinstance(v, str) and _is_scientific_notation(v):
            errors.append(f"field {k} contains scientific notation")
    return (len(errors) == 0, errors)
