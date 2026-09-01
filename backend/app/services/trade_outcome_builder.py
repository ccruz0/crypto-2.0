"""Build round-trip trade outcome labels from existing order tables (Phase 1a).

Join path (design ADR closed-loop Phase 1):
  telegram_messages.id
    ← order_intents.signal_id
    ← order_intents.order_id = exchange_orders.exchange_order_id (entry)
    ← exchange_orders where parent_order_id = entry (SL/TP children)
    ← optional orphan opposite MARKET/LIMIT fill (null parent_order_id)

Incomplete joins are dropped. Coverage counters are returned for operators.
Pure helpers accept dict-shaped rows so unit tests need no live DB.
Does NOT wire Auto ML promote (Phase 1b).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional, Sequence

from app.utils.dry_run_orders import is_dry_run_order_id
from app.utils.ops_stub_orders import is_ops_stub_closed_order_id


EXIT_ROLES = frozenset({"STOP_LOSS", "TAKE_PROFIT"})
FILLED_STATUSES = frozenset(
    {"FILLED", "PARTIALLY_FILLED"}  # PARTIALLY_FILLED treated as usable exit if price present
)
ENTRY_INTENT_STATUSES = frozenset({"ORDER_PLACED"})
ORPHAN_EXIT_ORDER_TYPES = frozenset({"MARKET", "LIMIT"})
ACTIVE_PROTECTION_STATUSES = frozenset(
    {"ACTIVE", "NEW", "PENDING", "OPEN", "TRIGGERED", "PARTIALLY_FILLED"}
)
# Orphan flatten/manual close: opposite filled MARKET/LIMIT, null parent, qty+time gates.
DEFAULT_ORPHAN_EXIT_WINDOW_DAYS = 14
DEFAULT_ORPHAN_QTY_TOLERANCE = 0.05  # relative |Δqty| / max(entry, exit)


@dataclass
class CoverageStats:
    intents_considered: int = 0
    complete: int = 0
    with_alert: int = 0
    without_alert: int = 0
    short_close_supplemented: int = 0
    dropped: dict[str, int] = field(
        default_factory=lambda: {
            "dry_run_order_id": 0,
            "missing_order_id": 0,
            "missing_entry_order": 0,
            "entry_not_filled": 0,
            "missing_entry_price": 0,
            # Former missing_exit_fill split for ops visibility (no attribution change).
            "still_open": 0,
            "protection_cancelled_no_exit": 0,
            "no_children": 0,
            "orphan_rejected_by_guards": 0,
            "missing_exit_price": 0,
            "missing_quantity": 0,
            "short_close_existing": 0,
            "short_close_missing_parent": 0,
            "short_close_invalid": 0,
        }
    )

    def join_coverage_pct(self) -> float:
        if self.intents_considered <= 0:
            return 0.0
        return round(100.0 * self.complete / self.intents_considered, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "intents_considered": self.intents_considered,
            "complete": self.complete,
            "with_alert": self.with_alert,
            "without_alert": self.without_alert,
            "short_close_supplemented": self.short_close_supplemented,
            "join_coverage_pct": self.join_coverage_pct(),
            "dropped": dict(self.dropped),
        }


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    s = str(value).strip()
    return s or None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, (int, float)):
        # Heuristic: ms vs s
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def infer_exit_role(
    *,
    order_role: Any = None,
    order_type: Any = None,
) -> Optional[str]:
    """Map child order_role / order_type to TAKE_PROFIT or STOP_LOSS."""
    role = (_as_str(order_role) or "").upper()
    if role in EXIT_ROLES:
        return role
    ot = (_as_str(order_type) or "").upper()
    if "TAKE_PROFIT" in ot:
        return "TAKE_PROFIT"
    if ot in ("STOP_LOSS", "STOP_LIMIT", "STOP_MARKET", "STOP_LOSS_LIMIT") or "STOP" in ot:
        return "STOP_LOSS"
    return None


def order_fill_price(order: Mapping[str, Any]) -> Optional[float]:
    return _as_float(order.get("avg_price") if order.get("avg_price") is not None else order.get("price"))


def order_qty(order: Mapping[str, Any]) -> Optional[float]:
    qty = _as_float(order.get("cumulative_quantity"))
    if qty is not None and qty > 0:
        return qty
    return _as_float(order.get("quantity"))


def order_event_ts(order: Mapping[str, Any]) -> Optional[datetime]:
    return (
        _as_dt(order.get("exchange_update_time"))
        or _as_dt(order.get("exchange_create_time"))
        or _as_dt(order.get("updated_at"))
        or _as_dt(order.get("created_at"))
    )


def is_filled_status(status: Any) -> bool:
    s = (_as_str(status) or "").upper()
    return s in FILLED_STATUSES or s == "FILLED"


def compute_pnl(
    *,
    side: str,
    entry_price: float,
    exit_price: float,
    quantity: float,
) -> tuple[float, float]:
    """Return (pnl_usd, pnl_pct). Side is entry side."""
    side_u = side.upper()
    if side_u == "BUY":
        pnl_usd = (exit_price - entry_price) * quantity
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0 if entry_price else 0.0
    else:
        pnl_usd = (entry_price - exit_price) * quantity
        pnl_pct = ((entry_price - exit_price) / entry_price) * 100.0 if entry_price else 0.0
    return pnl_usd, pnl_pct


def select_exit_child(children: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    """Prefer earliest filled SL/TP child by event timestamp.

    Skips ops STUB-CLOSED-* ids (not real fills; weak/zero PnL train labels).
    """
    filled: list[tuple[datetime, Mapping[str, Any]]] = []
    for child in children:
        child_oid = _as_str(child.get("exchange_order_id"))
        if is_ops_stub_closed_order_id(child_oid):
            continue
        role = infer_exit_role(order_role=child.get("order_role"), order_type=child.get("order_type"))
        if role is None:
            continue
        if not is_filled_status(child.get("status")):
            continue
        if order_fill_price(child) is None:
            continue
        ts = order_event_ts(child) or datetime.min.replace(tzinfo=timezone.utc)
        filled.append((ts, child))
    if not filled:
        return None
    filled.sort(key=lambda x: x[0])
    return filled[0][1]


def select_flatten_child(children: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    """Earliest FILLED child tagged order_role=FLATTEN with a usable fill price.

    A flatten/manual close correctly tagged with parent_order_id was invisible
    before 28-ago-2026: infer_exit_role only maps SL/TP (so select_exit_child
    skipped it) and the orphan path requires parent_order_id IS NULL (so the
    tag itself disqualified it). The untagged version of the same economic
    event DID join via the orphan path — the code rewarded missing metadata.
    Verified against production: 16 MANUAL_OR_FLATTEN rows, all via_orphan,
    while 4 correctly-tagged XRP flatten closes were dropped as no_children.
    """
    filled: list[tuple[datetime, Mapping[str, Any]]] = []
    for child in children:
        child_oid = _as_str(child.get("exchange_order_id"))
        if is_ops_stub_closed_order_id(child_oid):
            continue
        role = (_as_str(child.get("order_role")) or "").upper()
        if role != "FLATTEN":
            continue
        if not is_filled_status(child.get("status")):
            continue
        if order_fill_price(child) is None:
            continue
        ts = order_event_ts(child) or datetime.min.replace(tzinfo=timezone.utc)
        filled.append((ts, child))
    if not filled:
        return None
    filled.sort(key=lambda x: x[0])
    return filled[0][1]


def _opposite_side(side: str) -> str:
    return "SELL" if side.upper() == "BUY" else "BUY"


def _qty_within_tolerance(
    entry_qty: float,
    exit_qty: float,
    *,
    tolerance: float = DEFAULT_ORPHAN_QTY_TOLERANCE,
) -> bool:
    if entry_qty <= 0 or exit_qty <= 0:
        return False
    denom = max(entry_qty, exit_qty)
    return abs(entry_qty - exit_qty) / denom <= tolerance


def _is_orphan_exit_order_type(order_type: Any) -> bool:
    ot = (_as_str(order_type) or "").upper()
    if not ot:
        return False
    # Exact MARKET/LIMIT only — avoid STOP_*/TAKE_PROFIT_* even if loosely named.
    return ot in ORPHAN_EXIT_ORDER_TYPES


def has_active_protection_children(children: Sequence[Mapping[str, Any]]) -> bool:
    """True when SL/TP children are still working (position likely still open)."""
    for child in children:
        role = infer_exit_role(order_role=child.get("order_role"), order_type=child.get("order_type"))
        if role is None:
            continue
        status = (_as_str(child.get("status")) or "").upper()
        if status in ACTIVE_PROTECTION_STATUSES:
            return True
    return False


def has_protection_role_children(children: Sequence[Mapping[str, Any]]) -> bool:
    """True when any child maps to STOP_LOSS / TAKE_PROFIT (any status)."""
    for child in children:
        if infer_exit_role(order_role=child.get("order_role"), order_type=child.get("order_type")):
            return True
    return False


def has_loose_orphan_opposite(
    *,
    entry: Mapping[str, Any],
    entry_side: str,
    entry_ts: Optional[datetime],
    candidates: Sequence[Mapping[str, Any]],
) -> bool:
    """True if an opposite FILLED MARKET/LIMIT exists after entry (diag only).

    Intentionally looser than select_orphan_exit: ignores qty, window end,
    claimed ids, and parented rows. Used only to bucket drops as
    orphan_rejected_by_guards — does NOT attribute or loosen COMPLETE guards.
    """
    if entry_ts is None:
        return False
    entry_symbol = (_as_str(entry.get("symbol")) or "").upper()
    entry_oid = _as_str(entry.get("exchange_order_id"))
    want_side = _opposite_side(entry_side)
    for cand in candidates:
        cand_oid = _as_str(cand.get("exchange_order_id"))
        if not cand_oid or cand_oid == entry_oid:
            continue
        if is_dry_run_order_id(cand_oid) or is_ops_stub_closed_order_id(cand_oid):
            continue
        if (_as_str(cand.get("symbol")) or "").upper() != entry_symbol:
            continue
        if (_as_str(cand.get("side")) or "").upper() != want_side:
            continue
        if not is_filled_status(cand.get("status")):
            continue
        if not _is_orphan_exit_order_type(cand.get("order_type")):
            continue
        if infer_exit_role(order_role=cand.get("order_role"), order_type=cand.get("order_type")):
            continue
        cand_ts = order_event_ts(cand)
        if cand_ts is None or cand_ts <= entry_ts:
            continue
        return True
    return False


def classify_missing_exit_fill(
    *,
    entry: Mapping[str, Any],
    entry_side: str,
    entry_ts: Optional[datetime],
    children: Sequence[Mapping[str, Any]],
    orphan_candidates: Sequence[Mapping[str, Any]] = (),
) -> str:
    """Bucket why a filled entry produced no COMPLETE exit (coverage only)."""
    if has_active_protection_children(children):
        return "still_open"
    if has_loose_orphan_opposite(
        entry=entry,
        entry_side=entry_side,
        entry_ts=entry_ts,
        candidates=orphan_candidates,
    ):
        return "orphan_rejected_by_guards"
    if has_protection_role_children(children):
        return "protection_cancelled_no_exit"
    return "no_children"


def select_orphan_exit(
    *,
    entry: Mapping[str, Any],
    entry_side: str,
    entry_qty: float,
    entry_ts: Optional[datetime],
    candidates: Sequence[Mapping[str, Any]],
    claimed_exit_ids: Optional[set[str]] = None,
    window_days: int = DEFAULT_ORPHAN_EXIT_WINDOW_DAYS,
    qty_tolerance: float = DEFAULT_ORPHAN_QTY_TOLERANCE,
) -> Optional[Mapping[str, Any]]:
    """First opposite-side FILLED MARKET/LIMIT after entry, qty+time gated.

    Requires null parent_order_id. Rejects dry-run / stub ids and SL/TP-typed rows.
    Does not take a naive first-opposite without qty/time checks.
    """
    if entry_ts is None or entry_qty <= 0:
        return None
    claimed = claimed_exit_ids or set()
    entry_symbol = (_as_str(entry.get("symbol")) or "").upper()
    entry_oid = _as_str(entry.get("exchange_order_id"))
    want_side = _opposite_side(entry_side)
    window_end = entry_ts + timedelta(days=window_days)

    matched: list[tuple[datetime, Mapping[str, Any]]] = []
    for cand in candidates:
        cand_oid = _as_str(cand.get("exchange_order_id"))
        if not cand_oid or cand_oid == entry_oid or cand_oid in claimed:
            continue
        if is_dry_run_order_id(cand_oid) or is_ops_stub_closed_order_id(cand_oid):
            continue
        if (_as_str(cand.get("parent_order_id")) or "").strip():
            continue
        if (_as_str(cand.get("symbol")) or "").upper() != entry_symbol:
            continue
        if (_as_str(cand.get("side")) or "").upper() != want_side:
            continue
        if not is_filled_status(cand.get("status")):
            continue
        if not _is_orphan_exit_order_type(cand.get("order_type")):
            continue
        # Linked SL/TP roles must go through select_exit_child, not orphan path.
        if infer_exit_role(order_role=cand.get("order_role"), order_type=cand.get("order_type")):
            continue
        if order_fill_price(cand) is None:
            continue
        cand_qty = order_qty(cand)
        if cand_qty is None or not _qty_within_tolerance(
            entry_qty, cand_qty, tolerance=qty_tolerance
        ):
            continue
        cand_ts = order_event_ts(cand)
        if cand_ts is None or cand_ts <= entry_ts or cand_ts > window_end:
            continue
        matched.append((cand_ts, cand))

    if not matched:
        return None
    matched.sort(key=lambda x: x[0])
    return matched[0][1]


def build_outcome_for_intent(
    intent: Mapping[str, Any],
    *,
    entry: Optional[Mapping[str, Any]],
    children: Sequence[Mapping[str, Any]],
    alert: Optional[Mapping[str, Any]] = None,
    orphan_candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    claimed_exit_ids: Optional[set[str]] = None,
    orphan_window_days: int = DEFAULT_ORPHAN_EXIT_WINDOW_DAYS,
    orphan_qty_tolerance: float = DEFAULT_ORPHAN_QTY_TOLERANCE,
    stats: Optional[CoverageStats] = None,
) -> Optional[dict[str, Any]]:
    """Join one ORDER_PLACED intent to entry + exit; return COMPLETE row or None."""
    if stats is not None:
        stats.intents_considered += 1

    def drop(reason: str) -> None:
        if stats is not None:
            stats.dropped[reason] = stats.dropped.get(reason, 0) + 1

    order_id = _as_str(intent.get("order_id"))
    if not order_id:
        drop("missing_order_id")
        return None
    if is_dry_run_order_id(order_id):
        # Defensive: callers should filter these from the eligible set first.
        drop("dry_run_order_id")
        return None
    if entry is None:
        drop("missing_entry_order")
        return None
    if not is_filled_status(entry.get("status")):
        drop("entry_not_filled")
        return None

    entry_price = order_fill_price(entry)
    if entry_price is None or entry_price <= 0:
        drop("missing_entry_price")
        return None

    side = (_as_str(intent.get("side")) or _as_str(entry.get("side")) or "BUY").upper()
    entry_ts = order_event_ts(entry)
    qty = order_qty(entry)

    exit_order: Optional[Mapping[str, Any]] = select_exit_child(children)
    exit_reason: Optional[str] = None
    exit_via_orphan = False

    if exit_order is not None:
        exit_reason = infer_exit_role(
            order_role=exit_order.get("order_role"), order_type=exit_order.get("order_type")
        ) or "UNKNOWN"
    elif (flatten_child := select_flatten_child(children)) is not None:
        # Tagged flatten wins over the still-open check on purpose: a FILLED
        # flatten means the position IS closed even if a protection leg still
        # shows ACTIVE because sibling-cancel lagged.
        exit_order = flatten_child
        exit_reason = "MANUAL_OR_FLATTEN"
    elif not has_active_protection_children(children):
        # No filled linked SL/TP and not still-open → try orphan MARKET/LIMIT flatten.
        if qty is None or qty <= 0:
            drop("missing_quantity")
            return None
        exit_order = select_orphan_exit(
            entry=entry,
            entry_side=side,
            entry_qty=qty,
            entry_ts=entry_ts,
            candidates=orphan_candidates or (),
            claimed_exit_ids=claimed_exit_ids,
            window_days=orphan_window_days,
            qty_tolerance=orphan_qty_tolerance,
        )
        if exit_order is not None:
            exit_reason = "MANUAL_OR_FLATTEN"
            exit_via_orphan = True

    if exit_order is None:
        drop(
            classify_missing_exit_fill(
                entry=entry,
                entry_side=side,
                entry_ts=entry_ts,
                children=children,
                orphan_candidates=orphan_candidates or (),
            )
        )
        return None

    exit_price = order_fill_price(exit_order)
    if exit_price is None or exit_price <= 0:
        drop("missing_exit_price")
        return None

    qty = qty or order_qty(exit_order)
    if qty is None or qty <= 0:
        drop("missing_quantity")
        return None

    pnl_usd, pnl_pct = compute_pnl(
        side=side, entry_price=entry_price, exit_price=exit_price, quantity=qty
    )
    exit_ts = order_event_ts(exit_order)
    hold_seconds: Optional[int] = None
    if entry_ts and exit_ts:
        hold_seconds = max(0, int((exit_ts - entry_ts).total_seconds()))

    telegram_message_id = intent.get("signal_id")
    if telegram_message_id is None and alert is not None:
        telegram_message_id = alert.get("id")

    if stats is not None:
        stats.complete += 1
        if telegram_message_id is not None:
            stats.with_alert += 1
        else:
            stats.without_alert += 1

    exit_oid = _as_str(exit_order.get("exchange_order_id"))
    if claimed_exit_ids is not None and exit_oid:
        claimed_exit_ids.add(exit_oid)

    meta = {
        "entry_order_type": _as_str(entry.get("order_type")),
        "exit_order_type": _as_str(exit_order.get("order_type")),
        "exit_order_role": _as_str(exit_order.get("order_role")),
        "oco_group_id": _as_str(entry.get("oco_group_id") or exit_order.get("oco_group_id")),
        "has_alert": telegram_message_id is not None,
        "exit_via_orphan": exit_via_orphan,
    }

    return {
        "telegram_message_id": int(telegram_message_id) if telegram_message_id is not None else None,
        "order_intent_id": intent.get("id"),
        "entry_exchange_order_id": order_id,
        "exit_exchange_order_id": exit_oid,
        "symbol": _as_str(intent.get("symbol") or entry.get("symbol")) or "UNKNOWN",
        "side": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": qty,
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
        "exit_reason": exit_reason or "UNKNOWN",
        "label": 1 if pnl_usd > 0 else 0,
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "hold_seconds": hold_seconds,
        "join_status": "COMPLETE",
        "source": "exchange_orders",
        "meta_json": json.dumps(meta, default=str),
    }


def is_short_close_buy_order(order: Mapping[str, Any]) -> bool:
    """BUY cover leg that closes a short (parent link or SL/TP role).

    Same predicate shape as ``order_position_service._short_close_buy_filter``.
    """
    if (_as_str(order.get("side")) or "").upper() != "BUY":
        return False
    parent = (_as_str(order.get("parent_order_id")) or "").strip()
    role = (_as_str(order.get("order_role")) or "").upper()
    return bool(parent) or role in EXIT_ROLES


def build_outcome_from_short_close_buy(
    cover: Mapping[str, Any],
    parent_entry: Mapping[str, Any],
    *,
    alert: Optional[Mapping[str, Any]] = None,
    order_intent: Optional[Mapping[str, Any]] = None,
    qty_tolerance: float = DEFAULT_ORPHAN_QTY_TOLERANCE,
    stats: Optional[CoverageStats] = None,
) -> Optional[dict[str, Any]]:
    """Build COMPLETE short round-trip from a filled BUY cover + linked SELL entry."""
    if stats is not None:
        pass  # increments applied only on success below

    cover_oid = _as_str(cover.get("exchange_order_id"))
    if not cover_oid or is_dry_run_order_id(cover_oid) or is_ops_stub_closed_order_id(cover_oid):
        if stats is not None:
            stats.dropped["short_close_invalid"] = stats.dropped.get("short_close_invalid", 0) + 1
        return None
    if not is_filled_status(cover.get("status")):
        if stats is not None:
            stats.dropped["short_close_invalid"] = stats.dropped.get("short_close_invalid", 0) + 1
        return None

    parent_side = (_as_str(parent_entry.get("side")) or "").upper()
    if parent_side != "SELL":
        if stats is not None:
            stats.dropped["short_close_invalid"] = stats.dropped.get("short_close_invalid", 0) + 1
        return None
    if not is_filled_status(parent_entry.get("status")):
        if stats is not None:
            stats.dropped["short_close_invalid"] = stats.dropped.get("short_close_invalid", 0) + 1
        return None

    entry_price = order_fill_price(parent_entry)
    exit_price = order_fill_price(cover)
    if entry_price is None or entry_price <= 0 or exit_price is None or exit_price <= 0:
        if stats is not None:
            stats.dropped["short_close_invalid"] = stats.dropped.get("short_close_invalid", 0) + 1
        return None

    entry_qty = order_qty(parent_entry)
    exit_qty = order_qty(cover)
    if entry_qty is None or exit_qty is None or entry_qty <= 0 or exit_qty <= 0:
        if stats is not None:
            stats.dropped["short_close_invalid"] = stats.dropped.get("short_close_invalid", 0) + 1
        return None
    if not _qty_within_tolerance(entry_qty, exit_qty, tolerance=qty_tolerance):
        if stats is not None:
            stats.dropped["short_close_invalid"] = stats.dropped.get("short_close_invalid", 0) + 1
        return None

    entry_oid = _as_str(parent_entry.get("exchange_order_id"))
    if not entry_oid:
        if stats is not None:
            stats.dropped["short_close_invalid"] = stats.dropped.get("short_close_invalid", 0) + 1
        return None

    entry_ts = order_event_ts(parent_entry)
    exit_ts = order_event_ts(cover)
    pnl_usd, pnl_pct = compute_pnl(
        side="SELL", entry_price=entry_price, exit_price=exit_price, quantity=exit_qty
    )
    exit_reason = (
        infer_exit_role(order_role=cover.get("order_role"), order_type=cover.get("order_type"))
        or "UNKNOWN"
    )

    telegram_message_id = None
    order_intent_id = None
    if order_intent is not None:
        order_intent_id = order_intent.get("id")
        telegram_message_id = order_intent.get("signal_id")
    if telegram_message_id is None and alert is not None:
        telegram_message_id = alert.get("id")

    hold_seconds: Optional[int] = None
    if entry_ts and exit_ts:
        hold_seconds = max(0, int((exit_ts - entry_ts).total_seconds()))

    if stats is not None:
        stats.complete += 1
        stats.short_close_supplemented += 1
        if telegram_message_id is not None:
            stats.with_alert += 1
        else:
            stats.without_alert += 1

    meta = {
        "outcome_kind": "short_close_buy",
        "entry_order_type": _as_str(parent_entry.get("order_type")),
        "exit_order_type": _as_str(cover.get("order_type")),
        "exit_order_role": _as_str(cover.get("order_role")),
        "has_alert": telegram_message_id is not None,
        "exit_via_short_close_buy": True,
    }

    return {
        "telegram_message_id": int(telegram_message_id) if telegram_message_id is not None else None,
        "order_intent_id": order_intent_id,
        "entry_exchange_order_id": entry_oid,
        "exit_exchange_order_id": cover_oid,
        "symbol": _as_str(parent_entry.get("symbol") or cover.get("symbol")) or "UNKNOWN",
        "side": "SELL",
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": exit_qty,
        "pnl_usd": pnl_usd,
        "pnl_pct": pnl_pct,
        "exit_reason": exit_reason,
        "label": 1 if pnl_usd > 0 else 0,
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "hold_seconds": hold_seconds,
        "join_status": "COMPLETE",
        "source": "exchange_orders",
        "meta_json": json.dumps(meta, default=str),
    }


def supplement_short_close_buy_outcomes(
    rows: Sequence[Mapping[str, Any]],
    short_close_buys: Sequence[Mapping[str, Any]],
    entries_by_id: Mapping[str, Mapping[str, Any]],
    *,
    intents_by_order_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
    alerts_by_id: Optional[Mapping[Any, Mapping[str, Any]]] = None,
    qty_tolerance: float = DEFAULT_ORPHAN_QTY_TOLERANCE,
    stats: Optional[CoverageStats] = None,
) -> list[dict[str, Any]]:
    """Add short round-trips from BUY cover legs when the intent path missed them."""
    existing_entries = {_as_str(r.get("entry_exchange_order_id")) for r in rows}
    existing_entries.discard(None)
    intents_by_order_id = intents_by_order_id or {}
    alerts_by_id = alerts_by_id or {}
    out: list[dict[str, Any]] = [dict(r) for r in rows]

    for cover in short_close_buys:
        if not is_short_close_buy_order(cover):
            continue
        parent_id = _as_str(cover.get("parent_order_id"))
        if not parent_id:
            if stats is not None:
                stats.dropped["short_close_invalid"] = stats.dropped.get("short_close_invalid", 0) + 1
            continue
        if parent_id in existing_entries:
            if stats is not None:
                stats.dropped["short_close_existing"] = stats.dropped.get("short_close_existing", 0) + 1
            continue
        parent_entry = entries_by_id.get(parent_id)
        if parent_entry is None:
            if stats is not None:
                stats.dropped["short_close_missing_parent"] = stats.dropped.get(
                    "short_close_missing_parent", 0
                ) + 1
            continue

        intent = intents_by_order_id.get(parent_id)
        alert = None
        if intent is not None and intent.get("signal_id") is not None:
            alert = alerts_by_id.get(intent["signal_id"])

        row = build_outcome_from_short_close_buy(
            cover,
            parent_entry,
            alert=alert,
            order_intent=intent,
            qty_tolerance=qty_tolerance,
            stats=stats,
        )
        if row is not None:
            out.append(row)
            existing_entries.add(parent_id)

    return out


def build_outcomes_from_fixtures(
    *,
    intents: Sequence[Mapping[str, Any]],
    entries_by_id: Mapping[str, Mapping[str, Any]],
    children_by_parent: Mapping[str, Sequence[Mapping[str, Any]]],
    alerts_by_id: Optional[Mapping[Any, Mapping[str, Any]]] = None,
    orphan_candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    short_close_buys: Optional[Sequence[Mapping[str, Any]]] = None,
    orphan_window_days: int = DEFAULT_ORPHAN_EXIT_WINDOW_DAYS,
    orphan_qty_tolerance: float = DEFAULT_ORPHAN_QTY_TOLERANCE,
) -> tuple[list[dict[str, Any]], CoverageStats]:
    """Batch build from in-memory fixtures (unit tests / dry-run JSON).

    Dry-run synthetic order ids are excluded from the eligible set (not counted).
    """
    alerts_by_id = alerts_by_id or {}
    orphans = list(orphan_candidates or ())
    stats = CoverageStats()
    claimed_exit_ids: set[str] = set()
    out: list[dict[str, Any]] = []
    for intent in intents:
        status = (_as_str(intent.get("status")) or "").upper()
        if status and status not in ENTRY_INTENT_STATUSES:
            continue
        oid = _as_str(intent.get("order_id"))
        # PR1: exclude dry-run synthetics from eligible denom entirely.
        if oid and is_dry_run_order_id(oid):
            continue
        entry = entries_by_id.get(oid) if oid else None
        children = list(children_by_parent.get(oid or "", [])) if oid else []
        alert = None
        sid = intent.get("signal_id")
        if sid is not None:
            alert = alerts_by_id.get(sid)
        row = build_outcome_for_intent(
            intent,
            entry=entry,
            children=children,
            alert=alert,
            orphan_candidates=orphans,
            claimed_exit_ids=claimed_exit_ids,
            orphan_window_days=orphan_window_days,
            orphan_qty_tolerance=orphan_qty_tolerance,
            stats=stats,
        )
        if row is not None:
            out.append(row)
    intents_by_order_id = {
        oid: intent
        for intent in intents
        if (oid := _as_str(intent.get("order_id")))
    }
    if short_close_buys:
        out = supplement_short_close_buy_outcomes(
            out,
            short_close_buys,
            entries_by_id,
            intents_by_order_id=intents_by_order_id,
            alerts_by_id=alerts_by_id,
            qty_tolerance=orphan_qty_tolerance,
            stats=stats,
        )
    return out, stats


def load_rows_from_db(database_url: str, *, days: Optional[int] = 90) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[Any, dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """Read intents / orders / alerts / orphan exit candidates / short-close BUYs.

    Never logs the URL (may contain credentials). Dry-run synthetic order ids
    are excluded from the eligible intent set.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    cutoff = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    intents: list[dict[str, Any]] = []
    entries_by_id: dict[str, dict[str, Any]] = {}
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    alerts_by_id: dict[Any, dict[str, Any]] = {}
    orphan_candidates: list[dict[str, Any]] = []
    short_close_buys: list[dict[str, Any]] = []

    with engine.connect() as conn:
        intent_sql = text(
            """
            SELECT id, signal_id, symbol, side, status, order_id, created_at, updated_at
            FROM order_intents
            WHERE status = 'ORDER_PLACED'
              AND order_id IS NOT NULL
              AND LOWER(order_id) NOT LIKE 'dry\\_%' ESCAPE '\\'
              AND (:cutoff IS NULL OR created_at >= :cutoff)
            ORDER BY created_at DESC
            """
        )
        for row in conn.execute(intent_sql, {"cutoff": cutoff}):
            d = dict(row._mapping)
            # Defense in depth (SQL already filters); keeps unit-testable helper path.
            if is_dry_run_order_id(_as_str(d.get("order_id"))):
                continue
            intents.append(d)

        order_ids = [i["order_id"] for i in intents if i.get("order_id")]
        if not order_ids:
            return intents, entries_by_id, children_by_parent, alerts_by_id, orphan_candidates, short_close_buys

        # Chunk IN lists for portability
        chunk = 500
        for i in range(0, len(order_ids), chunk):
            part = order_ids[i : i + chunk]
            placeholders = ", ".join(f":oid{j}" for j in range(len(part)))
            params = {f"oid{j}": part[j] for j in range(len(part))}
            entry_sql = text(
                f"""
                SELECT exchange_order_id, symbol, side, order_type, status,
                       price, quantity, cumulative_quantity, avg_price,
                       exchange_create_time, exchange_update_time,
                       parent_order_id, oco_group_id, order_role,
                       created_at, updated_at
                FROM exchange_orders
                WHERE exchange_order_id IN ({placeholders})
                """
            )
            for row in conn.execute(entry_sql, params):
                d = dict(row._mapping)
                entries_by_id[d["exchange_order_id"]] = d

            child_sql = text(
                f"""
                SELECT exchange_order_id, symbol, side, order_type, status,
                       price, quantity, cumulative_quantity, avg_price,
                       exchange_create_time, exchange_update_time,
                       parent_order_id, oco_group_id, order_role,
                       created_at, updated_at
                FROM exchange_orders
                WHERE parent_order_id IN ({placeholders})
                """
            )
            for row in conn.execute(child_sql, params):
                d = dict(row._mapping)
                parent = d.get("parent_order_id")
                if not parent:
                    continue
                children_by_parent.setdefault(parent, []).append(d)

        symbols = sorted(
            {
                (_as_str(i.get("symbol")) or "")
                for i in intents
                if _as_str(i.get("symbol"))
            }
            | {
                (_as_str(e.get("symbol")) or "")
                for e in entries_by_id.values()
                if _as_str(e.get("symbol"))
            }
        )
        if symbols:
            # Orphan flatten/manual closes: FILLED MARKET/LIMIT, unparented.
            # Extend lookback slightly so exit can fall after intent cutoff.
            orphan_cutoff = None
            if cutoff is not None:
                orphan_cutoff = cutoff - timedelta(days=DEFAULT_ORPHAN_EXIT_WINDOW_DAYS)
            for i in range(0, len(symbols), chunk):
                part = symbols[i : i + chunk]
                placeholders = ", ".join(f":sym{j}" for j in range(len(part)))
                params: dict[str, Any] = {f"sym{j}": part[j] for j in range(len(part))}
                params["cutoff"] = orphan_cutoff
                orphan_sql = text(
                    f"""
                    SELECT exchange_order_id, symbol, side, order_type, status,
                           price, quantity, cumulative_quantity, avg_price,
                           exchange_create_time, exchange_update_time,
                           parent_order_id, oco_group_id, order_role,
                           created_at, updated_at
                    FROM exchange_orders
                    WHERE symbol IN ({placeholders})
                      AND parent_order_id IS NULL
                      AND UPPER(status::text) IN ('FILLED', 'PARTIALLY_FILLED')
                      AND UPPER(order_type::text) IN ('MARKET', 'LIMIT')
                      AND LOWER(exchange_order_id) NOT LIKE 'dry\\_%' ESCAPE '\\'
                      AND UPPER(exchange_order_id) NOT LIKE 'STUB-CLOSED-%'
                      AND (order_role IS NULL OR UPPER(order_role::text) NOT IN ('STOP_LOSS', 'TAKE_PROFIT'))
                      AND (:cutoff IS NULL
                           OR COALESCE(exchange_update_time, exchange_create_time, created_at) >= :cutoff)
                    """
                )
                for row in conn.execute(orphan_sql, params):
                    orphan_candidates.append(dict(row._mapping))

            # Short-close BUY covers (TP/SL linked to SELL parent) for ML labels.
            short_cutoff = cutoff
            for i in range(0, len(symbols), chunk):
                part = symbols[i : i + chunk]
                placeholders = ", ".join(f":sym{j}" for j in range(len(part)))
                params = {f"sym{j}": part[j] for j in range(len(part))}
                params["cutoff"] = short_cutoff
                short_close_sql = text(
                    f"""
                    SELECT exchange_order_id, symbol, side, order_type, status,
                           price, quantity, cumulative_quantity, avg_price,
                           exchange_create_time, exchange_update_time,
                           parent_order_id, oco_group_id, order_role,
                           created_at, updated_at
                    FROM exchange_orders
                    WHERE symbol IN ({placeholders})
                      AND UPPER(side::text) = 'BUY'
                      AND UPPER(status::text) IN ('FILLED', 'PARTIALLY_FILLED')
                      AND (
                        parent_order_id IS NOT NULL
                        OR UPPER(COALESCE(order_role::text, '')) IN ('STOP_LOSS', 'TAKE_PROFIT')
                      )
                      AND LOWER(exchange_order_id) NOT LIKE 'dry\\_%' ESCAPE '\\'
                      AND UPPER(exchange_order_id) NOT LIKE 'STUB-CLOSED-%'
                      AND (:cutoff IS NULL
                           OR COALESCE(exchange_update_time, exchange_create_time, created_at) >= :cutoff)
                    """
                )
                for row in conn.execute(short_close_sql, params):
                    short_close_buys.append(dict(row._mapping))

        signal_ids = [i["signal_id"] for i in intents if i.get("signal_id") is not None]
        for i in range(0, len(signal_ids), chunk):
            part = signal_ids[i : i + chunk]
            if not part:
                continue
            placeholders = ", ".join(f":sid{j}" for j in range(len(part)))
            params = {f"sid{j}": part[j] for j in range(len(part))}
            alert_sql = text(
                f"""
                SELECT id, symbol, timestamp, context_json, blocked, order_skipped
                FROM telegram_messages
                WHERE id IN ({placeholders})
                """
            )
            for row in conn.execute(alert_sql, params):
                d = dict(row._mapping)
                alerts_by_id[d["id"]] = d

    return intents, entries_by_id, children_by_parent, alerts_by_id, orphan_candidates, short_close_buys


