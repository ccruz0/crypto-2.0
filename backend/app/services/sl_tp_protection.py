"""Shared SL/TP protection idempotency helpers (cross-process safe)."""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple, Union  # noqa: F401 — Union used by helpers below

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.utils.filled_entry_order import PROTECTION_ROLES, TRIGGER_ORDER_TYPES

logger = logging.getLogger(__name__)


def is_sltp_healing_enabled() -> bool:
    """Background SL/TP heal/backfill (hourly ensure, sync backfill, OCO cancel-recreate).

    Business rule: alert → fill → SL+TP once at fill time only. Healing is OFF by default.
    Set ``SLTP_HEALING_ENABLED=true`` to restore legacy reconciliation loops (rollback).
    """
    return os.getenv("SLTP_HEALING_ENABLED", "false").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def cap_protection_quantity_to_wallet(
    symbol: str,
    entry_side: str,
    requested_qty: float,
    wallet_balance: Optional[float],
) -> Tuple[float, Optional[str]]:
    """Cap SL/TP qty to signed wallet balance so OCO never exceeds available coins.

    Long (BUY entry): use min(requested, max(0, wallet_balance)).
    Returns (capped_qty, skip_reason).
    """
    if wallet_balance is None:
        return requested_qty, None
    side = (entry_side or "").upper()
    if side == "BUY":
        available = max(0.0, float(wallet_balance))
        if available <= 0:
            return requested_qty, "wallet_empty_long"
        if requested_qty > available + 1e-12:
            logger.warning(
                "[SLTP_QTY_CAP] %s long protection qty %s > wallet %s — capping",
                symbol,
                requested_qty,
                available,
            )
            return available, "capped_to_wallet_balance"
    return requested_qty, None


ACTIVE_PROTECTION_STATUSES = [
    OrderStatusEnum.NEW,
    OrderStatusEnum.ACTIVE,
    OrderStatusEnum.PARTIALLY_FILLED,
]

# Ghost-cleanup grace for ordinary (non-protection) DB rows missing from open+history.
GHOST_CANCEL_GRACE_SECONDS = 120.0

_SL_TP_LOCK_NAMESPACE = 876543210


def is_protection_order(
    *,
    order_role: Optional[str] = None,
    order_type: Optional[str] = None,
) -> bool:
    """True for SL/TP protection legs (by role or trigger order type)."""
    role = (order_role or "").upper().strip()
    if role in PROTECTION_ROLES:
        return True
    return (order_type or "").upper().strip() in TRIGGER_ORDER_TYPES


def is_protection_exchange_order(order: ExchangeOrder) -> bool:
    """Convenience wrapper for ExchangeOrder rows."""
    return is_protection_order(order_role=order.order_role, order_type=order.order_type)


def should_mark_unresolved_order_cancelled(
    order: Union[ExchangeOrder, object],
    age_seconds: Optional[float],
    *,
    grace_seconds: float = GHOST_CANCEL_GRACE_SECONDS,
) -> Tuple[bool, str]:
    """Decide whether sync may mark a missing open order as CANCELLED.

    Protection (SL/TP) must never be ghost-cancelled: Crypto.com trigger/advanced
    orders often omit them from spot open-order/history snapshots, which previously
    caused CANCELLED → recreate loops and moved TP prices.
    """
    if age_seconds is None or age_seconds < grace_seconds:
        return False, "within_grace"

    role = getattr(order, "order_role", None)
    order_type = getattr(order, "order_type", None)
    if is_protection_order(order_role=role, order_type=order_type):
        return False, "protection_requires_exchange_confirmation"

    return True, "stale_non_protection_ghost"


def get_active_protection_order(
    db: Session,
    parent_order_id: str,
    role: str,
) -> Optional[ExchangeOrder]:
    """Return the oldest active protection order for a parent entry and role."""
    return (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.parent_order_id == str(parent_order_id),
            ExchangeOrder.order_role == role,
            ExchangeOrder.status.in_(ACTIVE_PROTECTION_STATUSES),
        )
        .order_by(ExchangeOrder.id.asc())
        .first()
    )


