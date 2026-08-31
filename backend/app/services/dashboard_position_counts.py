"""Dashboard open-position / protection risk helpers.

Keeps Watchlist/Portfolio ``N/limit`` aligned with Signal Monitor /
``count_open_positions_for_symbol`` (bot entry exposure), not TP leg counts.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_ACTIVE = {"NEW", "ACTIVE", "PARTIALLY_FILLED", "PENDING"}
# Protective qty larger than this multiple of |wallet| is treated as ghost/orphan.
_GHOST_QTY_MULTIPLE = 3.0
_GHOST_MIN_NOTIONAL_HINT = 1e-8


def _base_from_symbol(symbol: Optional[str]) -> str:
    sym = (symbol or "").upper().strip()
    if not sym:
        return ""
    return sym.split("_")[0] if "_" in sym else sym


def _is_protection_order(order: Any) -> bool:
    from app.services.sl_tp_protection import is_effective_protection_order

    order_type = (getattr(order, "order_type", None) or "").upper()
    role = (getattr(order, "order_role", None) or "").upper()
    if isinstance(order, dict):
        order_type = (order.get("order_type") or order.get("type") or order_type or "").upper()
        role = (order.get("order_role") or role or "").upper()
    return is_effective_protection_order(
        order_role=role or None,
        order_type=order_type or None,
    )


def _order_qty(order: Any) -> float:
    for attr in ("quantity", "qty"):
        raw = getattr(order, attr, None)
        if raw is None and isinstance(order, dict):
            raw = order.get(attr)
        if raw is None:
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def _order_status(order: Any) -> str:
    if hasattr(order, "status"):
        return (getattr(order, "status", None) or "").upper()
    if isinstance(order, dict):
        return (order.get("status") or order.get("order_status") or "").upper()
    return ""


def _order_symbol(order: Any) -> str:
    if hasattr(order, "symbol"):
        return str(getattr(order, "symbol", "") or "")
    if hasattr(order, "instrument_name"):
        return str(getattr(order, "instrument_name", "") or "")
    if isinstance(order, dict):
        return str(order.get("symbol") or order.get("instrument_name") or "")
    return ""


def _order_base(order: Any) -> str:
    base = getattr(order, "base_symbol", None)
    if base:
        return str(base).upper()
    return _base_from_symbol(_order_symbol(order))


def wallet_balances_by_base(balances: Iterable[dict]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for bal in balances or []:
        if not isinstance(bal, dict):
            continue
        currency = str(bal.get("currency") or bal.get("asset") or "").upper()
        base = _base_from_symbol(currency)
        if not base:
            continue
        try:
            qty = float(
                bal.get("balance")
                if bal.get("balance") is not None
                else bal.get("quantity") or 0
            )
        except (TypeError, ValueError):
            continue
        # Prefer exact currency match over accumulating dual books into one base:
        # last write wins is OK for ghost checks (same economic base).
        out[base] = qty
    return out


def collect_bases_for_position_counts(
    balances: Iterable[dict],
    unified_open_orders: Iterable[Any],
) -> List[str]:
    bases: set[str] = set()
    for bal in balances or []:
        if not isinstance(bal, dict):
            continue
        currency = str(bal.get("currency") or bal.get("asset") or "").upper()
        base = _base_from_symbol(currency)
        fiat = {"USD", "USDT", "USDC", "EUR", "DAI", "BUSD"}
        if base and base not in fiat:
            bases.add(base)
    for order in unified_open_orders or []:
        base = _order_base(order)
        if base:
            bases.add(base)
    return sorted(bases)


# Wallet exposure below this USD notional is ignored for the count fallback
# (dust leftovers like ~$0.05 BONK / ~$1 XLM should not show as an open slot).
_WALLET_EXPOSURE_USD_FLOOR = 5.0


def _wallet_abs_usd_by_base(balances: Iterable[dict]) -> Dict[str, float]:
    """Best-effort |usd_value| per base from portfolio balance rows."""
    out: Dict[str, float] = {}
    for bal in balances or []:
        if not isinstance(bal, dict):
            continue
        currency = str(bal.get("currency") or bal.get("asset") or "").upper()
        base = _base_from_symbol(currency)
        if not base:
            continue
        try:
            usd = abs(
                float(
                    bal.get("usd_value")
                    if bal.get("usd_value") is not None
                    else bal.get("market_value") or 0.0
                )
            )
        except (TypeError, ValueError):
            usd = 0.0
        # Prefer the larger absolute USD when dual books exist for one base.
        out[base] = max(out.get(base, 0.0), usd)
    return out


def compute_open_position_counts(
    db,
    bases: Iterable[str],
    *,
    balances: Optional[Iterable[dict]] = None,
) -> Dict[str, int]:
    """Bot entry/exposure slots per base — same definition as Signal Monitor.

    When ``balances`` is provided, a wallet with meaningful |usd| exposure but a
    bot FIFO count of 0 is treated as at least 1 open slot (margin shorts that
    missed ``trade_signal_id`` tagging used to show HBAR=0 while wallet ≠ 0).
    """
    from app.services.order_position_service import count_open_positions_for_symbol

    counts: Dict[str, int] = {}
    for base in bases:
        try:
            counts[base] = int(count_open_positions_for_symbol(db, base))
        except Exception as err:
            logger.warning("count_open_positions_for_symbol(%s) failed: %s", base, err)
            counts[base] = 0

    if balances is None:
        return counts

    wallet_usd = _wallet_abs_usd_by_base(balances)
    for base, usd in wallet_usd.items():
        if usd < _WALLET_EXPOSURE_USD_FLOOR:
            continue
        if int(counts.get(base, 0) or 0) <= 0:
            counts[base] = 1
            logger.info(
                "open_position_counts wallet fallback base=%s usd=%.2f -> 1 "
                "(bot FIFO count was 0)",
                base,
                usd,
            )
    return counts


def compute_protection_leg_stats(
    unified_open_orders: Iterable[Any],
    balances: Iterable[dict],
) -> Tuple[Dict[str, int], Dict[str, int], List[dict]]:
    """Return (tp_counts, protective_counts, ghost_alerts)."""
    wallet = wallet_balances_by_base(balances)
    tp_counts: Dict[str, int] = {}
    protective_counts: Dict[str, int] = {}
    alerts: List[dict] = []

    for order in unified_open_orders or []:
        status = _order_status(order)
        if status and status not in _ACTIVE:
            continue
        if not _is_protection_order(order):
            continue
        base = _order_base(order)
        if not base:
            continue
        protective_counts[base] = protective_counts.get(base, 0) + 1
        order_type = (getattr(order, "order_type", None) or "").upper()
        if (
            "TAKE_PROFIT" in order_type
            or (getattr(order, "order_role", None) or "").upper() == "TAKE_PROFIT"
        ):
            tp_counts[base] = tp_counts.get(base, 0) + 1

        qty = abs(_order_qty(order))
        if qty <= _GHOST_MIN_NOTIONAL_HINT:
            continue
        wallet_signed = float(wallet.get(base, 0.0) or 0.0)
        wallet_qty = abs(wallet_signed)
        side = (getattr(order, "side", None) or "").upper()
        if isinstance(order, dict):
            side = (order.get("side") or side or "").upper()

        # Wrong-side protection vs signed wallet (ALGO long book with BUY covers).
        if wallet_signed > _GHOST_MIN_NOTIONAL_HINT and side == "BUY":
            oid = getattr(order, "order_id", None) or getattr(
                order, "exchange_order_id", None
            )
            alerts.append(
                {
                    "symbol": _order_symbol(order) or base,
                    "base": base,
                    "order_id": str(oid) if oid is not None else None,
                    "order_type": order_type or None,
                    "side": side or None,
                    "quantity": qty,
                    "wallet_qty": wallet_signed,
                    "reason": "wrong_side_cover_on_long",
                }
            )
            continue
        if wallet_signed < -_GHOST_MIN_NOTIONAL_HINT and side == "SELL":
            oid = getattr(order, "order_id", None) or getattr(
                order, "exchange_order_id", None
            )
            alerts.append(
                {
                    "symbol": _order_symbol(order) or base,
                    "base": base,
                    "order_id": str(oid) if oid is not None else None,
                    "order_type": order_type or None,
                    "side": side or None,
                    "quantity": qty,
                    "wallet_qty": wallet_signed,
                    "reason": "wrong_side_cover_on_short",
                }
            )
            continue

        if (
            wallet_qty <= _GHOST_MIN_NOTIONAL_HINT
            or qty > wallet_qty * _GHOST_QTY_MULTIPLE
        ):
            oid = getattr(order, "order_id", None) or getattr(
                order, "exchange_order_id", None
            )
            alerts.append(
                {
                    "symbol": _order_symbol(order) or base,
                    "base": base,
                    "order_id": str(oid) if oid is not None else None,
                    "order_type": order_type or None,
                    "side": side or (getattr(order, "side", None) or None),
                    "quantity": qty,
                    "wallet_qty": wallet_qty,
                    "reason": (
                        "no_wallet"
                        if wallet_qty <= _GHOST_MIN_NOTIONAL_HINT
                        else "qty_exceeds_wallet"
                    ),
                }
            )

    return tp_counts, protective_counts, alerts
