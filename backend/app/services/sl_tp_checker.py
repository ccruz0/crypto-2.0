"""
SL/TP Checker Service
Checks all open positions for missing SL/TP orders and sends Telegram alerts
"""
import os
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.models.watchlist import WatchlistItem
from app.services.brokers.crypto_com_trade import trade_client
from app.services.telegram_notifier import telegram_notifier
from app.services.exchange_sync import exchange_sync_service
from app.services.tp_sl_order_creator import create_stop_loss_order, create_take_profit_order
from app.services.unified_open_orders_fetch import fetch_unified_open_orders

logger = logging.getLogger(__name__)

# Align with system_core / recover_missing_tps dust floor (USD notional).
_MIN_ENSURE_POSITION_USD = float(os.getenv("SL_TP_MIN_POSITION_USD", os.getenv("SYSTEM_CORE_MIN_POSITION_USD", "5")))


def _entry_symbol_variants(symbol: str) -> List[str]:
    """USD/USDT (and bare) variants so fills on AKT_USD are found for AKT_USDT ensure."""
    symbol = (symbol or "").upper().strip()
    if not symbol:
        return []
    variants = [symbol]
    if "_" not in symbol:
        variants.extend([f"{symbol}_USDT", f"{symbol}_USD"])
    elif symbol.endswith("_USDT"):
        variants.append(symbol.replace("_USDT", "_USD"))
    elif symbol.endswith("_USD"):
        variants.append(symbol.replace("_USD", "_USDT"))
    seen = set()
    out: List[str] = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _order_entry_price(order: ExchangeOrder) -> Optional[float]:
    """Best available fill price from an ExchangeOrder row."""
    price = order.avg_price or order.price
    if (not price or float(price) <= 0) and order.cumulative_value and order.cumulative_quantity:
        try:
            cq = float(order.cumulative_quantity)
            cv = float(order.cumulative_value)
            if cq > 0 and cv > 0:
                price = cv / cq
        except (TypeError, ValueError):
            price = None
    if price is None:
        return None
    try:
        p = float(price)
        return p if p > 0 else None
    except (TypeError, ValueError):
        return None


def _find_recent_entry_order(
    db: Session,
    symbol: str,
    *,
    side: Optional[str] = None,
) -> Optional[ExchangeOrder]:
    """Most recent filled entry order (BUY long or SELL short), excluding protection orders.

    Searches USD/USDT symbol variants — Crypto.com often fills on *_USD while
    watchlist/ensure defaults bare balances to *_USDT.

    When ``side`` is BUY/SELL, only that entry side is considered (avoids linking
    a long wallet to a recent short dust fill and vice versa).
    """
    variants = _entry_symbol_variants(symbol)
    q = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.symbol.in_(variants),
            ExchangeOrder.status == OrderStatusEnum.FILLED,
        )
        .filter(
            (ExchangeOrder.order_role.is_(None))
            | (~ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]))
        )
    )
    side_u = (side or "").strip().upper()
    if side_u == "BUY":
        q = q.filter(ExchangeOrder.side == OrderSideEnum.BUY)
    elif side_u == "SELL":
        q = q.filter(ExchangeOrder.side == OrderSideEnum.SELL)
    else:
        q = q.filter(ExchangeOrder.side.in_([OrderSideEnum.BUY, OrderSideEnum.SELL]))
    return q.order_by(ExchangeOrder.exchange_create_time.desc()).first()


_EXPECTED_ENSURE_SKIP_MARKERS = (
    "wallet_side_mismatch",
    "tp_rejected_terminal",
)


def _is_expected_ensure_skip(creation: Optional[Dict]) -> bool:
    """True when ensure correctly skipped (must not page as hourly failure)."""
    if not creation:
        return False
    skip = str(creation.get("skip_reason") or "").lower()
    err = str(creation.get("error") or "").lower()
    blob = f"{skip} {err}"
    return any(marker in blob for marker in _EXPECTED_ENSURE_SKIP_MARKERS)


def _parent_ids_from_oco_legs(orders: List, oco_id: str) -> List[str]:
    """Collect parent entry ids from OCO legs, with oco_{parent}_{ts} fallback."""
    parent_ids: List[str] = []
    seen = set()
    for order in orders:
        pid = (getattr(order, "parent_order_id", None) or "").strip()
        if pid and pid not in seen:
            seen.add(pid)
            parent_ids.append(pid)
    if not parent_ids and oco_id:
        parts = str(oco_id).split("_")
        if len(parts) >= 3 and parts[0] == "oco" and parts[1].isdigit():
            parent_ids.append(parts[1])
    return parent_ids


def _is_expected_incomplete_missing_tp(
    db: Session,
    still_active: List,
    oco_id: str,
) -> bool:
    """True when a missing TP leg is expected / not an actionable OCO break.

    Suppress Telegram incomplete-group noise when:
    - parent already has an active TP under any OCO linkage, or
    - exchange already REJECTED TP for that parent (terminal / unreachable), or
    - a tp_unreachable / short_tp_not_widened claim is active, or
    - this OCO group itself has a REJECTED TAKE_PROFIT row.
    """
    from app.services.sl_tp_protection import (
        get_active_protection_order,
        has_rejected_protection_order,
    )
    from app.services.telegram_event_dedup import is_telegram_event_claimed

    for parent_id in _parent_ids_from_oco_legs(still_active, oco_id):
        if get_active_protection_order(db, parent_id, "TAKE_PROFIT") is not None:
            return True
        if has_rejected_protection_order(db, parent_id, "TAKE_PROFIT"):
            return True
        if is_telegram_event_claimed(
            db, f"tp_unreachable:{parent_id}", ttl_minutes=24 * 60
        ):
            return True
        if is_telegram_event_claimed(
            db, f"short_tp_not_widened:{parent_id}", ttl_minutes=24 * 60
        ):
            return True

    try:
        rejected_tp = (
            db.query(ExchangeOrder)
            .filter(
                ExchangeOrder.oco_group_id == oco_id,
                ExchangeOrder.order_role == "TAKE_PROFIT",
                ExchangeOrder.status == OrderStatusEnum.REJECTED,
            )
            .first()
        )
        if rejected_tp is not None:
            return True
    except Exception as exc:
        logger.debug(
            "expected-incomplete OCO rejected-TP lookup failed oco=%s: %s",
            oco_id,
            exc,
        )
    return False


def _fetch_mark_price(symbol: str) -> Optional[float]:
    """Mark/last price via simple_price_fetcher (correct API; module has no get_price())."""
    try:
        from simple_price_fetcher import price_fetcher

        for variant in _entry_symbol_variants(symbol):
            result = price_fetcher.get_price(variant)
            if result and getattr(result, "success", False) and result.price and float(result.price) > 0:
                return float(result.price)
    except Exception as exc:
        logger.warning("Mark price fetch failed for %s: %s", symbol, exc)
    return None


def _entry_side_from_order(order: ExchangeOrder) -> str:
    if order.side == OrderSideEnum.SELL:
        return "SELL"
    return "BUY"


def _derive_entry_from_abs_prices(
    *,
    entry_side: str,
    sl_price: Optional[float],
    tp_price: Optional[float],
    sl_percentage: Optional[float],
    tp_percentage: Optional[float],
) -> Optional[float]:
    """Back-solve entry from absolute SL/TP + configured percentages when fills are missing."""
    try:
        if tp_price and tp_percentage and float(tp_percentage) > 0:
            tp_pct = abs(float(tp_percentage)) / 100.0
            tp = float(tp_price)
            if entry_side == "SELL":
                denom = 1.0 - tp_pct
            else:
                denom = 1.0 + tp_pct
            if denom > 0:
                entry = tp / denom
                if entry > 0:
                    return entry
        if sl_price and sl_percentage and float(sl_percentage) > 0:
            sl_pct = abs(float(sl_percentage)) / 100.0
            sl = float(sl_price)
            if entry_side == "SELL":
                denom = 1.0 + sl_pct
            else:
                denom = 1.0 - sl_pct
            if denom > 0:
                entry = sl / denom
                if entry > 0:
                    return entry
    except (TypeError, ValueError):
        return None
    return None


def _compute_sl_tp_from_entry(
    entry_price: float,
    entry_side: str,
    sl_percentage: float,
    tp_percentage: float,
) -> Tuple[float, float]:
    if entry_side == "SELL":
        sl_price = entry_price * (1 + sl_percentage / 100)
        tp_price = entry_price * (1 - tp_percentage / 100)
    else:
        sl_price = entry_price * (1 - sl_percentage / 100)
        tp_price = entry_price * (1 + tp_percentage / 100)
    return sl_price, tp_price


def _classify_open_protection_leg(order: dict) -> Optional[str]:
    """Classify an open exchange order as 'SL', 'TP', or None.

    Advanced TP/SL (SPOT_ATTACH / TAKE_PROFIT_LIMIT / STOP_LIMIT) must be
    detected here — spot-only open-order endpoints miss them.
    """
    order_type = (order.get("order_type") or order.get("type") or "").upper()
    role = (order.get("order_role") or "").upper()
    contingency = (
        order.get("contingency_type") or order.get("contingencyType") or ""
    ).upper()
    side = (order.get("side") or "").upper()
    trigger_price = (
        order.get("trigger_price")
        or order.get("ref_price")
        or order.get("stop_price")
    )

    if role == "TAKE_PROFIT" or "TAKE_PROFIT" in order_type or "TAKE-PROFIT" in order_type:
        return "TP"
    if "PROFIT" in order_type and "TAKE" in order_type:
        return "TP"
    if role == "STOP_LOSS" or any(
        term in order_type for term in ("STOP_LOSS", "STOP_LIMIT", "STOP-LOSS")
    ):
        return "SL"
    if order_type in ("STOP",) or (
        "STOP" in order_type and "TAKE_PROFIT" not in order_type
    ):
        return "SL"
    if contingency in ("STOP_LOSS", "OCO_STOP"):
        return "SL"
    if contingency in ("TAKE_PROFIT", "OCO_TAKE_PROFIT"):
        return "TP"
    # Legacy Crypto.com pattern: LIMIT + trigger closes inventory (SELL long / BUY short)
    if order_type == "LIMIT" and trigger_price and side in ("SELL", "BUY"):
        return "SL"
    return None


def _protection_orders_match_wallet(
    orders: List[dict], position_balance: float
) -> List[dict]:
    """Keep protection legs whose closing side matches the wallet (drop wrong-side ghosts)."""
    from app.services.sl_tp_protection import protection_closing_side_matches_wallet

    matched: List[dict] = []
    for order in orders:
        side = order.get("side") or ""
        if not str(side).strip():
            # Legacy open-order payloads sometimes omit side — keep and size-match.
            matched.append(order)
            continue
        if protection_closing_side_matches_wallet(side, position_balance):
            matched.append(order)
    return matched


def _order_matches_symbol_variants(order: dict, symbol_variants: List[str]) -> bool:
    order_instrument = order.get("instrument_name") or order.get("symbol") or ""
    order_symbol_normalized = str(order_instrument).replace("/", "_").upper()
    variant_normalized = [v.upper() for v in symbol_variants]
    if order_symbol_normalized in variant_normalized:
        return True
    return any(v.replace("_", "/") == order_instrument for v in symbol_variants)


def _is_active_open_order_status(order: dict) -> bool:
    order_status = (
        order.get("order_status", "") or order.get("status", "")
    ).upper()
    return order_status in ("ACTIVE", "NEW", "PENDING", "PARTIALLY_FILLED") or not order_status


def _order_protection_qty(order: dict) -> float:
    """Remaining protective qty when available; else declared order quantity."""
    for key in ("remaining_quantity", "quantity", "qty"):
        raw = order.get(key)
        if raw is None or raw == "":
            continue
        try:
            qty = float(raw)
        except (TypeError, ValueError):
            continue
        if qty > 0:
            return qty
    return 0.0


def _quantity_matches_position(order: dict, position_balance: float) -> bool:
    """True when a single protection order size matches the wallet balance (±5%)."""
    order_quantity = _order_protection_qty(order)
    wallet = abs(float(position_balance or 0.0))
    if order_quantity <= 0 or wallet <= 0:
        return True  # no qty info → assume match (legacy)
    return abs(order_quantity - wallet) / wallet <= 0.05


def _protection_quantities_cover_position(
    orders: List[dict], position_balance: float, tolerance: float = 0.05
) -> bool:
    """True when active protection qtys cover the wallet (single full-size or multi-lot sum).

    Multi-lot positions place one SL/TP per entry lot. Each leg is a fraction of the
    wallet balance, so per-order ±5% matching falsely flags them as unprotected even
    when the sum of legs covers the bag (observed AAVE_USD: 0.105+0.104+0.104 ≈ 0.313).
    """
    wallet = abs(float(position_balance or 0.0))
    if wallet <= 0:
        return True
    active = [o for o in orders if _is_active_open_order_status(o)]
    if not active:
        return False
    qtys = [_order_protection_qty(o) for o in active]
    if all(q <= 0 for q in qtys):
        return True  # no qty info → assume match (legacy)
    for q in qtys:
        if q > 0 and abs(q - wallet) / wallet <= tolerance:
            return True
    covered = sum(q for q in qtys if q > 0)
    # Allow slight undershoot (fees/rounding) and any overshoot (duplicate legs).
    return covered >= wallet * (1.0 - tolerance)