def get_filled_protection_order(
    db: Session,
    parent_order_id: str,
    role: str,
) -> Optional[ExchangeOrder]:
    """Return a FILLED protection leg for a parent (closed / suppressed position)."""
    return (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.parent_order_id == str(parent_order_id),
            ExchangeOrder.order_role == role,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
        )
        .order_by(ExchangeOrder.id.asc())
        .first()
    )


def has_filled_sl_tp_protection(db: Session, parent_order_id: str) -> bool:
    """True when both SL and TP were FILLED (or stubbed closed) for the parent."""
    sl = get_filled_protection_order(db, parent_order_id, "STOP_LOSS")
    tp = get_filled_protection_order(db, parent_order_id, "TAKE_PROFIT")
    return sl is not None and tp is not None


def has_complete_sl_tp_protection(db: Session, parent_order_id: str) -> bool:
    """True when both SL and TP exist as active legs, or both were FILLED/closed."""
    sl = get_active_protection_order(db, parent_order_id, "STOP_LOSS")
    tp = get_active_protection_order(db, parent_order_id, "TAKE_PROFIT")
    if sl is not None and tp is not None:
        return True
    return has_filled_sl_tp_protection(db, parent_order_id)


def has_rejected_protection_order(
    db: Session,
    parent_order_id: str,
    role: str,
) -> bool:
    """True when exchange previously REJECTED this protection role for the parent."""
    row = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.parent_order_id == str(parent_order_id),
            ExchangeOrder.order_role == role,
            ExchangeOrder.status == OrderStatusEnum.REJECTED,
        )
        .first()
    )
    return row is not None


def should_skip_rejected_tp_backfill(
    db: Session,
    parent_order_id: str,
    *,
    allow_spot_oco_heal: bool = True,
    symbol: Optional[str] = None,
) -> bool:
    """Skip endless TP retries when SL is live but TP was already REJECTED.

    When spot native OCO heal is enabled (default), do NOT skip — the caller
    should cancel the standalone SL and recreate both legs as one OCO.
    Margin positions still skip (native OCO is spot-only).
    """
    has_sl = get_active_protection_order(db, parent_order_id, "STOP_LOSS") is not None
    if not has_sl:
        return False
    if not has_rejected_protection_order(db, parent_order_id, "TAKE_PROFIT"):
        return False
    if allow_spot_oco_heal:
        try:
            from app.services.tp_sl_order_creator import (
                is_native_oco_enabled,
                resolve_sltp_margin_context,
            )

            if is_native_oco_enabled():
                sym = symbol
                if not sym:
                    parent = (
                        db.query(ExchangeOrder)
                        .filter(ExchangeOrder.exchange_order_id == parent_order_id)
                        .first()
                    )
                    sym = parent.symbol if parent else None
                if sym:
                    is_margin, _ = resolve_sltp_margin_context(db, sym)
                    if not is_margin:
                        return False
                else:
                    # Unknown symbol: prefer heal path over terminal skip.
                    return False
        except Exception:
            pass
    return True


def wallet_balance_matches_entry_side(
    entry_side: str,
    wallet_balance: float,
    *,
    qty_epsilon: float = 0.0,
) -> bool:
    """True when wallet sign matches the entry side that needs protection.

    BUY entries need a long (positive) wallet. SELL entries need a short
    (negative) wallet. Flat / dust wallets must not get new SL/TP backfills.
    """
    side = (entry_side or "").strip().upper()
    try:
        bal = float(wallet_balance)
    except (TypeError, ValueError):
        return False
    eps = max(0.0, float(qty_epsilon or 0.0))
    if abs(bal) <= eps:
        return False
    if side == "BUY":
        return bal > eps
    if side == "SELL":
        return bal < -eps
    return False


