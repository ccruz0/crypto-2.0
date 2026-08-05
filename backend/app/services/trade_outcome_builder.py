"""Build round-trip trade outcome labels from existing order tables (Phase 1a).

Join path (design ADR closed-loop Phase 1):
  telegram_messages.id
    ← order_intents.signal_id
    ← order_intents.order_id = exchange_orders.exchange_order_id (entry)
    ← exchange_orders where parent_order_id = entry (SL/TP children)

Incomplete joins are dropped. Coverage counters are returned for operators.
Pure helpers accept dict-shaped rows so unit tests need no live DB.
Does NOT wire Auto ML promote (Phase 1b).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional, Sequence


EXIT_ROLES = frozenset({"STOP_LOSS", "TAKE_PROFIT"})
FILLED_STATUSES = frozenset(
    {"FILLED", "PARTIALLY_FILLED"}  # PARTIALLY_FILLED treated as usable exit if price present
)
ENTRY_INTENT_STATUSES = frozenset({"ORDER_PLACED"})


@dataclass
class CoverageStats:
    intents_considered: int = 0
    complete: int = 0
    with_alert: int = 0
    without_alert: int = 0
    dropped: dict[str, int] = field(
        default_factory=lambda: {
            "missing_order_id": 0,
            "missing_entry_order": 0,
            "entry_not_filled": 0,
            "missing_entry_price": 0,
            "missing_exit_fill": 0,
            "missing_exit_price": 0,
            "missing_quantity": 0,
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
    """Prefer earliest filled SL/TP child by event timestamp."""
    filled: list[tuple[datetime, Mapping[str, Any]]] = []
    for child in children:
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


def build_outcome_for_intent(
    intent: Mapping[str, Any],
    *,
    entry: Optional[Mapping[str, Any]],
    children: Sequence[Mapping[str, Any]],
    alert: Optional[Mapping[str, Any]] = None,
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

    exit_child = select_exit_child(children)
    if exit_child is None:
        drop("missing_exit_fill")
        return None

    exit_price = order_fill_price(exit_child)
    if exit_price is None or exit_price <= 0:
        drop("missing_exit_price")
        return None

    qty = order_qty(entry) or order_qty(exit_child)
    if qty is None or qty <= 0:
        drop("missing_quantity")
        return None

    side = (_as_str(intent.get("side")) or _as_str(entry.get("side")) or "BUY").upper()
    pnl_usd, pnl_pct = compute_pnl(
        side=side, entry_price=entry_price, exit_price=exit_price, quantity=qty
    )
    exit_reason = infer_exit_role(
        order_role=exit_child.get("order_role"), order_type=exit_child.get("order_type")
    ) or "UNKNOWN"
    entry_ts = order_event_ts(entry)
    exit_ts = order_event_ts(exit_child)
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

    meta = {
        "entry_order_type": _as_str(entry.get("order_type")),
        "exit_order_type": _as_str(exit_child.get("order_type")),
        "exit_order_role": _as_str(exit_child.get("order_role")),
        "oco_group_id": _as_str(entry.get("oco_group_id") or exit_child.get("oco_group_id")),
        "has_alert": telegram_message_id is not None,
    }

    return {
        "telegram_message_id": int(telegram_message_id) if telegram_message_id is not None else None,
        "order_intent_id": intent.get("id"),
        "entry_exchange_order_id": order_id,
        "exit_exchange_order_id": _as_str(exit_child.get("exchange_order_id")),
        "symbol": _as_str(intent.get("symbol") or entry.get("symbol")) or "UNKNOWN",
        "side": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": qty,
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


def build_outcomes_from_fixtures(
    *,
    intents: Sequence[Mapping[str, Any]],
    entries_by_id: Mapping[str, Mapping[str, Any]],
    children_by_parent: Mapping[str, Sequence[Mapping[str, Any]]],
    alerts_by_id: Optional[Mapping[Any, Mapping[str, Any]]] = None,
) -> tuple[list[dict[str, Any]], CoverageStats]:
    """Batch build from in-memory fixtures (unit tests / dry-run JSON)."""
    alerts_by_id = alerts_by_id or {}
    stats = CoverageStats()
    out: list[dict[str, Any]] = []
    for intent in intents:
        status = (_as_str(intent.get("status")) or "").upper()
        if status and status not in ENTRY_INTENT_STATUSES:
            continue
        oid = _as_str(intent.get("order_id"))
        entry = entries_by_id.get(oid) if oid else None
        children = list(children_by_parent.get(oid or "", [])) if oid else []
        alert = None
        sid = intent.get("signal_id")
        if sid is not None:
            alert = alerts_by_id.get(sid)
        row = build_outcome_for_intent(
            intent, entry=entry, children=children, alert=alert, stats=stats
        )
        if row is not None:
            out.append(row)
    return out, stats


def load_rows_from_db(database_url: str, *, days: Optional[int] = 90) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[Any, dict[str, Any]],
]:
    """Read intents / orders / alerts. Never logs the URL (may contain credentials)."""
    from datetime import timedelta

    from sqlalchemy import create_engine, text

    engine = create_engine(database_url)
    cutoff = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    intents: list[dict[str, Any]] = []
    entries_by_id: dict[str, dict[str, Any]] = {}
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    alerts_by_id: dict[Any, dict[str, Any]] = {}

    with engine.connect() as conn:
        intent_sql = text(
            """
            SELECT id, signal_id, symbol, side, status, order_id, created_at, updated_at
            FROM order_intents
            WHERE status = 'ORDER_PLACED'
              AND order_id IS NOT NULL
              AND (:cutoff IS NULL OR created_at >= :cutoff)
            ORDER BY created_at DESC
            """
        )
        for row in conn.execute(intent_sql, {"cutoff": cutoff}):
            intents.append(dict(row._mapping))

        order_ids = [i["order_id"] for i in intents if i.get("order_id")]
        if not order_ids:
            return intents, entries_by_id, children_by_parent, alerts_by_id

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

    return intents, entries_by_id, children_by_parent, alerts_by_id


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
        "note": "Not wired to Auto ML promote (Phase 1b).",
    }