def _parent_lot_qty(order: Optional[ExchangeOrder]) -> Optional[float]:
    """Filled/declared qty of an entry parent used to size linked SL/TP legs."""
    if order is None:
        return None
    for attr in ("cumulative_quantity", "quantity"):
        raw = getattr(order, attr, None)
        if raw is None or raw == "":
            continue
        try:
            qty = float(raw)
        except (TypeError, ValueError):
            continue
        if qty > 0:
            return qty
    return None


def _protection_create_qty(
    *,
    position_balance: float,
    parent_order: Optional[ExchangeOrder] = None,
) -> float:
    """Qty for new SL/TP: parent lot when linked, else wallet. Never exceed wallet.

    Linking a full-wallet leg to a partial parent (e.g. TP 1.893 on a 0.3 fill)
    oversizes coverage and duplicates sister-book lot TPs.
    Short wallets are negative — size with abs(wallet).
    """
    wallet = abs(float(position_balance or 0.0))
    if wallet <= 0:
        return 0.0
    parent_qty = _parent_lot_qty(parent_order)
    if parent_qty is not None and parent_qty > 0:
        return min(parent_qty, wallet)
    return wallet


def _db_active_protection_qty(
    db: Session, symbol_variants: List[str], role: str
) -> float:
    """Sum of active DB protection qty for role across USD/USDT sister books."""
    if not symbol_variants:
        return 0.0
    active_statuses = (
        OrderStatusEnum.ACTIVE,
        OrderStatusEnum.NEW,
        OrderStatusEnum.PARTIALLY_FILLED,
    )
    rows = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.symbol.in_(symbol_variants),
            ExchangeOrder.order_role == role,
            ExchangeOrder.status.in_(active_statuses),
        )
        .all()
    )
    total = 0.0
    for row in rows:
        qty = _parent_lot_qty(row)
        if qty:
            total += qty
    return total


def _db_protection_covers_wallet(
    db: Session,
    symbol_variants: List[str],
    role: str,
    position_balance: float,
    tolerance: float = 0.05,
) -> bool:
    """True when active sister-book SL/TP qty already covers the wallet."""
    wallet = abs(float(position_balance or 0.0))
    if wallet <= 0:
        return True
    covered = _db_active_protection_qty(db, symbol_variants, role)
    return covered >= wallet * (1.0 - tolerance)


def _iter_half_protected_entry_parents(
    db: Session,
    symbol: str,
    *,
    entry_side: Optional[str] = None,
) -> List[ExchangeOrder]:
    """FILLED entry parents with active SL and no active TP (multi-lot TP gap).

    Hourly ensure previously bound only to the most-recent fill. Older lots with
    REJECTED TP history stayed SL-only forever (prod AAVE_USD 2026-08-01).
    """
    from app.services.sl_tp_protection import get_active_protection_order

    variants = _entry_symbol_variants(symbol)
    if not variants:
        return []
    q = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.symbol.in_(variants),
            ExchangeOrder.status == OrderStatusEnum.FILLED,
        )
        .filter(
            (ExchangeOrder.order_role.is_(None))
            | (~ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]))
        )
    )
    side_u = (entry_side or "").strip().upper()
    if side_u == "BUY":
        q = q.filter(ExchangeOrder.side == OrderSideEnum.BUY)
    elif side_u == "SELL":
        q = q.filter(ExchangeOrder.side == OrderSideEnum.SELL)
    else:
        q = q.filter(ExchangeOrder.side.in_([OrderSideEnum.BUY, OrderSideEnum.SELL]))

    parents = q.order_by(ExchangeOrder.exchange_create_time.desc()).all()
    half: List[ExchangeOrder] = []
    for parent in parents:
        pid = (parent.exchange_order_id or "").strip()
        if not pid:
            continue
        if get_active_protection_order(db, pid, "STOP_LOSS") is None:
            continue
        if get_active_protection_order(db, pid, "TAKE_PROFIT") is not None:
            continue
        half.append(parent)
    return half


def _iter_naked_entry_parents(
    db: Session,
    symbol: str,
    *,
    entry_side: Optional[str] = None,
    lookback_hours: float = 168.0,
    max_parents: int = 25,
) -> List[ExchangeOrder]:
    """FILLED entry parents missing ACTIVE SL and/or ACTIVE TP.

    Wallet-sum coverage can look 100% while an older micro fill still has no
    children (prod ETH_USDT 5755600492671134850 — 0.0052 SELL, 2026-08-05).
    Broader than half-protected: includes fully naked parents, not only SL-only.
    """
    from datetime import timedelta

    from app.services.sl_tp_protection import (
        get_active_protection_order,
        has_complete_sl_tp_protection,
        has_filled_sl_tp_protection,
    )
    from app.utils.filled_entry_order import FLATTEN_CLOSE_ROLE, NON_ENTRY_ROLES

    variants = _entry_symbol_variants(symbol)
    if not variants:
        return []

    q = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.symbol.in_(variants),
            ExchangeOrder.status == OrderStatusEnum.FILLED,
        )
        .filter(
            (ExchangeOrder.order_role.is_(None))
            | (~ExchangeOrder.order_role.in_(list(NON_ENTRY_ROLES)))
        )
    )
    side_u = (entry_side or "").strip().upper()
    if side_u == "BUY":
        q = q.filter(ExchangeOrder.side == OrderSideEnum.BUY)
    elif side_u == "SELL":
        q = q.filter(ExchangeOrder.side == OrderSideEnum.SELL)
    else:
        q = q.filter(ExchangeOrder.side.in_([OrderSideEnum.BUY, OrderSideEnum.SELL]))

    if lookback_hours and lookback_hours > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=float(lookback_hours))
        q = q.filter(
            (ExchangeOrder.exchange_update_time >= cutoff)
            | (ExchangeOrder.exchange_create_time >= cutoff)
        )

    parents = q.order_by(ExchangeOrder.exchange_create_time.desc()).all()
    naked: List[ExchangeOrder] = []
    for parent in parents:
        pid = (parent.exchange_order_id or "").strip()
        if not pid:
            continue
        role = (getattr(parent, "order_role", None) or "").strip().upper()
        if role == FLATTEN_CLOSE_ROLE:
            continue
        if has_complete_sl_tp_protection(db, pid):
            continue
        if has_filled_sl_tp_protection(db, pid):
            continue
        has_sl = get_active_protection_order(db, pid, "STOP_LOSS") is not None
        has_tp = get_active_protection_order(db, pid, "TAKE_PROFIT") is not None
        if has_sl and has_tp:
            continue
        naked.append(parent)
        if len(naked) >= max(1, int(max_parents)):
            break
    return naked


def _naked_parent_report_row(
    db: Session,
    parent: ExchangeOrder,
    *,
    symbol: str,
    currency: str,
    balance: float,
    skip_reminder: bool,
    watchlist_item: Optional[WatchlistItem],
    current_price: Optional[float],
) -> Dict:
    """Build a SL/TP-check row sized to the parent lot (not wallet uncovered gap)."""
    from app.services.sl_tp_protection import get_active_protection_order

    pid = (parent.exchange_order_id or "").strip()
    side_val = getattr(parent, "side", None)
    side = side_val.value if hasattr(side_val, "value") else str(side_val or "")
    qty = _parent_lot_qty(parent) or 0.0
    has_sl = get_active_protection_order(db, pid, "STOP_LOSS") is not None
    has_tp = get_active_protection_order(db, pid, "TAKE_PROFIT") is not None
    sl_price = watchlist_item.sl_price if watchlist_item else None
    tp_price = watchlist_item.tp_price if watchlist_item else None
    return {
        "symbol": symbol,
        "currency": currency,
        "balance": balance,
        "has_sl": has_sl,
        "has_tp": has_tp,
        "sl_price": sl_price,
        "tp_price": tp_price,
        "skip_reminder": skip_reminder,
        "watchlist_item": watchlist_item,
        "side": side.upper() if side else None,
        "current_price": current_price,
        # Size Create to this parent fill — do not use wallet uncovered gap.
        "uncovered_qty": qty,
        "sl_covered_qty": qty if has_sl else 0.0,
        "tp_covered_qty": qty if has_tp else 0.0,
        "order_id": pid,
        "entry_order_id": pid,
        "quantity": qty,
        "entry_price": _order_entry_price(parent),
        "naked_parent": True,
    }


def _heal_half_protected_tp_parents(
    db: Session,
    symbol: str,
    *,
    position_balance: float,
    entry_side: str,
    sl_percentage: float,
    tp_percentage: float,
    dry_run: bool,
    source: str = "auto_ensure_multilot",
) -> Dict:
    """Heal every SL-only parent lot for ``symbol`` (spot native OCO preferred)."""
    from app.services.sl_tp_protection import (
        get_active_protection_order,
        should_skip_rejected_tp_backfill,
    )
    from app.services.tp_sl_order_creator import (
        ensure_spot_oco_protection,
        is_native_oco_enabled,
        resolve_sltp_margin_context,
    )
    from app.utils.sl_trigger_guard import ensure_valid_sl_trigger, ensure_valid_tp_trigger

    healed: List[Dict] = []
    skipped: List[Dict] = []
    failed: List[Dict] = []

    parents = _iter_half_protected_entry_parents(
        db, symbol, entry_side=entry_side
    )
    if not parents:
        return {"healed": healed, "skipped": skipped, "failed": failed, "parents": 0}

    is_margin, _leverage = resolve_sltp_margin_context(db, symbol)
    mark = _fetch_mark_price(symbol)

    for parent in parents:
        pid = str(parent.exchange_order_id)
        if should_skip_rejected_tp_backfill(db, pid, symbol=symbol):
            skipped.append(
                {"parent_order_id": pid, "reason": "tp_rejected_terminal"}
            )
            continue

        qty = _protection_create_qty(
            position_balance=position_balance, parent_order=parent
        )
        if qty <= 0:
            skipped.append({"parent_order_id": pid, "reason": "zero_qty"})
            continue

        entry_price = _order_entry_price(parent) or mark
        if not entry_price or float(entry_price) <= 0:
            failed.append({"parent_order_id": pid, "error": "no_entry_price"})
            continue

        parent_side = _entry_side_from_order(parent) or entry_side or "BUY"
        sl_price, tp_price = _compute_sl_tp_from_entry(
            float(entry_price),
            parent_side,
            float(sl_percentage),
            float(tp_percentage),
        )
        if mark and float(mark) > 0:
            tp_price, _ = ensure_valid_tp_trigger(
                entry_side=parent_side,
                tp_price=float(tp_price),
                last_price=float(mark),
                tp_percentage=float(tp_percentage),
                entry_price=float(entry_price),
            )
            sl_price, _ = ensure_valid_sl_trigger(
                entry_side=parent_side,
                sl_price=float(sl_price),
                last_price=float(mark),
                sl_percentage=float(sl_percentage),
                entry_price=float(entry_price),
            )

        existing_sl = get_active_protection_order(db, pid, "STOP_LOSS")
        existing_tp = get_active_protection_order(db, pid, "TAKE_PROFIT")
        if existing_tp is not None:
            skipped.append({"parent_order_id": pid, "reason": "already_has_tp"})
            continue

        logger.info(
            "[%s] Multi-lot TP heal %s parent=%s qty=%s entry=%s sl=%s tp=%s "
            "margin=%s",
            source.upper(),
            symbol,
            pid,
            qty,
            entry_price,
            sl_price,
            tp_price,
            is_margin,
        )

        try:
            if not is_margin and is_native_oco_enabled():
                oco_res = ensure_spot_oco_protection(
                    db=db,
                    symbol=symbol,
                    side=parent_side,
                    tp_price=float(tp_price),
                    sl_price=float(sl_price),
                    quantity=float(qty),
                    entry_price=float(entry_price),
                    parent_order_id=pid,
                    dry_run=dry_run,
                    source=source,
                    existing_sl=existing_sl,
                    existing_tp=existing_tp,
                )
                if oco_res.get("status") == "already_protected" or (
                    not oco_res.get("error")
                    and not oco_res.get("skipped")
                    and (
                        (oco_res.get("tp_result") or {}).get("order_id")
                        or oco_res.get("oco_group_id")
                    )
                ):
                    healed.append(
                        {
                            "parent_order_id": pid,
                            "sl_order_id": (oco_res.get("sl_result") or {}).get(
                                "order_id"
                            ),
                            "tp_order_id": (oco_res.get("tp_result") or {}).get(
                                "order_id"
                            ),
                            "oco_group_id": oco_res.get("oco_group_id"),
                            "status": oco_res.get("status") or "oco_created",
                        }
                    )
                    continue
                failed.append(
                    {
                        "parent_order_id": pid,
                        "error": oco_res.get("error") or "native_oco_failed",
                    }
                )
                continue

            # Margin / OCO-off: cancel-SL-first dual create via shared impl.
            if dry_run:
                skipped.append({"parent_order_id": pid, "reason": "dry_run_margin"})
                continue
            from app.services.exchange_sync import ExchangeSyncService

            impl = ExchangeSyncService()._create_sl_tp_impl(
                db=db,
                symbol=symbol,
                side_upper=parent_side.upper(),
                filled_price_f=float(entry_price),
                filled_qty=float(qty),
                order_id=pid,
                source=source,
                strict_percentages=False,
                sl_price_override_f=float(sl_price),
                tp_price_override_f=float(tp_price),
            )
            tp_res = impl.get("tp_result") or {}
            sl_res = impl.get("sl_result") or {}
            if tp_res.get("order_id") or impl.get("status") == "already_protected":
                healed.append(
                    {
                        "parent_order_id": pid,
                        "sl_order_id": sl_res.get("order_id"),
                        "tp_order_id": tp_res.get("order_id"),
                        "oco_group_id": impl.get("oco_group_id"),
                        "status": impl.get("status") or "margin_dual",
                    }
                )
            else:
                failed.append(
                    {
                        "parent_order_id": pid,
                        "error": tp_res.get("error")
                        or sl_res.get("error")
                        or impl.get("skip_tp_reason")
                        or "margin_dual_failed",
                    }
                )
        except Exception as exc:
            logger.error(
                "[%s] Multi-lot TP heal failed %s parent=%s: %s",
                source.upper(),
                symbol,
                pid,
                exc,
                exc_info=True,
            )
            failed.append({"parent_order_id": pid, "error": str(exc)})

    logger.info(
        "[%s] Multi-lot TP heal %s: parents=%d healed=%d skipped=%d failed=%d",
        source.upper(),
        symbol,
        len(parents),
        len(healed),
        len(skipped),
        len(failed),
    )
    return {
        "healed": healed,
        "skipped": skipped,
        "failed": failed,
        "parents": len(parents),
    }