def upsert_outcomes(database_url: str, rows: Iterable[Mapping[str, Any]]) -> int:
    """Insert or update COMPLETE outcomes by entry_exchange_order_id. Returns rows touched."""
    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    sql = text(
        """
        INSERT INTO trade_outcomes (
            telegram_message_id, order_intent_id, entry_exchange_order_id, exit_exchange_order_id,
            symbol, side, entry_price, exit_price, quantity, pnl_usd, pnl_pct,
            exit_reason, label, entry_ts, exit_ts, hold_seconds, join_status, source, meta_json,
            created_at, updated_at
        ) VALUES (
            :telegram_message_id, :order_intent_id, :entry_exchange_order_id, :exit_exchange_order_id,
            :symbol, :side, :entry_price, :exit_price, :quantity, :pnl_usd, :pnl_pct,
            :exit_reason, :label, :entry_ts, :exit_ts, :hold_seconds, :join_status, :source, :meta_json,
            (NOW() AT TIME ZONE 'UTC'), (NOW() AT TIME ZONE 'UTC')
        )
        ON CONFLICT (entry_exchange_order_id) DO UPDATE SET
            telegram_message_id = EXCLUDED.telegram_message_id,
            order_intent_id = EXCLUDED.order_intent_id,
            exit_exchange_order_id = EXCLUDED.exit_exchange_order_id,
            symbol = EXCLUDED.symbol,
            side = EXCLUDED.side,
            entry_price = EXCLUDED.entry_price,
            exit_price = EXCLUDED.exit_price,
            quantity = EXCLUDED.quantity,
            pnl_usd = EXCLUDED.pnl_usd,
            pnl_pct = EXCLUDED.pnl_pct,
            exit_reason = EXCLUDED.exit_reason,
            label = EXCLUDED.label,
            entry_ts = EXCLUDED.entry_ts,
            exit_ts = EXCLUDED.exit_ts,
            hold_seconds = EXCLUDED.hold_seconds,
            join_status = EXCLUDED.join_status,
            source = EXCLUDED.source,
            meta_json = EXCLUDED.meta_json,
            updated_at = (NOW() AT TIME ZONE 'UTC')
        """
    )
    # SQLite fallback for local/unit smoke (no NOW() AT TIME ZONE)
    sql_sqlite = text(
        """
        INSERT INTO trade_outcomes (
            telegram_message_id, order_intent_id, entry_exchange_order_id, exit_exchange_order_id,
            symbol, side, entry_price, exit_price, quantity, pnl_usd, pnl_pct,
            exit_reason, label, entry_ts, exit_ts, hold_seconds, join_status, source, meta_json,
            created_at, updated_at
        ) VALUES (
            :telegram_message_id, :order_intent_id, :entry_exchange_order_id, :exit_exchange_order_id,
            :symbol, :side, :entry_price, :exit_price, :quantity, :pnl_usd, :pnl_pct,
            :exit_reason, :label, :entry_ts, :exit_ts, :hold_seconds, :join_status, :source, :meta_json,
            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT (entry_exchange_order_id) DO UPDATE SET
            telegram_message_id = EXCLUDED.telegram_message_id,
            order_intent_id = EXCLUDED.order_intent_id,
            exit_exchange_order_id = EXCLUDED.exit_exchange_order_id,
            symbol = EXCLUDED.symbol,
            side = EXCLUDED.side,
            entry_price = EXCLUDED.entry_price,
            exit_price = EXCLUDED.exit_price,
            quantity = EXCLUDED.quantity,
            pnl_usd = EXCLUDED.pnl_usd,
            pnl_pct = EXCLUDED.pnl_pct,
            exit_reason = EXCLUDED.exit_reason,
            label = EXCLUDED.label,
            entry_ts = EXCLUDED.entry_ts,
            exit_ts = EXCLUDED.exit_ts,
            hold_seconds = EXCLUDED.hold_seconds,
            join_status = EXCLUDED.join_status,
            source = EXCLUDED.source,
            meta_json = EXCLUDED.meta_json,
            updated_at = CURRENT_TIMESTAMP
        """
    )

    count = 0
    with engine.begin() as conn:
        q = sql_sqlite if engine.dialect.name == "sqlite" else sql
        for row in rows:
            payload = dict(row)
            # Decimal-friendly for drivers
            for k in ("entry_price", "exit_price", "quantity", "pnl_usd", "pnl_pct"):
                if payload.get(k) is not None and not isinstance(payload[k], Decimal):
                    payload[k] = float(payload[k])
            conn.execute(q, payload)
            count += 1
    return count


def coverage_report_dict(
    rows: Sequence[Mapping[str, Any]], stats: CoverageStats
) -> dict[str, Any]:
    pos = sum(1 for r in rows if r.get("label") == 1)
    neg = sum(1 for r in rows if r.get("label") == 0)
    by_reason: dict[str, int] = {}
    for r in rows:
        reason = str(r.get("exit_reason") or "UNKNOWN")
        by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "phase": "1a-trade-outcomes",
        "label_def": "y=1 if round-trip pnl_usd > 0 else 0 (COMPLETE only)",
        "coverage": stats.to_dict(),
        "n_written_or_built": len(rows),
        "n_positive": pos,
        "n_negative": neg,
        "exit_reason_counts": by_reason,
        "note": "Phase 1b: use scripts/build_auto_ml_dataset.py --label-source hybrid|trade_outcomes.",
    }
