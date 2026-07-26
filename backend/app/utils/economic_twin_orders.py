"""Deduplicate Crypto.com dual-ID copies of the same economic fill.

Crypto.com often persists both:
  - advanced/trigger id (e.g. 7381749…)
  - spot remapped fill id (e.g. 5755600…)
for one TP/SL execution. Sync upserts by exchange_order_id only, so history
and FIFO would otherwise show/count the fill twice.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.models.exchange_order import ExchangeOrder

ECONOMIC_TWIN_MAX_GAP = timedelta(hours=1)

PROTECTION_CLOSE_ROLES = frozenset({"TAKE_PROFIT", "STOP_LOSS"})


def is_protection_close_order(order: ExchangeOrder) -> bool:
    role = (order.order_role or "").strip().upper()
    if role in PROTECTION_CLOSE_ROLES:
        return True
    order_type = (order.order_type or "").strip().upper()
    return (
        "TAKE_PROFIT" in order_type
        or order_type in {"STOP_LIMIT", "STOP_LOSS", "STOP_LOSS_LIMIT"}
    )


def _fill_qty(order: ExchangeOrder) -> Decimal:
    return Decimal(str(order.cumulative_quantity or order.quantity or 0))


def _fill_price(order: ExchangeOrder) -> Decimal:
    return Decimal(str(order.avg_price or order.price or 0))


def _fill_time(order: ExchangeOrder) -> Optional[datetime]:
    return order.exchange_update_time or order.exchange_create_time or order.created_at


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def times_within_economic_twin_gap(a: ExchangeOrder, b: ExchangeOrder) -> bool:
    ta = _aware(_fill_time(a))
    tb = _aware(_fill_time(b))
    if ta is None or tb is None:
        return False
    # Remap evidence: A updated when B was created (or vice versa).
    ta_create = _aware(a.exchange_create_time or a.created_at) or ta
    tb_create = _aware(b.exchange_create_time or b.created_at) or tb
    gaps = [
        abs(ta - tb),
        abs(ta - tb_create),
        abs(tb - ta_create),
    ]
    return min(gaps) <= ECONOMIC_TWIN_MAX_GAP


def protection_close_fingerprint(
    order: ExchangeOrder,
) -> Optional[Tuple[str, str, str, str, Decimal, Decimal]]:
    """Group key for dual-ID TP/SL fills of the same economic close."""
    parent = (order.parent_order_id or "").strip()
    if not parent:
        return None
    if not is_protection_close_order(order):
        return None
    role = (order.order_role or "").strip().upper()
    if not role:
        ot = (order.order_type or "").upper()
        role = "TAKE_PROFIT" if "TAKE_PROFIT" in ot else "STOP_LOSS"
    side = order.side.value if hasattr(order.side, "value") else str(order.side or "")
    qty = _fill_qty(order).quantize(Decimal("0.00000001"))
    price = _fill_price(order).quantize(Decimal("0.01"))
    if qty <= 0 or price <= 0:
        return None
    return (
        str(order.symbol or "").upper(),
        parent,
        side.upper(),
        role,
        qty,
        price,
    )


def protection_close_keep_score(order: ExchangeOrder) -> Tuple[int, datetime, str]:
    """Higher score wins. Prefer OCO/advanced trigger row over spot remapped fill."""
    score = 0
    if (order.oco_group_id or "").strip():
        score += 100
    try:
        if float(order.cumulative_value or 0) > 0:
            score += 10
    except (TypeError, ValueError):
        pass
    # Prefer the older create time (original trigger), then stable id.
    created = _aware(order.exchange_create_time or order.created_at) or datetime.min.replace(
        tzinfo=timezone.utc
    )
    # Invert create for tuple sort: we want higher score first, then earlier create.
    return (score, datetime.max.replace(tzinfo=timezone.utc) - created, str(order.exchange_order_id or ""))


def choose_canonical_protection_close(
    candidates: Sequence[ExchangeOrder],
) -> Optional[ExchangeOrder]:
    if not candidates:
        return None
    return max(candidates, key=protection_close_keep_score)


def dedupe_protection_close_twins(
    orders: Sequence[ExchangeOrder],
) -> List[ExchangeOrder]:
    """
    Drop shadow TP/SL fill rows when a canonical twin is present in ``orders``.

    Keeps non-protection rows untouched. Within each fingerprint group, keeps
    the highest ``protection_close_keep_score`` row and drops time-adjacent twins.
    """
    if len(orders) < 2:
        return list(orders)

    groups: Dict[Tuple, List[ExchangeOrder]] = {}
    passthrough: List[ExchangeOrder] = []
    for order in orders:
        fp = protection_close_fingerprint(order)
        if fp is None:
            passthrough.append(order)
            continue
        groups.setdefault(fp, []).append(order)

    drop_ids: set[str] = set()
    keep: List[ExchangeOrder] = []
    for group in groups.values():
        if len(group) == 1:
            keep.extend(group)
            continue
        # Cluster by time adjacency (union-find lite via pairwise keep set).
        remaining = list(group)
        while remaining:
            canonical = choose_canonical_protection_close(remaining)
            if canonical is None:
                break
            cid = str(canonical.exchange_order_id)
            keep.append(canonical)
            remaining = [o for o in remaining if str(o.exchange_order_id) != cid]
            next_remaining: List[ExchangeOrder] = []
            for shadow in remaining:
                if times_within_economic_twin_gap(canonical, shadow):
                    drop_ids.add(str(shadow.exchange_order_id))
                else:
                    next_remaining.append(shadow)
            remaining = next_remaining

    if not drop_ids:
        return list(orders)

    # Preserve original order, excluding dropped shadows.
    out: List[ExchangeOrder] = []
    for order in orders:
        oid = str(order.exchange_order_id or "")
        if oid and oid in drop_ids:
            continue
        out.append(order)
    return out


def shadow_protection_close_ids_against_canonicals(
    candidates: Iterable[ExchangeOrder],
    canonicals: Iterable[ExchangeOrder],
) -> set[str]:
    """
    IDs in ``candidates`` that are time-adjacent twins of a better canonical
    already chosen (e.g. page row is spot remap; DB has OCO trigger twin).
    """
    canon_by_fp: Dict[Tuple, ExchangeOrder] = {}
    for order in canonicals:
        fp = protection_close_fingerprint(order)
        if fp is None:
            continue
        prev = canon_by_fp.get(fp)
        if prev is None or protection_close_keep_score(order) > protection_close_keep_score(prev):
            canon_by_fp[fp] = order

    drop: set[str] = set()
    for order in candidates:
        fp = protection_close_fingerprint(order)
        if fp is None:
            continue
        canon = canon_by_fp.get(fp)
        if canon is None:
            continue
        oid = str(order.exchange_order_id or "")
        cid = str(canon.exchange_order_id or "")
        if not oid or oid == cid:
            continue
        if protection_close_keep_score(order) >= protection_close_keep_score(canon):
            continue
        if times_within_economic_twin_gap(order, canon):
            drop.add(oid)
    return drop