class SLTPCheckerService:
    """Service to check open positions for missing SL/TP orders and OCO integrity"""
    
    def __init__(self):
        self.last_check_date = None
        self._open_orders_snapshot_complete = False
    
    def _fetch_exchange_open_order_ids(self) -> set:
        """Return exchange order IDs currently open (regular + trigger + advanced)."""
        open_ids: set = set()
        self._open_orders_snapshot_complete = False
        try:
            fetch_result = fetch_unified_open_orders(trade_client)
            if not fetch_result.get("data_verified"):
                logger.warning(
                    "Unified open orders fetch not verified for orphan check: %s",
                    fetch_result.get("error_message"),
                )
            self._open_orders_snapshot_complete = bool(
                fetch_result.get("data_verified")
                and fetch_result.get("trigger_orders_status") in (None, "ok")
                and fetch_result.get("advanced_orders_status") in (None, "ok")
            )
            if not self._open_orders_snapshot_complete:
                logger.warning(
                    "Unified open-orders snapshot incomplete; ghost reconciliation disabled "
                    "(trigger=%s advanced=%s)",
                    fetch_result.get("trigger_orders_status"),
                    fetch_result.get("advanced_orders_status"),
                )
            for raw in fetch_result.get("all_raw_orders") or []:
                for field in ("order_id", "exchange_order_id", "client_oid"):
                    oid = raw.get(field)
                    if oid:
                        open_ids.add(str(oid))
        except Exception as exc:
            logger.warning("Could not fetch unified open orders for orphan check: %s", exc)
        return open_ids

    def _check_oco_issues(self, db: Session) -> Dict:
        """
        Check for OCO-related issues and stale/orphan protection orders.

        Orphan/stale cases (actionable only):
        - Sibling in OCO group already FILLED (other leg should be cancelled)
        - ACTIVE in DB but not present on exchange open orders (ghost/stale)

        Incomplete OCO groups missing TAKE_PROFIT are suppressed when the parent
        already has a REJECTED/unreachable TP (or an active TP under another
        linkage); those land in ``expected_incomplete_groups`` and are not paged.

        Standalone trigger TPs/SLs on the exchange without parent_order_id or
        oco_group_id are valid (legacy/manual orders) and must not be flagged.
        """
        issues = {
            'orphaned_orders': [],
            'incomplete_groups': [],
            'expected_incomplete_groups': [],
            'total_oco_groups': 0,
        }
        sl_tp_types = [
            'STOP_LIMIT', 'STOP_LOSS_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT_LIMIT', 'TAKE_PROFIT',
        ]

        try:
            active_sl_tp = db.query(ExchangeOrder).filter(
                ExchangeOrder.order_type.in_(sl_tp_types),
                ExchangeOrder.status.in_([
                    OrderStatusEnum.NEW,
                    OrderStatusEnum.ACTIVE,
                    OrderStatusEnum.PARTIALLY_FILLED,
                ]),
            ).all()

            logger.info("Checking %d active SL/TP orders for OCO/orphan issues", len(active_sl_tp))
            exchange_open_ids = self._fetch_exchange_open_order_ids()
            seen_orphan_ids: set = set()

            # Wallet by base currency for wrong-side ghost detection (SELL legs on shorts, etc.)
            wallet_by_base: Dict[str, float] = {}
            try:
                summary = trade_client.get_account_summary() or {}
                for acc in summary.get("accounts") or []:
                    cur = str(acc.get("currency") or "").upper().replace("/", "_")
                    if not cur:
                        continue
                    base = cur.split("_")[0]
                    try:
                        bal = float(acc.get("balance") or acc.get("quantity") or 0)
                    except (TypeError, ValueError):
                        continue
                    # Prefer exact base row; keep first non-zero-ish.
                    if base not in wallet_by_base or abs(bal) > abs(wallet_by_base[base]):
                        wallet_by_base[base] = bal
            except Exception as wallet_err:
                logger.debug("Wallet snapshot unavailable for wrong-side reconcile: %s", wallet_err)

            from app.services.sl_tp_protection import protection_closing_side_matches_wallet

            for order in active_sl_tp:
                reasons: List[str] = []
                on_exchange = bool(
                    order.exchange_order_id
                    and exchange_open_ids
                    and str(order.exchange_order_id) in exchange_open_ids
                )

                if order.oco_group_id:
                    siblings = db.query(ExchangeOrder).filter(
                        ExchangeOrder.oco_group_id == order.oco_group_id,
                        ExchangeOrder.exchange_order_id != order.exchange_order_id,
                    ).all()
                    for sibling in siblings:
                        if sibling.status == OrderStatusEnum.FILLED:
                            reasons.append(
                                f"sibling {sibling.order_role} {sibling.exchange_order_id} FILLED"
                            )
                            break

                if order.parent_order_id:
                    sibling_filled = db.query(ExchangeOrder).filter(
                        ExchangeOrder.parent_order_id == order.parent_order_id,
                        ExchangeOrder.exchange_order_id != order.exchange_order_id,
                        ExchangeOrder.order_type.in_(sl_tp_types),
                        ExchangeOrder.status == OrderStatusEnum.FILLED,
                    ).first()
                    if sibling_filled:
                        reason = (
                            f"parent {order.parent_order_id} has filled sibling "
                            f"{sibling_filled.order_role} {sibling_filled.exchange_order_id}"
                        )
                        if reason not in reasons:
                            reasons.append(reason)

                if order.exchange_order_id and exchange_open_ids and not on_exchange:
                    reasons.append("ACTIVE in DB but not on exchange")

                # Wrong-side vs wallet (e.g. SELL SL while ALGO wallet is short).
                closing_side = order.side.value if hasattr(order.side, "value") else str(order.side or "")
                base = (order.symbol or "").split("_")[0].upper()
                wallet_bal = wallet_by_base.get(base)
                wrong_side = False
                if wallet_bal is not None and closing_side:
                    if not protection_closing_side_matches_wallet(closing_side, wallet_bal):
                        wrong_side = True
                        reasons.append(
                            f"wrong-side vs wallet (side={closing_side} bal={wallet_bal})"
                        )

                if reasons and order.exchange_order_id not in seen_orphan_ids:
                    seen_orphan_ids.add(order.exchange_order_id)
                    # Ghost rows: ACTIVE in DB but gone from the exchange. Reconcile
                    # immediately so the next health check / half_protected path does
                    # not keep recreating TP or spamming the same orphans.
                    # Also cancel wrong-side legs (long protection on a short wallet).
                    ghost_only = reasons == ["ACTIVE in DB but not on exchange"]
                    should_reconcile = (
                        (ghost_only and self._open_orders_snapshot_complete)
                        or (wrong_side and (not on_exchange or self._open_orders_snapshot_complete))
                    )
                    if should_reconcile:
                        try:
                            order.status = OrderStatusEnum.CANCELLED
                            order.updated_at = datetime.now(timezone.utc)
                            logger.info(
                                "[OCO_RECONCILE] Marked ghost/wrong-side SL/TP CANCELLED: "
                                "order_id=%s symbol=%s type=%s reasons=%s",
                                order.exchange_order_id,
                                order.symbol,
                                order.order_role or order.order_type,
                                "; ".join(reasons),
                            )
                            continue  # reconciled; do not alert
                        except Exception as reconcile_err:
                            logger.warning(
                                "[OCO_RECONCILE] Failed to mark ghost %s CANCELLED: %s",
                                order.exchange_order_id,
                                reconcile_err,
                            )
                    issues['orphaned_orders'].append({
                        'order_id': order.exchange_order_id,
                        'symbol': order.symbol,
                        'type': order.order_role or order.order_type,
                        'price': float(order.price) if order.price else None,
                        'missing': "; ".join(reasons),
                        'quantity': float(order.quantity) if order.quantity else None,
                        'parent_order_id': order.parent_order_id,
                        'oco_group_id': order.oco_group_id,
                    })

            try:
                db.commit()
            except Exception as commit_err:
                logger.warning("[OCO_RECONCILE] commit failed: %s", commit_err)
                db.rollback()

            from collections import defaultdict
            oco_groups = defaultdict(list)
            for order in active_sl_tp:
                if order.oco_group_id:
                    oco_groups[order.oco_group_id].append(order)

            issues['total_oco_groups'] = len(oco_groups)

            for oco_id, orders in oco_groups.items():
                still_active = [
                    o
                    for o in orders
                    if o.status
                    in (
                        OrderStatusEnum.NEW,
                        OrderStatusEnum.ACTIVE,
                        OrderStatusEnum.PARTIALLY_FILLED,
                    )
                ]
                if not still_active:
                    continue
                has_sl = any(o.order_role == "STOP_LOSS" for o in still_active)
                has_tp = any(o.order_role == "TAKE_PROFIT" for o in still_active)
                if not (has_sl and has_tp):
                    symbol = still_active[0].symbol if still_active else "Unknown"
                    missing = "STOP_LOSS" if not has_sl else "TAKE_PROFIT"
                    group = {
                        'oco_group_id': oco_id,
                        'symbol': symbol,
                        'has_sl': has_sl,
                        'has_tp': has_tp,
                        'missing': missing,
                    }
                    # SL-only + REJECTED/unreachable TP is expected half-protection,
                    # not an actionable OCO integrity break (prod: 31-group noise).
                    if (
                        missing == "TAKE_PROFIT"
                        and has_sl
                        and _is_expected_incomplete_missing_tp(db, still_active, oco_id)
                    ):
                        issues['expected_incomplete_groups'].append(group)
                        continue
                    issues['incomplete_groups'].append(group)

            logger.info(
                "OCO check: %d orphaned, %d incomplete, %d expected-incomplete",
                len(issues['orphaned_orders']),
                len(issues['incomplete_groups']),
                len(issues['expected_incomplete_groups']),
            )

        except Exception as e:
            logger.error(f"Error checking OCO issues: {e}", exc_info=True)
            issues['error'] = str(e)

        return issues
    
    def check_positions_for_sl_tp(self, db: Session) -> Dict:
        """
        Check all open positions and verify if they have SL/TP orders
        
        Returns:
            Dict with positions missing SL/TP
        """
        try:
            # Get account balance to find open positions
            balance_response = trade_client.get_account_summary()
            accounts = balance_response.get('accounts', [])
            
            logger.info(f"Received {len(accounts)} accounts from get_account_summary")
            if len(accounts) > 0:
                logger.info(f"Sample account: {accounts[0]}")
            
            # Filter non-flat wallets (long > 0 or short < 0), excluding USDT/USD.
            # Shorts are negative on Crypto.com — they still need SL/TP ensure.
            # Skipping balance <= 0 left APT/DOGE SHORT missing-TP as REVISIÓN-only
            # noise while auto-ensure never healed them (2026-08-02/03 Telegram).
            open_positions = []
            for account in accounts:
                # Handle both 'currency' and 'instrument_name' fields
                currency = account.get('currency', '').upper()
                if not currency:
                    # Try instrument_name if currency is not available
                    currency = account.get('instrument_name', '').upper()
                
                if not currency:
                    logger.warning(f"Account missing currency/instrument_name: {account}")
                    continue
                    
                # Prefer quantity (signed) then balance — same source as position_review /
                # OCO wrong-side reconcile. Shorts are negative wallets.
                balance_raw = account.get("quantity", account.get("balance", "0"))
                if balance_raw in (None, ""):
                    balance_raw = account.get("balance") or "0"
                
                # Handle balance format - could be string or number
                try:
                    balance = float(balance_raw)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid balance format for {currency}: {balance_raw}")
                    continue
                
                # Skip flat wallets only. Negative = short (must ensure SL/TP).
                # Expected TP already includes shorts; skipping under-reports and left
                # APT/DOGE SHORT as REVISIÓN-only noise (2026-08-02/03 Telegram).
                if abs(balance) <= 1e-12:
                    logger.debug(f"Skipping {currency} - flat balance {balance}")
                    continue
                
                # Handle currency format - could be "ETH" or "ETH_USDT"
                if '_' in currency:
                    # Format is already like "ETH_USDT" - extract base currency
                    base_currency = currency.split('_')[0]
                    symbol = currency  # Keep full symbol for later use
                else:
                    # Format is just currency like "ETH" - prefer watchlist / fill pair
                    base_currency = currency
                    symbol = f"{currency}_USDT"
                    for preferred in (f"{currency}_USD", f"{currency}_USDT"):
                        wl = (
                            db.query(WatchlistItem)
                            .filter(WatchlistItem.symbol == preferred)
                            .first()
                        )
                        if wl:
                            symbol = preferred
                            break
                    # Prefer the pair that actually has a recent filled entry
                    entry_side = "BUY" if balance > 0 else "SELL"
                    for preferred in (f"{currency}_USD", f"{currency}_USDT"):
                        if _find_recent_entry_order(db, preferred, side=entry_side):
                            symbol = preferred
                            break
                
                # Skip stablecoins (USDT, USD, USDC, etc.) and fiat (EUR, GBP, JPY, etc.)
                # Negative stablecoin rows are margin debt, not short crypto inventory.
                stablecoins = ['USDT', 'USD', 'USDC', 'BUSD', 'DAI', 'TUSD']
                fiat = ['EUR', 'GBP', 'JPY', 'CNY', 'AUD', 'CAD', 'CHF', 'NZD', 'SGD', 'HKD', 'KRW']
                if base_currency in stablecoins or base_currency in fiat:
                    logger.debug(f"Skipping stablecoin/fiat: {base_currency}")
                    continue

                # Skip dust leftovers (AKT/ATOM/CRO/LINK residual balances) — cannot protect
                # meaningfully and entry fills are usually gone after the position was closed.
                mark = None
                if _MIN_ENSURE_POSITION_USD > 0:
                    mark = _fetch_mark_price(symbol)
                    if mark and mark > 0:
                        notional = abs(balance) * mark
                        if notional < _MIN_ENSURE_POSITION_USD:
                            logger.info(
                                "Skipping dust position %s balance=%s mark=%s notional=$%.4f "
                                "(min=$%s)",
                                symbol,
                                balance,
                                mark,
                                notional,
                                _MIN_ENSURE_POSITION_USD,
                            )
                            continue
                
                open_positions.append({
                    'currency': base_currency,
                    'symbol': symbol,
                    'balance': balance,
                    'mark_price': mark,
                    'side': 'BUY' if balance > 0 else 'SELL',
                })
                
                logger.info(f"Found open position: {symbol} ({base_currency}) = {balance}")
            
            logger.info(f"Found {len(open_positions)} open positions to check for SL/TP")
            
            # For each position, check if there are active SL/TP orders
            positions_missing_sl_tp = []

            # Fetch once: regular + trigger + advanced (spot-only misses advanced TPs)
            all_orders_data: List[dict] = []
            try:
                fetch_result = fetch_unified_open_orders(trade_client)
                all_orders_data = list(fetch_result.get("all_raw_orders") or [])
                if not fetch_result.get("data_verified"):
                    logger.warning(
                        "Unified open orders not fully verified for SL/TP position check: %s",
                        fetch_result.get("error_message"),
                    )
                logger.info(
                    "Retrieved %s unified open orders for SL/TP position check "
                    "(trigger=%s advanced=%s)",
                    len(all_orders_data),
                    fetch_result.get("trigger_orders_status"),
                    fetch_result.get("advanced_orders_status"),
                )
            except Exception as e:
                logger.warning(
                    "Unified open orders fetch failed for SL/TP check, falling back to spot: %s",
                    e,
                )
                try:
                    all_open_orders = trade_client.get_open_orders()
                    all_orders_data = all_open_orders.get("data", []) or []
                except Exception as spot_err:
                    logger.warning("Spot open orders fallback also failed: %s", spot_err)
                    all_orders_data = []
            
            for position in open_positions:
                currency = position['currency']
                symbol = position.get('symbol', f"{currency}_USDT")  # Use symbol from position or default
                
                # Create symbol variants to check (BONK_USDT, BONK_USD, etc.)
                symbol_variants = [symbol]
                if symbol.endswith('_USDT'):
                    symbol_variants.append(symbol.replace('_USDT', '_USD'))
                elif symbol.endswith('_USD'):
                    symbol_variants.append(symbol.replace('_USD', '_USDT'))
                
                # Try to find symbol in watchlist - try exact match first
                watchlist_item = db.query(WatchlistItem).filter(
                    WatchlistItem.symbol == symbol
                ).first()
                
                if not watchlist_item:
                    # Try pattern match
                    watchlist_item = db.query(WatchlistItem).filter(
                        WatchlistItem.symbol.like(f"%{currency}%")
                    ).first()
                    if watchlist_item:
                        symbol = watchlist_item.symbol  # Use symbol from watchlist if found
                        # Update symbol variants
                        symbol_variants = [symbol]
                        if symbol.endswith('_USDT'):
                            symbol_variants.append(symbol.replace('_USDT', '_USD'))
                        elif symbol.endswith('_USD'):
                            symbol_variants.append(symbol.replace('_USD', '_USDT'))
                
                # Check for active SL/TP orders from Crypto.com Exchange API directly
                # This is more reliable than checking database status
                has_sl = False
                has_tp = False
                sl_covered_qty = 0.0
                tp_covered_qty = 0.0
                
                try:
                    open_orders_data = [
                        order
                        for order in all_orders_data
                        if _order_matches_symbol_variants(order, symbol_variants)
                    ]
                    
                    logger.debug(
                        f"Filtered {len(open_orders_data)} orders for {symbol} "
                        f"from {len(all_orders_data)} total orders"
                    )
                    
                    sl_orders_open = []
                    tp_orders_open = []
                    
                    for o in open_orders_data:
                        leg = _classify_open_protection_leg(o)
                        if leg == "SL":
                            sl_orders_open.append(o)
                            logger.debug(
                                f"Found SL order for {symbol}: "
                                f"{o.get('order_type')} id={o.get('order_id')}"
                            )
                        elif leg == "TP":
                            tp_orders_open.append(o)
                            logger.debug(
                                f"Found TP order for {symbol}: "
                                f"{o.get('order_type')} id={o.get('order_id')}"
                            )
                    
                    logger.info(
                        f"Position {symbol}: Filtered {len(sl_orders_open)} SL and "
                        f"{len(tp_orders_open)} TP orders from {len(open_orders_data)} matched orders"
                    )
                    
                    position_balance = position.get('balance', 0)
                    # Drop wrong-side ghosts (e.g. residual SELL legs on a short wallet).
                    active_sl_orders = _protection_orders_match_wallet(
                        [
                            o
                            for o in sl_orders_open
                            if _is_active_open_order_status(o)
                        ],
                        position_balance,
                    )
                    active_tp_orders = _protection_orders_match_wallet(
                        [
                            o
                            for o in tp_orders_open
                            if _is_active_open_order_status(o)
                        ],
                        position_balance,
                    )
                    sl_covered_qty = sum(_order_protection_qty(o) for o in active_sl_orders)
                    tp_covered_qty = sum(_order_protection_qty(o) for o in active_tp_orders)
                    has_sl = _protection_quantities_cover_position(
                        active_sl_orders, position_balance
                    )
                    has_tp = _protection_quantities_cover_position(
                        active_tp_orders, position_balance
                    )
                    if active_sl_orders and not has_sl:
                        logger.info(
                            "Position %s: SL qty under-covered "
                            "sum=%s balance=%s orders=%s",
                            symbol,
                            sl_covered_qty,
                            position_balance,
                            [o.get("order_id") for o in active_sl_orders],
                        )
                    if active_tp_orders and not has_tp:
                        logger.info(
                            "Position %s: TP qty under-covered "
                            "sum=%s balance=%s orders=%s",
                            symbol,
                            tp_covered_qty,
                            position_balance,
                            [o.get("order_id") for o in active_tp_orders],
                        )

                    logger.info(
                        f"Position {symbol}: SL covered={has_sl} "
                        f"(sum={sl_covered_qty}/{len(active_sl_orders)} legs) "
                        f"TP covered={has_tp} "
                        f"(sum={tp_covered_qty}/{len(active_tp_orders)} legs) "
                        f"balance={position_balance} "
                        f"(raw found: {len(sl_orders_open)} SL, {len(tp_orders_open)} TP)"
                    )
                except Exception as e:
                    logger.warning(f"Error checking open orders from Exchange API for {symbol}: {e}")
                    # Fallback to database check
                    try:
                        from sqlalchemy import or_
                        from app.services.sl_tp_protection import (
                            protection_closing_side_matches_wallet,
                        )

                        position_balance = position.get("balance", 0)

                        def _db_order_matches_wallet(order: ExchangeOrder) -> bool:
                            side = getattr(order, "side", None)
                            if side is None:
                                return True
                            return protection_closing_side_matches_wallet(
                                side, position_balance
                            )

                        # Check database for active orders (status NEW or ACTIVE, not FILLED)
                        sl_orders_db = [
                            o
                            for o in db.query(ExchangeOrder)
                            .filter(
                                or_(
                                    *[
                                        ExchangeOrder.symbol == variant
                                        for variant in symbol_variants
                                    ]
                                ),
                                ExchangeOrder.order_type.in_(
                                    ["STOP_LIMIT", "STOP_LOSS"]
                                ),
                                ExchangeOrder.status.in_(
                                    [
                                        OrderStatusEnum.NEW,
                                        OrderStatusEnum.ACTIVE,
                                        OrderStatusEnum.PARTIALLY_FILLED,
                                    ]
                                ),
                            )
                            .all()
                            if _db_order_matches_wallet(o)
                        ]

                        tp_orders_db = [
                            o
                            for o in db.query(ExchangeOrder)
                            .filter(
                                or_(
                                    *[
                                        ExchangeOrder.symbol == variant
                                        for variant in symbol_variants
                                    ]
                                ),
                                ExchangeOrder.order_type.in_(
                                    ["TAKE_PROFIT_LIMIT", "TAKE_PROFIT"]
                                ),
                                ExchangeOrder.status.in_(
                                    [
                                        OrderStatusEnum.NEW,
                                        OrderStatusEnum.ACTIVE,
                                        OrderStatusEnum.PARTIALLY_FILLED,
                                    ]
                                ),
                            )
                            .all()
                            if _db_order_matches_wallet(o)
                        ]

                        # Match primary path: qty coverage, not mere presence.
                        def _db_rows_as_open_dicts(
                            orders: List[ExchangeOrder],
                        ) -> List[dict]:
                            rows: List[dict] = []
                            for o in orders:
                                status = getattr(o, "status", None)
                                status_s = (
                                    str(getattr(status, "value", status) or "ACTIVE")
                                    .upper()
                                )
                                rows.append(
                                    {
                                        "quantity": float(o.quantity or 0),
                                        "order_status": status_s,
                                        "status": status_s,
                                        "order_id": getattr(o, "order_id", None),
                                    }
                                )
                            return rows

                        sl_open_dicts = _db_rows_as_open_dicts(sl_orders_db)
                        tp_open_dicts = _db_rows_as_open_dicts(tp_orders_db)
                        sl_covered_qty = sum(
                            _order_protection_qty(o) for o in sl_open_dicts
                        )
                        tp_covered_qty = sum(
                            _order_protection_qty(o) for o in tp_open_dicts
                        )
                        has_sl = _protection_quantities_cover_position(
                            sl_open_dicts, position_balance
                        )
                        has_tp = _protection_quantities_cover_position(
                            tp_open_dicts, position_balance
                        )
                        logger.info(
                            f"Position {symbol}: Found {len(sl_orders_db)} SL and "
                            f"{len(tp_orders_db)} TP orders from database "
                            f"(wallet-side+qty filtered, balance={position_balance}, "
                            f"sl_covered={sl_covered_qty}, tp_covered={tp_covered_qty})"
                        )
                    except Exception as db_err:
                        logger.error(f"Error querying orders from database for {symbol}: {db_err}", exc_info=True)
                        has_sl = False
                        has_tp = False
                
                # has_sl and has_tp are now set from Exchange API or database fallback
                logger.info(f"Position {symbol}: Final check - has_sl={has_sl}, has_tp={has_tp}")
                
                # Check if user skipped reminder for this symbol
                skip_reminder = watchlist_item.skip_sl_tp_reminder if watchlist_item else False
                
                logger.info(f"Position {symbol}: has_sl={has_sl}, has_tp={has_tp}, skip_reminder={skip_reminder}, will_include={((not has_sl or not has_tp) and not skip_reminder)}")
                
                # Always include unprotected positions for auto-create (even if reminder skipped).
                # skip_reminder only suppresses Telegram nudge buttons, not protection.
                wallet_row = None
                if not has_sl or not has_tp:
                    # Get SL/TP prices from watchlist if available
                    sl_price = watchlist_item.sl_price if watchlist_item else None
                    tp_price = watchlist_item.tp_price if watchlist_item else None
                    wallet_abs = abs(float(position.get("balance") or 0.0))
                    sl_gap = 0.0 if has_sl else max(0.0, wallet_abs - float(sl_covered_qty or 0.0))
                    tp_gap = 0.0 if has_tp else max(0.0, wallet_abs - float(tp_covered_qty or 0.0))
                    current_price = position.get("mark_price")
                    if current_price is None:
                        current_price = _fetch_mark_price(symbol)

                    wallet_row = {
                        'symbol': symbol,
                        'currency': currency,
                        'balance': position['balance'],
                        'has_sl': has_sl,
                        'has_tp': has_tp,
                        'sl_price': sl_price,
                        'tp_price': tp_price,
                        'skip_reminder': skip_reminder,
                        'watchlist_item': watchlist_item,
                        'side': position.get('side') or (
                            'BUY' if float(position.get('balance') or 0) >= 0 else 'SELL'
                        ),
                        'current_price': current_price,
                        'uncovered_qty': max(sl_gap, tp_gap),
                        'sl_covered_qty': sl_covered_qty,
                        'tp_covered_qty': tp_covered_qty,
                    }

                # Even when wallet-sum SL/TP looks complete, surface FILLED entry
                # parents that still lack ACTIVE children (naked micros). Prefer
                # parent rows over the wallet aggregate so Create sizes to the fill.
                naked_rows: List[Dict] = []
                try:
                    entry_side = position.get("side") or (
                        "BUY" if float(position.get("balance") or 0) >= 0 else "SELL"
                    )
                    naked_parents = _iter_naked_entry_parents(
                        db, symbol, entry_side=str(entry_side)
                    )
                    seen_parent_ids = set()
                    for parent in naked_parents:
                        pid = (parent.exchange_order_id or "").strip()
                        if not pid or pid in seen_parent_ids:
                            continue
                        parent_qty = _parent_lot_qty(parent) or 0.0
                        entry_px = _order_entry_price(parent)
                        mark = position.get("mark_price")
                        if mark is None:
                            mark = _fetch_mark_price(symbol)
                        # Skip sub-dollar dust parents; ETH 0.0052 @ ~1900 is ~$10.
                        notional = parent_qty * float(entry_px or mark or 0.0)
                        if parent_qty <= 0 or notional < 1.0:
                            continue
                        row = _naked_parent_report_row(
                            db,
                            parent,
                            symbol=symbol,
                            currency=currency,
                            balance=float(position.get("balance") or 0.0),
                            skip_reminder=skip_reminder,
                            watchlist_item=watchlist_item,
                            current_price=mark,
                        )
                        naked_rows.append(row)
                        seen_parent_ids.add(pid)
                        logger.warning(
                            "Naked entry parent %s on %s qty=%s (wallet has_sl=%s has_tp=%s)",
                            pid,
                            symbol,
                            parent_qty,
                            has_sl,
                            has_tp,
                        )
                except Exception as naked_err:
                    logger.warning(
                        "Naked-entry parent scan failed for %s: %s",
                        symbol,
                        naked_err,
                        exc_info=True,
                    )

                if naked_rows:
                    positions_missing_sl_tp.extend(naked_rows)
                elif wallet_row is not None:
                    positions_missing_sl_tp.append(wallet_row)
            
            logger.info(f"Found {len(positions_missing_sl_tp)} positions missing SL/TP")
            
            # Check for OCO-related issues
            oco_issues = self._check_oco_issues(db)
            naked_count = sum(
                1 for p in positions_missing_sl_tp if p.get("naked_parent")
            )
            
            return {
                'positions_missing_sl_tp': positions_missing_sl_tp,
                'total_positions': len(open_positions),
                'oco_issues': oco_issues,
                'naked_entry_parent_count': naked_count,
                'checked_at': datetime.utcnow()
            }
            
        except Exception as e:
            logger.error(f"Error checking positions for SL/TP: {e}", exc_info=True)
            return {
                'positions_missing_sl_tp': [],
                'total_positions': 0,
                'error': str(e)
            }
    
    def _ensure_multilot_tp_heal(self, db: Session, pos: Dict) -> Dict:
        """Heal SL-only entry lots for a wallet that still needs TP coverage."""
        symbol = pos["symbol"]
        balance = float(pos.get("balance") or 0.0)
        entry_side = "BUY" if balance >= 0 else "SELL"
        watchlist_item = pos.get("watchlist_item")
        strategy_mode = (
            (getattr(watchlist_item, "sl_tp_mode", None) or "conservative").lower()
            if watchlist_item
            else "conservative"
        )
        sl_percentage = 3.0 if strategy_mode == "conservative" else 2.0
        tp_percentage = 3.0 if strategy_mode == "conservative" else 2.0
        if watchlist_item is not None:
            if (
                getattr(watchlist_item, "sl_percentage", None) is not None
                and float(watchlist_item.sl_percentage) > 0
            ):
                sl_percentage = abs(float(watchlist_item.sl_percentage))
            if (
                getattr(watchlist_item, "tp_percentage", None) is not None
                and float(watchlist_item.tp_percentage) > 0
            ):
                tp_percentage = abs(float(watchlist_item.tp_percentage))

        live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
        return _heal_half_protected_tp_parents(
            db,
            symbol,
            position_balance=balance,
            entry_side=entry_side,
            sl_percentage=sl_percentage,
            tp_percentage=tp_percentage,
            dry_run=not live_trading,
            source="auto_ensure_multilot",
        )

    def ensure_missing_protection(self, db: Session) -> Dict:
        """
        Create missing SL and/or TP for open positions when healing is enabled.

        When ``SLTP_HEALING_ENABLED`` is false (default), this is read-only: it
        reports unprotected positions but does not mutate orders on the exchange.
        """
        from app.services.sl_tp_protection import is_sltp_healing_enabled

        result = self.check_positions_for_sl_tp(db)
        if not is_sltp_healing_enabled():
            positions_missing = result.get("positions_missing_sl_tp", [])
            logger.info(
                "SL/TP healing disabled — read-only scan: %s unprotected position(s)",
                len(positions_missing),
            )
            return {
                "checked_at": result.get("checked_at"),
                "total_positions": result.get("total_positions", 0),
                "oco_issues": result.get("oco_issues", {}),
                "created": [],
                "failed": [],
                "skipped": [],
                "still_missing": positions_missing,
                "positions_missing_sl_tp": positions_missing,
                "healed_parents": [],
                "healing_disabled": True,
            }

        positions_missing = result.get("positions_missing_sl_tp", [])
        created: List[Dict] = []
        failed: List[Dict] = []
        skipped: List[Dict] = []
        still_missing: List[Dict] = []

        healed_parents: List[Dict] = []

        for pos in positions_missing:
            symbol = pos["symbol"]
            create_sl = not pos.get("has_sl")
            create_tp = not pos.get("has_tp")
            if not create_sl and not create_tp:
                continue
            logger.info(
                "Auto-creating missing protection for %s (create_sl=%s create_tp=%s)",
                symbol,
                create_sl,
                create_tp,
            )
            try:
                creation = self._create_protection_order(
                    db,
                    symbol,
                    create_sl=create_sl,
                    create_tp=create_tp,
                    force=True,
                    source="auto_ensure",
                )
            except Exception as exc:
                logger.error(
                    "Auto-create protection failed for %s: %s",
                    symbol,
                    exc,
                    exc_info=True,
                )
                failed.append({"symbol": symbol, "error": str(exc), **pos})
                still_missing.append(pos)
                continue

            if creation.get("success"):
                if creation.get("skip_reason") or _is_expected_ensure_skip(creation):
                    skipped.append(
                        {
                            "symbol": symbol,
                            "skip_reason": creation.get("skip_reason")
                            or creation.get("error"),
                            **pos,
                        }
                    )
                else:
                    created.append(
                        {
                            "symbol": symbol,
                            "sl_order_id": creation.get("sl_order_id"),
                            "tp_order_id": creation.get("tp_order_id"),
                        }
                    )
            elif _is_expected_ensure_skip(creation):
                # Correct no-op (e.g. terminal TP reject) — do not page hourly.
                skipped.append(
                    {
                        "symbol": symbol,
                        "skip_reason": creation.get("skip_reason")
                        or creation.get("error"),
                        **pos,
                    }
                )
            else:
                failed.append(
                    {
                        "symbol": symbol,
                        "error": creation.get("error")
                        or creation.get("sl_error")
                        or creation.get("tp_error"),
                        **pos,
                    }
                )
                # Keep for Telegram reminder if still unprotected
                still_pos = dict(pos)
                if creation.get("sl_order_id"):
                    still_pos["has_sl"] = True
                if creation.get("tp_order_id"):
                    still_pos["has_tp"] = True
                if not still_pos.get("has_sl") or not still_pos.get("has_tp"):
                    still_missing.append(still_pos)

            # Multi-lot TP gap: recent-parent ensure can succeed while older lots
            # remain SL-only (REJECTED TP). Heal every half-protected parent.
            if create_tp:
                try:
                    multilot = self._ensure_multilot_tp_heal(db, pos)
                    for item in multilot.get("healed") or []:
                        healed_parents.append({"symbol": symbol, **item})
                        created.append(
                            {
                                "symbol": symbol,
                                "sl_order_id": item.get("sl_order_id"),
                                "tp_order_id": item.get("tp_order_id"),
                                "parent_order_id": item.get("parent_order_id"),
                                "source": "multilot_tp_heal",
                            }
                        )
                    for item in multilot.get("failed") or []:
                        failed.append({"symbol": symbol, **item})
                except Exception as multilot_exc:
                    logger.error(
                        "Multi-lot TP heal failed for %s: %s",
                        symbol,
                        multilot_exc,
                        exc_info=True,
                    )
                    failed.append(
                        {
                            "symbol": symbol,
                            "error": f"multilot_tp_heal: {multilot_exc}",
                            **pos,
                        }
                    )

        return {
            "checked_at": result.get("checked_at"),
            "total_positions": result.get("total_positions", 0),
            "oco_issues": result.get("oco_issues", {}),
            "created": created,
            "failed": failed,
            "skipped": skipped,
            "still_missing": still_missing,
            "positions_missing_sl_tp": still_missing,
            "healed_parents": healed_parents,
        }

    def send_sl_tp_reminder(self, db: Session) -> bool:
        """
        Scan open positions for missing SL/TP and send reminders.

        When ``SLTP_HEALING_ENABLED`` is true, auto-creates missing legs first.
        When false (default), read-only scan + operator reminder with manual actions.
        Also sends OCO issues alerts.
        
        Returns:
            bool: True if reminder was sent, False otherwise
        """
        try:
            # Always auto-create missing legs first (no age gate)
            ensure_result = self.ensure_missing_protection(db)
            positions_missing = [
                p for p in ensure_result.get("still_missing", [])
                if not p.get("skip_reminder")
            ]
            oco_issues = ensure_result.get('oco_issues', {})

            if ensure_result.get("created"):
                logger.info(
                    "Auto-created protection for %s position(s): %s",
                    len(ensure_result["created"]),
                    [c.get("symbol") for c in ensure_result["created"]],
                )
            if ensure_result.get("failed"):
                logger.warning(
                    "Failed auto-create protection for %s position(s): %s",
                    len(ensure_result["failed"]),
                    [
                        f"{f.get('symbol')}: {f.get('error')}"
                        for f in ensure_result["failed"]
                    ],
                )

            # Always alert on orphan/stale OCO issues even when all positions are protected.
            oco_alerts_sent = self._send_oco_alerts(oco_issues)

            if not positions_missing:
                logger.info("All positions have SL/TP orders, no position reminders needed")
                return oco_alerts_sent > 0 or bool(ensure_result.get("created"))

            # Send one message per position with specific options
            reminders_sent = 0
            for pos in positions_missing:
                symbol = pos['symbol']
                balance = pos['balance']
                has_sl = pos['has_sl']
                has_tp = pos['has_tp']
                sl_price = pos['sl_price']
                tp_price = pos['tp_price']
                currency = pos['currency']
                
                # Determine what's missing
                missing_items = []
                if not has_sl:
                    missing_items.append("SL")
                if not has_tp:
                    missing_items.append("TP")
                
                if not missing_items:
                    continue  # Skip if nothing is missing (shouldn't happen, but just in case)
                
                # Spanish operator copy: state the problem, then list actionable options.
                # Close side follows wallet: LONG → SELL, SHORT → BUY cover.
                side = "SHORT" if float(balance) < 0 else "LONG"
                close_key = f"{symbol}:{side}"
                close_verb = "comprar" if side == "SHORT" else "vender"
                close_side = "BUY" if side == "SHORT" else "SELL"
                message = f"⚠️ <b>POSICIÓN SIN PROTECCIÓN: {symbol}</b>\n\n"
                from app.services.sl_tp_protection import is_sltp_healing_enabled

                if is_sltp_healing_enabled():
                    message += (
                        "⚠️ <b>Problema:</b> auto-creación falló; la posición sigue "
                        f"<b>sin {' y '.join(missing_items)}</b>.\n"
                        "Sin esa protección la posición queda expuesta.\n\n"
                    )
                else:
                    message += (
                        "⚠️ <b>Problema:</b> la posición no tiene "
                        f"<b>{' y '.join(missing_items)}</b> activos.\n"
                        "La auto-creación en segundo plano está desactivada; "
                        "crea protección manualmente o cierra la posición.\n\n"
                    )
                message += f"📊 Símbolo: <b>{symbol}</b>\n"
                message += f"🔄 Lado: <b>{side}</b>\n"
                message += f"💰 Balance: {balance:.6f} {currency}\n\n"

                sl_status = "✅ Activo" if has_sl else "❌ Falta"
                tp_status = "✅ Activo" if has_tp else "❌ Falta"

                message += f"🛑 Stop Loss: {sl_status}"
                if sl_price:
                    message += f" @ ${sl_price:.4f}" if has_sl else f" (precio sugerido: ${sl_price:.4f})"
                message += "\n"

                message += f"🚀 Take Profit: {tp_status}"
                if tp_price:
                    message += f" @ ${tp_price:.4f}" if has_tp else f" (precio sugerido: ${tp_price:.4f})"
                message += "\n\n"

                message += "<b>Opciones:</b>\n"
                opt_n = 1
                if not has_sl:
                    message += f"{opt_n}. Crear un SL\n"
                    opt_n += 1
                if not has_tp:
                    message += f"{opt_n}. Crear un TP\n"
                    opt_n += 1
                message += (
                    f"{opt_n}. Cerrar la posición ({close_verb} a mercado → {close_side})\n\n"
                )
                message += "Elige un botón abajo."

                buttons = []

                if not has_sl and not has_tp:
                    buttons.append([
                        {"text": "🛡️ Crear SL y TP", "callback_data": f"create_sl_tp_{symbol}"},
                    ])
                    buttons.append([
                        {"text": "🛑 Crear SL", "callback_data": f"create_sl_{symbol}"},
                        {"text": "🚀 Crear TP", "callback_data": f"create_tp_{symbol}"}
                    ])
                elif not has_sl:
                    buttons.append([
                        {"text": "🛑 Crear SL", "callback_data": f"create_sl_{symbol}"}
                    ])
                elif not has_tp:
                    buttons.append([
                        {"text": "🚀 Crear TP", "callback_data": f"create_tp_{symbol}"}
                    ])

                buttons.append([
                    {
                        "text": f"🔴 Cerrar ({close_verb})",
                        "callback_data": f"posrev_close:{close_key}",
                    },
                    {"text": "⏭️ No preguntar más", "callback_data": f"skip_sl_tp_{symbol}"}
                ])
                
                # Send individual message for this position with buttons
                try:
                    telegram_notifier.send_message_with_buttons(message, buttons)
                    reminders_sent += 1
                    logger.info(f"Sent SL/TP reminder for {symbol} with buttons (missing: {', '.join(missing_items)})")
                except Exception as e:
                    logger.error(f"Error sending Telegram reminder for {symbol}: {e}")
            
            logger.info(f"Sent {reminders_sent} SL/TP reminders (one per position)")

            # Store reminder state for later processing
            self.last_reminder_positions = positions_missing
            self.last_reminder_time = datetime.utcnow()

            return (reminders_sent > 0 or oco_alerts_sent > 0)

        except Exception as e:
            logger.error(f"Error sending SL/TP reminder: {e}", exc_info=True)
            return False

    def send_orphan_order_alert(self, db: Session) -> bool:
        """Check for orphaned/stale SL/TP orders and send a Telegram alert."""
        try:
            issues = self._check_oco_issues(db)
            return self._send_oco_alerts(issues, db=db) > 0
        except Exception as e:
            logger.error("Error sending orphan order alert: %s", e, exc_info=True)
            return False

    def _send_oco_alerts(self, oco_issues: Dict, db: Session = None) -> int:
        """Send Telegram alerts for OCO issues"""
        alerts_sent = 0
        
        try:
            orphaned = oco_issues.get('orphaned_orders', [])
            incomplete = oco_issues.get('incomplete_groups', [])
            
            if not orphaned and not incomplete:
                logger.info("No OCO issues found")
                return 0

            # Suppress identical health snapshots for 24h (same orphans + incomplete groups).
            from app.services.telegram_event_dedup import claim_telegram_event

            orphan_ids = sorted(
                str(o.get("order_id") or "") for o in orphaned if o.get("order_id")
            )
            incomplete_ids = sorted(
                str(g.get("oco_group_id") or "") for g in incomplete if g.get("oco_group_id")
            )
            fingerprint = f"oco_health:{','.join(orphan_ids)}|{','.join(incomplete_ids)}"
            if not claim_telegram_event(
                db,
                fingerprint,
                ttl_minutes=24 * 60,
                action="oco_health",
            ):
                logger.info(
                    "📢 Skipping duplicate OCO health Telegram (orphaned=%d incomplete=%d)",
                    len(orphaned),
                    len(incomplete),
                )
                return 0
            
            message = "🔧 <b>ORPHAN / OCO HEALTH CHECK</b>\n\n"
            message += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            message += f"📊 Total OCO Groups: {oco_issues.get('total_oco_groups', 0)}\n\n"

            if orphaned:
                message += f"⚠️ <b>ORPHANED / STALE ORDERS: {len(orphaned)}</b>\n\n"
                for order in orphaned:
                    message += f"• <b>{order['symbol']}</b> - {order['type']}\n"
                    if order['price']:
                        message += f"  ${order['price']:,.4f}\n"
                    message += f"  Reason: {order['missing']}\n"
                    if order.get('order_id'):
                        message += f"  Order ID: <code>{order['order_id']}</code>\n"
                    if order.get('parent_order_id'):
                        message += f"  Parent: <code>{order['parent_order_id']}</code>\n"
                    message += "\n"
            
            if incomplete:
                message += f"❌ <b>INCOMPLETE GROUPS: {len(incomplete)}</b>\n\n"
                for group in incomplete:  # Show ALL incomplete groups
                    message += f"• <b>{group['symbol']}</b>\n"
                    message += f"  Has: {group.get('missing') and 'TP' if group.get('missing') == 'STOP_LOSS' else 'SL'}\n"
                    message += f"  Missing: {group['missing']}\n"
                    if group.get('oco_group_id'):
                        message += f"  OCO Group ID: {group['oco_group_id']}\n"
                    message += "\n"
            
            message += "💡 Review with /orders command"
            
            telegram_notifier.send_message(message)
            alerts_sent += 1
            logger.info(f"Sent OCO alert: {len(orphaned)} orphaned, {len(incomplete)} incomplete")
            
        except Exception as e:
            logger.error(f"Error sending OCO alerts: {e}", exc_info=True)
        
        return alerts_sent
    
    def create_sl_for_position(self, db: Session, symbol: str, force: bool = False) -> Dict:
        """
        Create only SL order for a specific position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        return self._create_protection_order(db, symbol, create_sl=True, create_tp=False, force=force)
    
    def create_tp_for_position(self, db: Session, symbol: str, force: bool = False) -> Dict:
        """
        Create only TP order for a specific position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        return self._create_protection_order(db, symbol, create_sl=False, create_tp=True, force=force)
    
    def _create_protection_order(self, db: Session, symbol: str, create_sl: bool = True, create_tp: bool = True, force: bool = False, source: str = "manual") -> Dict:
        """
        Internal method to create SL and/or TP orders for a position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            create_sl: Whether to create SL order
            create_tp: Whether to create TP order
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        try:
            # First, verify there's an open position
            balance_response = trade_client.get_account_summary()
            accounts = balance_response.get('accounts', [])
            
            # Extract base currency from symbol (e.g., ETH from ETH_USDT)
            base_currency = symbol.split('_')[0] if '_' in symbol else symbol
            
            logger.debug(f"Looking for position balance for {symbol} (base currency: {base_currency})")
            logger.debug(f"Available accounts (first 5): {[(acc.get('currency'), acc.get('balance')) for acc in accounts[:5]]}")
            
            position_balance = 0.0
            for account in accounts:
                currency = account.get('currency', '').upper()
                balance_str = account.get('balance', '0')
                
                # Handle formats:
                # 1. currency = "ETH" -> matches base_currency "ETH"
                # 2. currency = "ETH_USDT" -> matches symbol "ETH_USDT"
                # 3. currency = "ETH/USDT" -> matches symbol "ETH_USDT"
                # 4. currency = "BONK/USD" -> matches symbol "BONK_USDT" (flexible)
                
                currency_normalized = currency.replace('/', '_').upper()
                symbol_normalized = symbol.upper()
                base_normalized = base_currency.upper()
                
                # Check if currency matches symbol directly or base currency
                matches = (
                    currency == symbol.upper() or  # Exact match: "ETH_USDT" == "ETH_USDT"
                    currency_normalized == symbol_normalized or  # Normalized match: "ETH/USDT" == "ETH_USDT"
                    currency == base_normalized or  # Base match: "ETH" == "ETH"
                    currency_normalized == base_normalized or  # Normalized base: "ETH/USDT" -> "ETH"
                    currency.startswith(base_normalized + '_') or  # Starts with base: "ETH_USDT" starts with "ETH_"
                    currency.startswith(base_normalized + '/')  # Starts with base and slash: "ETH/USDT" starts with "ETH/"
                )
                
                if matches:
                    try:
                        position_balance = float(balance_str)
                        logger.debug(f"Found balance for {currency}: {position_balance}")
                        # Prefer a non-flat wallet (long or short); keep searching if dust.
                        if abs(position_balance) > 1e-12:
                            break
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Invalid balance format for {currency}: {balance_str}, error: {e}")
                        continue
            
            if abs(position_balance) <= 1e-12:
                available_currencies = [acc.get('currency') for acc in accounts[:10]]
                logger.warning(f"No open position found for {symbol}. Available currencies: {available_currencies}")
                return {
                    'success': False,
                    'error': f'No open position found for {symbol}. Please verify you have balance in {base_currency}.'
                }

            # Live wallet sign — prefer fills that match (ignore opposite dust fills).
            if position_balance > 0:
                wallet_entry_side = "BUY"
            elif position_balance < 0:
                wallet_entry_side = "SELL"
            else:
                wallet_entry_side = None
            
            # Get watchlist item (if exists) — try USD/USDT variants
            watchlist_item = None
            for variant in _entry_symbol_variants(symbol):
                watchlist_item = db.query(WatchlistItem).filter(
                    WatchlistItem.symbol == variant
                ).first()
                if watchlist_item:
                    if variant != symbol:
                        logger.info(
                            "Using watchlist item %s for ensure of %s",
                            variant,
                            symbol,
                        )
                    break
            
            # If no watchlist item, create one with default values
            if not watchlist_item:
                logger.info(f"Watchlist item not found for {symbol}, creating with default values")
                
                # Get current price for calculations (skip if async - will get from order instead)
                current_price = _fetch_mark_price(symbol)
                
                # Try to get entry price from most recent filled entry order
                entry_price = None
                try:
                    recent_order = _find_recent_entry_order(
                        db, symbol, side=wallet_entry_side
                    )
                    if recent_order:
                        entry_price = _order_entry_price(recent_order)
                        logger.info(f"Found entry price from recent order: {entry_price}")
                except Exception as e:
                    logger.warning(f"Could not get entry price from orders: {e}")
                
                # Use entry price if available, otherwise use current price
                purchase_price = entry_price or current_price
                
                # Create watchlist item with default values
                watchlist_item = WatchlistItem(
                    symbol=symbol,
                    exchange="CRYPTO_COM",
                    trade_enabled=False,
                    alert_enabled=False,
                    sl_tp_mode="conservative",
                    skip_sl_tp_reminder=False,
                    purchase_price=purchase_price,
                    price=current_price
                )
                db.add(watchlist_item)
                db.commit()
                logger.info(f"Created watchlist item for {symbol} with purchase_price={purchase_price}, current_price={current_price}")
            
            # Check if reminder was skipped
            if watchlist_item.skip_sl_tp_reminder and not force:
                return {
                    'success': False,
                    'error': f'SL/TP reminder skipped for {symbol} (use force=True to override)'
                }
            
            # Get SL/TP prices from watchlist
            sl_price = watchlist_item.sl_price
            tp_price = watchlist_item.tp_price
            prefer_tp_from_pct = (
                create_tp
                and watchlist_item.tp_percentage is not None
                and watchlist_item.tp_percentage > 0
            )
            # Absolute SL ages; if it is on the wrong side of market, force % recalculation.
            prefer_sl_from_pct = (
                create_sl
                and watchlist_item.sl_percentage is not None
                and watchlist_item.sl_percentage > 0
            )
            if create_sl and sl_price and prefer_sl_from_pct:
                try:
                    from app.utils.sl_trigger_guard import (
                        fetch_last_price,
                        is_sl_trigger_valid,
                    )

                    preview_side = wallet_entry_side or "BUY"
                    recent_for_side = _find_recent_entry_order(
                        db, symbol, side=wallet_entry_side
                    )
                    if recent_for_side:
                        preview_side = _entry_side_from_order(recent_for_side)
                    last = fetch_last_price(symbol)
                    if last and not is_sl_trigger_valid(
                        preview_side, float(sl_price), last
                    ):
                        logger.warning(
                            "Ignoring stale watchlist sl_price=%s for %s "
                            "(invalid vs last=%s); will recompute from sl_percentage=%s",
                            sl_price,
                            symbol,
                            last,
                            watchlist_item.sl_percentage,
                        )
                        sl_price = None
                except Exception as guard_err:
                    logger.debug(
                        "SL absolute-price guard skipped for %s: %s", symbol, guard_err
                    )
            
            # Calculate from percentages if prices not available, or when tp_percentage is set
            entry_price = None
            entry_side = wallet_entry_side or "BUY"
            need_sl_calc = create_sl and not sl_price
            need_tp_calc = create_tp and (not tp_price or prefer_tp_from_pct)
            if need_sl_calc or need_tp_calc:
                recent_order = _find_recent_entry_order(
                    db, symbol, side=wallet_entry_side
                )

                if recent_order:
                    entry_price = _order_entry_price(recent_order)
                    entry_side = _entry_side_from_order(recent_order)
                    if entry_price:
                        logger.info(
                            f"✅ Using entry price from filled {entry_side} order for {symbol}: "
                            f"{entry_price} (Order ID: {recent_order.exchange_order_id}, "
                            f"order_symbol={recent_order.symbol})"
                        )
                    else:
                        logger.warning(
                            f"⚠️ Filled {entry_side} order found for {symbol} but price is None "
                            f"(Order ID: {recent_order.exchange_order_id})"
                        )
                
                # 2. Fallback: use purchase_price from watchlist (only if no BUY order found)
                if not entry_price:
                    entry_price = watchlist_item.purchase_price
                    if entry_price:
                        logger.info(f"Using purchase_price from watchlist for {symbol}: {entry_price} (no filled BUY order found)")
                
                # 3. Last resort: use last known price from watchlist (only if no BUY order and no purchase_price)
                if not entry_price:
                    entry_price = watchlist_item.price
                    if entry_price:
                        logger.info(f"Using last known price from watchlist for {symbol}: {entry_price} (no filled BUY order or purchase_price found)")

                # 3b. Derive entry from absolute SL/TP + percentages (watchlist often has both)
                if not entry_price:
                    derived = _derive_entry_from_abs_prices(
                        entry_side=entry_side,
                        sl_price=watchlist_item.sl_price,
                        tp_price=watchlist_item.tp_price,
                        sl_percentage=watchlist_item.sl_percentage,
                        tp_percentage=watchlist_item.tp_percentage,
                    )
                    if derived:
                        entry_price = derived
                        logger.info(
                            "Derived entry price for %s from abs SL/TP + percentages: %s",
                            symbol,
                            entry_price,
                        )
                
                # 4. Final fallback: if we have an open position but no entry price, use current market price
                # This handles cases where position exists but order history is missing
                if not entry_price and abs(position_balance) > 1e-12:
                    try:
                        current_market_price = _fetch_mark_price(symbol)
                        if current_market_price and current_market_price > 0:
                            entry_price = current_market_price
                            logger.warning(
                                "⚠️ Using current market price as entry price for %s: %s "
                                "(position exists but no entry fill found in database)",
                                symbol,
                                entry_price,
                            )
                            # Update watchlist_item with current price for future use
                            watchlist_item.price = entry_price
                            if not watchlist_item.purchase_price:
                                watchlist_item.purchase_price = entry_price
                            db.commit()
                    except Exception as e:
                        logger.warning(f"Could not fetch current market price for {symbol}: {e}")
                
                if not entry_price:
                    # Prefer-tp-from-% but absolute prices already cover needed legs —
                    # keep abs prices rather than failing the whole ensure.
                    can_keep_abs = (
                        (not need_sl_calc or sl_price)
                        and (not create_tp or tp_price)
                    )
                    if can_keep_abs:
                        logger.warning(
                            "No entry price for %s; keeping existing absolute SL/TP "
                            "(sl=%s tp=%s) instead of failing ensure",
                            symbol,
                            sl_price,
                            tp_price,
                        )
                        need_sl_calc = False
                        need_tp_calc = False
                        # Order creators still require an entry_price argument — use mark.
                        entry_price = _fetch_mark_price(symbol)
                        if entry_price:
                            logger.info(
                                "Using mark price as entry metadata for %s: %s",
                                symbol,
                                entry_price,
                            )
                    else:
                        return {
                            'success': False,
                            'error': (
                                f'Cannot determine entry price for {symbol}. No filled entry order found in database. '
                                f'Please ensure there is a recent filled BUY or SELL entry order, or configure '
                                f'purchase_price/price in watchlist.'
                            )
                        }
                
                # Get strategy mode and percentages
                strategy_mode = watchlist_item.sl_tp_mode or "conservative"
                
                # Log what we're reading from watchlist
                logger.info(
                    f"Reading SL/TP settings for {symbol}: "
                    f"watchlist_sl_pct={watchlist_item.sl_percentage}, watchlist_tp_pct={watchlist_item.tp_percentage}, "
                    f"mode={strategy_mode}"
                )
                
                # Use configured percentages or defaults based on strategy
                # CRITICAL: Check for None and > 0 (0% would be invalid anyway)
                if watchlist_item.sl_percentage is not None and watchlist_item.sl_percentage > 0:
                    sl_percentage = abs(watchlist_item.sl_percentage)
                    logger.info(f"Using watchlist SL percentage: {sl_percentage}% (from watchlist: {watchlist_item.sl_percentage}%)")
                else:
                    # Default percentages based on strategy
                    sl_percentage = 3.0 if strategy_mode == "conservative" else 2.0
                    logger.info(f"Using default SL percentage: {sl_percentage}% (watchlist had: {watchlist_item.sl_percentage})")
                
                if watchlist_item.tp_percentage is not None and watchlist_item.tp_percentage > 0:
                    tp_percentage = abs(watchlist_item.tp_percentage)
                    logger.info(f"Using watchlist TP percentage: {tp_percentage}% (from watchlist: {watchlist_item.tp_percentage}%)")
                else:
                    # Default percentages based on strategy
                    tp_percentage = 3.0 if strategy_mode == "conservative" else 2.0
                    logger.info(f"Using default TP percentage: {tp_percentage}% (watchlist had: {watchlist_item.tp_percentage})")
                
                if entry_price and (need_sl_calc or need_tp_calc):
                    logger.info(f"Calculating SL/TP for {symbol}: entry_price={entry_price}, entry_side={entry_side}, strategy={strategy_mode}, sl_percentage={sl_percentage}%, tp_percentage={tp_percentage}%")
                    
                    # Calculate SL/TP from entry price using strategy percentages (side-aware)
                    if need_sl_calc:
                        sl_price, _ = _compute_sl_tp_from_entry(entry_price, entry_side, sl_percentage, tp_percentage)
                        logger.info(f"Calculated SL price for {symbol}: {sl_price} (entry: {entry_price}, side={entry_side}, {sl_percentage}%)")
                    
                    if need_tp_calc:
                        _, tp_price = _compute_sl_tp_from_entry(entry_price, entry_side, sl_percentage, tp_percentage)
                        logger.info(
                            f"Calculated TP price for {symbol}: {tp_price} "
                            f"(entry: {entry_price}, side={entry_side}, {tp_percentage}%, "
                            f"prefer_pct={prefer_tp_from_pct})"
                        )
            
            # Round prices to reasonable precision before passing to exchange
            # The exchange will further format according to instrument tick size
            if sl_price:
                # Round to 4 decimals for prices < 100, 2 decimals for prices >= 100
                sl_price = round(sl_price, 2) if sl_price >= 100 else round(sl_price, 4)
            if tp_price:
                # Round to 4 decimals for prices < 100, 2 decimals for prices >= 100
                tp_price = round(tp_price, 2) if tp_price >= 100 else round(tp_price, 4)
            
            live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
            dry_run_mode = not live_trading
            
            # Ensure entry_price is available for order creation (even if prices were already set)
            entry_side = wallet_entry_side or "BUY"
            if not entry_price:
                recent_order = _find_recent_entry_order(
                    db, symbol, side=wallet_entry_side
                )
                if recent_order:
                    entry_price = _order_entry_price(recent_order)
                    entry_side = _entry_side_from_order(recent_order)
                    if entry_price:
                        logger.info(
                            f"✅ Using entry price from filled {entry_side} order for {symbol}: "
                            f"{entry_price} (Order ID: {recent_order.exchange_order_id})"
                        )
            if not entry_price:
                entry_price = (
                    watchlist_item.purchase_price
                    or watchlist_item.price
                    or _fetch_mark_price(symbol)
                )
            
            # Get parent order ID from most recent wallet-matching fill (for linking TP/SL)
            parent_order_id = None
            parent_order = None
            oco_group_id = None
            if entry_price:
                try:
                    recent_order = _find_recent_entry_order(
                        db, symbol, side=wallet_entry_side
                    )
                    if recent_order:
                        parent_order = recent_order
                        parent_order_id = recent_order.exchange_order_id
                        entry_side = (
                            _entry_side_from_order(recent_order)
                            or wallet_entry_side
                            or entry_side
                        )
                        # Generate OCO group ID for linking SL and TP orders
                        import uuid
                        oco_group_id = (
                            f"oco_{parent_order_id}_"
                            f"{int(datetime.utcnow().timestamp())}"
                        )
                        logger.info(
                            f"Found parent order {parent_order_id} for {symbol}, "
                            f"using OCO group: {oco_group_id}"
                        )
                    elif wallet_entry_side:
                        entry_side = wallet_entry_side
                except Exception as e:
                    logger.warning(f"Could not get parent order ID for {symbol}: {e}")
            elif wallet_entry_side:
                entry_side = wallet_entry_side

            # Size legs to parent lot (not full wallet) when linked; never exceed wallet.
            protection_qty = _protection_create_qty(
                position_balance=position_balance,
                parent_order=parent_order,
            )
            if parent_order and abs(protection_qty - float(position_balance)) > 1e-12:
                logger.info(
                    "Using parent lot qty %s (wallet %s) for %s protection "
                    "(parent %s)",
                    protection_qty,
                    position_balance,
                    symbol,
                    parent_order_id,
                )

            # Skip creating a wallet-duplicate leg when sister-book / multi-lot
            # protections already cover the bag (USD TPs covering BTC_USDT ensure).
            sister_variants = _entry_symbol_variants(symbol)
            if create_tp and _db_protection_covers_wallet(
                db, sister_variants, "TAKE_PROFIT", position_balance
            ):
                logger.info(
                    "Skipping TP create for %s: active sister/lot TPs already "
                    "cover wallet %s",
                    symbol,
                    position_balance,
                )
                create_tp = False
            if create_sl and _db_protection_covers_wallet(
                db, sister_variants, "STOP_LOSS", position_balance
            ):
                logger.info(
                    "Skipping SL create for %s: active sister/lot SLs already "
                    "cover wallet %s",
                    symbol,
                    position_balance,
                )
                create_sl = False
            
            # Use the reusable TP/SL order creator functions (same as automatic creation)
            from app.services.sl_tp_protection import (
                get_active_protection_order,
                should_skip_rejected_tp_backfill,
            )
            from app.services.tp_sl_order_creator import (
                ensure_spot_oco_protection,
                is_native_oco_enabled,
                resolve_sltp_margin_context,
            )

            if parent_order_id and should_skip_rejected_tp_backfill(
                db, parent_order_id, symbol=symbol
            ):
                logger.info(
                    "Skipping ensure TP backfill for %s parent=%s: REJECTED TP with active SL",
                    symbol,
                    parent_order_id,
                )
                create_tp = False
                if not create_sl:
                    return {
                        "success": True,
                        "symbol": symbol,
                        "sl_order_id": None,
                        "tp_order_id": None,
                        "skip_reason": "tp_rejected_terminal",
                    }

            existing_sl = (
                get_active_protection_order(db, parent_order_id, "STOP_LOSS")
                if parent_order_id
                else None
            )
            existing_tp = (
                get_active_protection_order(db, parent_order_id, "TAKE_PROFIT")
                if parent_order_id
                else None
            )

            # Spot: prefer ONE native OCO whenever both prices are known and we
            # would otherwise create two independent full-qty triggers (or backfill
            # a missing leg while the other locks qty).
            is_margin, _leverage = resolve_sltp_margin_context(db, symbol)
            need_sl = bool(create_sl and sl_price and entry_price and protection_qty > 0)
            need_tp = bool(create_tp and tp_price and entry_price and protection_qty > 0)
            want_both_or_heal = (
                (need_sl and need_tp)
                or (need_tp and existing_sl and not existing_tp)
                or (need_sl and existing_tp and not existing_sl)
            )
            if (
                want_both_or_heal
                and not is_margin
                and is_native_oco_enabled()
                and sl_price
                and tp_price
                and entry_price
                and protection_qty > 0
            ):
                oco_res = ensure_spot_oco_protection(
                    db=db,
                    symbol=symbol,
                    side=entry_side,
                    tp_price=float(tp_price),
                    sl_price=float(sl_price),
                    quantity=float(protection_qty),
                    entry_price=float(entry_price),
                    parent_order_id=parent_order_id,
                    dry_run=dry_run_mode,
                    source=source,
                    existing_sl=existing_sl,
                    existing_tp=existing_tp,
                )
                if oco_res.get("status") == "already_protected" or (
                    not oco_res.get("error")
                    and not oco_res.get("skipped")
                    and (
                        (oco_res.get("sl_result") or {}).get("order_id")
                        or oco_res.get("oco_group_id")
                    )
                ):
                    sl_order_id = (oco_res.get("sl_result") or {}).get("order_id")
                    tp_order_id = (oco_res.get("tp_result") or {}).get("order_id")
                    return {
                        "success": True,
                        "symbol": symbol,
                        "sl_order_id": sl_order_id,
                        "tp_order_id": tp_order_id,
                        "oco_group_id": oco_res.get("oco_group_id"),
                        "sl_newly_created": bool(oco_res.get("sl_newly_created")),
                        "tp_newly_created": bool(oco_res.get("tp_newly_created")),
                        "status": oco_res.get("status") or "oco_created",
                    }
                logger.error(
                    "Native OCO ensure failed for %s: %s — refusing dual create-order on spot",
                    symbol,
                    oco_res.get("error"),
                )
                return {
                    "success": False,
                    "symbol": symbol,
                    "sl_order_id": existing_sl.exchange_order_id if existing_sl else None,
                    "tp_order_id": existing_tp.exchange_order_id if existing_tp else None,
                    "error": oco_res.get("error") or "native_oco_failed",
                }

            # Margin (and spot without OCO): never place SL then independent TP —
            # that locks qty and yields INSUFFICIENT_ACC_BALANCE. Reuse the shared
            # TP-before-SL / cancel-SL-first implementation.
            if (
                want_both_or_heal
                and is_margin
                and not dry_run_mode
                and entry_price
                and protection_qty > 0
                and parent_order_id
                and (sl_price or existing_sl)
                and (tp_price or existing_tp)
            ):
                from app.services.exchange_sync import ExchangeSyncService

                impl = ExchangeSyncService()._create_sl_tp_impl(
                    db=db,
                    symbol=symbol,
                    side_upper=(entry_side or "BUY").upper(),
                    filled_price_f=float(entry_price),
                    filled_qty=float(protection_qty),
                    order_id=str(parent_order_id),
                    source=source,
                    strict_percentages=False,
                    sl_price_override_f=float(sl_price) if sl_price else None,
                    tp_price_override_f=float(tp_price) if tp_price else None,
                )
                sl_res = impl.get("sl_result") or {}
                tp_res = impl.get("tp_result") or {}
                ok = bool(sl_res.get("order_id") or tp_res.get("order_id") or impl.get("status") == "already_protected")
                return {
                    "success": ok,
                    "symbol": symbol,
                    "sl_order_id": sl_res.get("order_id"),
                    "tp_order_id": tp_res.get("order_id"),
                    "oco_group_id": impl.get("oco_group_id"),
                    "sl_newly_created": bool(impl.get("sl_newly_created")),
                    "tp_newly_created": bool(impl.get("tp_newly_created")),
                    "status": impl.get("status") or ("margin_dual" if ok else "margin_dual_failed"),
                    "error": sl_res.get("error") or tp_res.get("error"),
                    "skip_tp_reason": impl.get("skip_tp_reason"),
                }

            # Create SL order if requested
            sl_order_id = None
            sl_error = None
            sl_newly_created = False
            if need_sl:
                if existing_sl:
                    sl_order_id = existing_sl.exchange_order_id
                    logger.info(
                        "Reusing existing SL %s for %s (parent %s)",
                        sl_order_id,
                        symbol,
                        parent_order_id,
                    )
                else:
                    sl_result = create_stop_loss_order(
                        db=db,
                        symbol=symbol,
                        side=entry_side,
                        sl_price=sl_price,
                        quantity=protection_qty,
                        entry_price=entry_price,
                        parent_order_id=parent_order_id,
                        oco_group_id=oco_group_id,
                        dry_run=dry_run_mode,
                        source=source,
                        sl_percentage=(
                            float(watchlist_item.sl_percentage)
                            if watchlist_item.sl_percentage is not None
                            else None
                        ),
                    )
                    sl_order_id = sl_result.get("order_id")
                    sl_error = sl_result.get("error")
                    sl_newly_created = bool(sl_order_id)
            
            # Create TP order if requested
            tp_order_id = None
            tp_error = None
            tp_newly_created = False
            if need_tp:
                if existing_tp:
                    tp_order_id = existing_tp.exchange_order_id
                    logger.info(
                        "Reusing existing TP %s for %s (parent %s)",
                        tp_order_id,
                        symbol,
                        parent_order_id,
                    )
                else:
                    tp_result = create_take_profit_order(
                        db=db,
                        symbol=symbol,
                        side=entry_side,
                        tp_price=tp_price,
                        quantity=protection_qty,
                        entry_price=entry_price,
                        parent_order_id=parent_order_id,
                        oco_group_id=oco_group_id,
                        dry_run=dry_run_mode,
                        source=source,
                    )
                    tp_order_id = tp_result.get("order_id")
                    tp_error = tp_result.get("error")
                    tp_newly_created = bool(tp_order_id)
            
            # BR-3: ATOMIC ROLLBACK - only roll back legs newly created in this call.
            # Never cancel a pre-existing reused SL/TP when the other leg fails.
            if create_sl and create_tp:
                if sl_newly_created and sl_order_id and not tp_order_id:
                    # SL created but TP failed - ROLLBACK: cancel SL
                    logger.error(f"🚨 ATOMIC TP/SL VIOLATION: SL created but TP failed for {symbol}. Rolling back SL order {sl_order_id}.")
                    try:
                        cancel_result = trade_client.cancel_order(sl_order_id)
                        if "error" in cancel_result:
                            logger.error(f"❌ Failed to cancel SL order {sl_order_id} during rollback: {cancel_result.get('error')}")
                        else:
                            logger.info(f"✅ Rolled back SL order {sl_order_id} after TP creation failed")
                            sl_order_id = None  # Mark as rolled back
                            sl_newly_created = False
                    except Exception as cancel_err:
                        logger.error(f"❌ Exception during SL rollback for {symbol}: {cancel_err}", exc_info=True)
                    
                    # Emit SLTP_FAILED event with explicit reason (BR-4)
                    try:
                        from app.services.signal_monitor import _emit_lifecycle_event
                        from app.services.strategy_profiles import build_strategy_key
                        watchlist_for_event = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
                        strategy_key = build_strategy_key(watchlist_for_event) if watchlist_for_event else "unknown:unknown"
                        
                        error_msg = f"TP creation failed: {tp_error or 'unknown error'}"
                        _emit_lifecycle_event(
                            db=db,
                            symbol=symbol,
                            strategy_key=strategy_key,
                            side="BUY",
                            price=entry_price,
                            event_type="SLTP_FAILED",
                            event_reason="ATOMIC_VIOLATION_TP_FAILED_SL_ROLLED_BACK",
                            error_message=error_msg,
                        )
                    except Exception as emit_err:
                        logger.warning(f"Failed to emit SLTP_FAILED event for {symbol}: {emit_err}")
                        
                elif tp_newly_created and tp_order_id and not sl_order_id:
                    # TP created but SL failed - ROLLBACK: cancel TP
                    logger.error(f"🚨 ATOMIC TP/SL VIOLATION: TP created but SL failed for {symbol}. Rolling back TP order {tp_order_id}.")
                    try:
                        cancel_result = trade_client.cancel_order(tp_order_id)
                        if "error" in cancel_result:
                            logger.error(f"❌ Failed to cancel TP order {tp_order_id} during rollback: {cancel_result.get('error')}")
                        else:
                            logger.info(f"✅ Rolled back TP order {tp_order_id} after SL creation failed")
                            tp_order_id = None  # Mark as rolled back
                            tp_newly_created = False
                    except Exception as cancel_err:
                        logger.error(f"❌ Exception during TP rollback for {symbol}: {cancel_err}", exc_info=True)
                    
                    # Emit SLTP_FAILED event with explicit reason (BR-4)
                    try:
                        from app.services.signal_monitor import _emit_lifecycle_event
                        from app.services.strategy_profiles import build_strategy_key
                        watchlist_for_event = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
                        strategy_key = build_strategy_key(watchlist_for_event) if watchlist_for_event else "unknown:unknown"
                        
                        error_msg = f"SL creation failed: {sl_error or 'unknown error'}"
                        _emit_lifecycle_event(
                            db=db,
                            symbol=symbol,
                            strategy_key=strategy_key,
                            side="BUY",
                            price=entry_price,
                            event_type="SLTP_FAILED",
                            event_reason="ATOMIC_VIOLATION_SL_FAILED_TP_ROLLED_BACK",
                            error_message=error_msg,
                        )
                    except Exception as emit_err:
                        logger.warning(f"Failed to emit SLTP_FAILED event for {symbol}: {emit_err}")
            
            # Notify only when at least one leg was newly created this call.
            if sl_newly_created or tp_newly_created:
                try:
                    from app.services.telegram_event_dedup import claim_telegram_event

                    claim_id = parent_order_id or symbol
                    if tp_newly_created and not sl_newly_created:
                        claim_key = f"sl_tp_created:ensure:{claim_id}:tp_ok"
                    else:
                        claim_key = f"sl_tp_created:ensure:{claim_id}"
                    if not claim_telegram_event(
                        db,
                        claim_key,
                        symbol=symbol,
                        ttl_minutes=7 * 24 * 60,
                        action="sl_tp_created",
                    ):
                        logger.info(
                            "📢 Skipping ensure SL/TP Telegram for %s: already claimed %s",
                            symbol,
                            claim_key,
                        )
                    else:
                        # Get percentages from watchlist or calculate from prices
                        sl_pct = watchlist_item.sl_percentage if watchlist_item.sl_percentage else None
                        tp_pct = watchlist_item.tp_percentage if watchlist_item.tp_percentage else None

                        # If percentages not set, calculate from entry price and SL/TP prices
                        if entry_price and entry_price > 0:
                            if not sl_pct and sl_price:
                                sl_pct = abs((entry_price - sl_price) / entry_price * 100)
                            if not tp_pct and tp_price:
                                tp_pct = abs((tp_price - entry_price) / entry_price * 100)

                        exit_side = "SELL" if entry_side == "BUY" else "BUY"
                        telegram_notifier.send_sl_tp_orders(
                            symbol=symbol,
                            sl_price=sl_price,
                            tp_price=tp_price,
                            quantity=protection_qty,
                            mode=watchlist_item.sl_tp_mode or "conservative",
                            sl_order_id=str(sl_order_id) if sl_order_id else None,
                            tp_order_id=str(tp_order_id) if tp_order_id else None,
                            original_order_id=parent_order_id,
                            entry_price=entry_price,
                            sl_percentage=sl_pct,
                            tp_percentage=tp_pct,
                            original_order_side=entry_side,
                            sl_side=exit_side,
                            tp_side=exit_side,
                            sl_newly_created=sl_newly_created,
                            tp_newly_created=tp_newly_created,
                        )
                        logger.info(f"✅ Sent Telegram notification for SL/TP orders: {symbol} - SL: {sl_order_id}, TP: {tp_order_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to send Telegram notification for SL/TP orders: {symbol} - {e}", exc_info=True)
            
            # BR-3: ATOMIC SUCCESS CHECK - If both SL and TP were requested, both must succeed
            if create_sl and create_tp:
                # Both requested - both must succeed
                success = bool(sl_order_id and tp_order_id)
            else:
                # Only one requested (or neither) - success if requested one succeeded
                success = (create_sl and sl_order_id) or (create_tp and tp_order_id) or (not create_sl and not create_tp)
            
            # If there's an error and no success, include it in the main error field
            main_error = None
            if not success:
                if create_sl and create_tp:
                    # Both requested - failure means one or both failed
                    if not sl_order_id and not tp_order_id:
                        main_error = f"Both SL and TP orders failed. SL: {sl_error or 'unknown'}, TP: {tp_error or 'unknown'}"
                    elif not sl_order_id:
                        main_error = f"SL order failed: {sl_error or 'unknown'} (TP was rolled back)"
                    elif not tp_order_id:
                        main_error = f"TP order failed: {tp_error or 'unknown'} (SL was rolled back)"
                elif create_sl and sl_error:
                    main_error = f"SL order failed: {sl_error}"
                elif create_tp and tp_error:
                    main_error = f"TP order failed: {tp_error}"
                elif create_sl and not sl_order_id:
                    main_error = sl_error or "SL order creation failed (unknown reason)"
                elif create_tp and not tp_order_id:
                    main_error = tp_error or "TP order creation failed (unknown reason)"
            
            return {
                'success': success,
                'symbol': symbol,
                'sl_order_id': sl_order_id,
                'tp_order_id': tp_order_id,
                'sl_error': sl_error,
                'tp_error': tp_error,
                'error': main_error,  # Add main error field for easier access
                'dry_run': dry_run_mode
            }
            
        except Exception as e:
            logger.error(f"Error creating protection order for position {symbol}: {e}", exc_info=True)
            error_msg = str(e)
            # Provide more specific error message
            if "Watchlist item not found" in error_msg:
                return {
                    'success': False,
                    'error': f'Watchlist item not found for {symbol}. First add {symbol} to watchlist.'
                }
            elif "No open position" in error_msg:
                return {
                    'success': False,
                    'error': error_msg  # Already has good message
                }
            else:
                return {
                    'success': False,
                    'error': f'Error creating order: {error_msg}'
                }
    
    def create_sl_tp_for_position(self, db: Session, symbol: str, force: bool = False) -> Dict:
        """
        Create both SL and TP orders for a specific position
        
        Args:
            db: Database session
            symbol: Trading symbol (e.g., ETH_USDT)
            force: If True, create even if skip_reminder is set
        
        Returns:
            Dict with creation results
        """
        return self._create_protection_order(db, symbol, create_sl=True, create_tp=True, force=force)
    
    def skip_reminder_for_symbol(self, db: Session, symbol: str) -> bool:
        """Mark symbol to skip SL/TP reminders"""
        try:
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).first()
            
            if not watchlist_item:
                # Create watchlist item if it doesn't exist
                watchlist_item = WatchlistItem(
                    symbol=symbol,
                    exchange="CRYPTO_COM",
                    skip_sl_tp_reminder=True
                )
                db.add(watchlist_item)
            else:
                watchlist_item.skip_sl_tp_reminder = True
            
            db.commit()
            logger.info(f"Marked {symbol} to skip SL/TP reminders")
            return True
            
        except Exception as e:
            logger.error(f"Error skipping reminder for {symbol}: {e}")
            db.rollback()
            return False


# Global instance
sl_tp_checker_service = SLTPCheckerService()