def protection_closing_side_matches_wallet(
    closing_side: str,
    wallet_balance: float,
    *,
    qty_epsilon: float = 0.0,
) -> bool:
    """True when a protection leg's closing side matches wallet inventory.

    SELL SL/TP closes a long (needs positive wallet). BUY SL/TP closes a short
    (needs negative wallet). Used to detect wrong-side ghost legs.
    """
    side = (closing_side or "").strip().upper()
    if hasattr(closing_side, "value"):
        side = str(closing_side.value).strip().upper()
    try:
        bal = float(wallet_balance)
    except (TypeError, ValueError):
        return False
    eps = max(0.0, float(qty_epsilon or 0.0))
    if abs(bal) <= eps:
        return False
    if side == "SELL":
        return bal > eps
    if side == "BUY":
        return bal < -eps
    return False


def should_send_protection_rejected_alert(
    db: Optional[Session],
    *,
    old_status: Optional[Union[OrderStatusEnum, str]],
    order_id: str,
    symbol: Optional[str],
    order_role: Optional[str],
    reject_reason: Optional[str],
) -> bool:
    """Gate PROTECTION ORDER REJECTED Telegram noise.

    Send only when status newly transitions into REJECTED, once per order_id
    (cross-process dedup). Known margin dual-trigger INSUFFICIENT_ACC_BALANCE
    on TAKE_PROFIT is log-only — it is not actionable wallet-funding signal.
    """
    old = old_status.value if hasattr(old_status, "value") else old_status
    old_u = str(old or "").strip().upper()
    if old_u == "REJECTED":
        logger.info(
            "Skipping protection-reject Telegram (already REJECTED) order=%s symbol=%s",
            order_id,
            symbol,
        )
        return False

    role = (order_role or "").strip().upper()
    reason = reject_reason or ""
    try:
        from app.services.tp_sl_order_creator import is_insufficient_acc_balance_error
    except Exception:
        is_insufficient_acc_balance_error = lambda _t: False  # noqa: E731

    if role == "TAKE_PROFIT" and is_insufficient_acc_balance_error(reason):
        logger.warning(
            "Suppressing INSUFFICIENT_ACC_BALANCE TP reject Telegram "
            "order=%s symbol=%s reason=%s (known dual-trigger / margin lock)",
            order_id,
            symbol,
            reason,
        )
        return False

    try:
        from app.services.telegram_event_dedup import claim_telegram_event

        if not claim_telegram_event(
            db,
            f"protection_rejected:{order_id}",
            symbol=symbol,
            ttl_minutes=7 * 24 * 60,
            action="prot_rej",
        ):
            return False
    except Exception as dedup_err:
        logger.debug("protection-reject dedup failed order=%s: %s", order_id, dedup_err)

    return True


def _sl_tp_lock_key(parent_order_id: str) -> int:
    return (_SL_TP_LOCK_NAMESPACE ^ hash(str(parent_order_id))) & 0x7FFFFFFF


def try_acquire_sl_tp_creation_lock(db: Session, parent_order_id: str) -> bool:
    """Try to acquire a Postgres advisory lock for SL/TP creation on one parent order."""
    key = _sl_tp_lock_key(parent_order_id)
    acquired = bool(
        db.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar()
    )
    if not acquired:
        logger.info(
            "[SLTP_LOCK] Could not acquire advisory lock for parent=%s (another worker is creating SL/TP)",
            parent_order_id,
        )
    return acquired


def release_sl_tp_creation_lock(db: Session, parent_order_id: str) -> None:
    """Release the Postgres advisory lock for SL/TP creation on one parent order."""
    key = _sl_tp_lock_key(parent_order_id)
    try:
        db.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
    except Exception as exc:
        logger.warning(
            "[SLTP_LOCK] Failed to release advisory lock for parent=%s: %s",
            parent_order_id,
            exc,
        )
