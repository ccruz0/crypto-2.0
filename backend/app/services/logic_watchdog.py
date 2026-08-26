"""Logic Watchdog - hourly consistency check between what the exchange did
and what Telegram reported.

Why this exists
---------------
The Telegram feed is the operator's only real-time view of the bot. Some
alerts arrive that do not make sense: an entry fills but no SL/TP alert
follows, a protection leg is rejected, an OCO sibling is never cancelled.
Some of those are *trading* bugs; some are *reporting* bugs (see
TELEGRAM_SL_TP_FIX.md - alerts were silently dropped by the origin
gatekeeper while the orders themselves were fine).

This service reads BOTH sources - `exchange_orders` (ground truth) and
`telegram_messages` (what was reported) - so it can tell those two classes
apart instead of paging on every lost notification.

Each finding is persisted once (dedup by fingerprint) and pushed to
Telegram with Ignore / Fix-code buttons. See watchdog_inline.py.

Run manually:
    python -m app.services.logic_watchdog --dry-run --hours 168
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import or_, text

from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.telegram_message import TelegramMessage

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = (
    OrderStatusEnum.NEW,
    OrderStatusEnum.ACTIVE,
    OrderStatusEnum.PARTIALLY_FILLED,
)
DEAD_STATUSES = (
    OrderStatusEnum.CANCELLED,
    OrderStatusEnum.REJECTED,
    OrderStatusEnum.EXPIRED,
)

# Exchange order types that actually trigger. An order booked as protection
# whose real type is outside these sets does not protect anything (#521).
_SL_EXCHANGE_TYPES = ("STOP_LOSS", "STOP_LIMIT", "STOP_MARKET", "STOP_LOSS_LIMIT")
_TP_EXCHANGE_TYPES = ("TAKE_PROFIT", "TAKE_PROFIT_LIMIT", "TAKE_PROFIT_MARKET")


# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def is_enabled() -> bool:
    return (os.getenv("WATCHDOG_ENABLED", "true") or "true").strip().lower() in ("1", "true", "yes")


WINDOW_HOURS = lambda: _env_int("WATCHDOG_WINDOW_HOURS", 6)                 # noqa: E731
GRACE_MINUTES = lambda: _env_int("WATCHDOG_PROTECTION_GRACE_MIN", 15)       # noqa: E731
MIN_POSITION_USD = lambda: _env_float("WATCHDOG_MIN_POSITION_USD", 5.0)     # noqa: E731
MAX_ALERTS_PER_RUN = lambda: _env_int("WATCHDOG_MAX_ALERTS_PER_RUN", 5)     # noqa: E731
PRICE_TOLERANCE = lambda: _env_float("WATCHDOG_PRICE_TOLERANCE", 0.005)     # noqa: E731
QTY_TOLERANCE = lambda: _env_float("WATCHDOG_QTY_TOLERANCE", 0.02)          # noqa: E731
# One exchange call per live protection leg. Bounded so a bloated book cannot
# stall the run; whatever the bound drops is reported, never dropped silently.
MAX_TYPE_CHECKS = lambda: _env_int("WATCHDOG_MAX_TYPE_CHECKS", 60)          # noqa: E731


DDL = """
CREATE TABLE IF NOT EXISTS watchdog_anomalies (
    id SERIAL PRIMARY KEY,
    fingerprint VARCHAR(64) NOT NULL UNIQUE,
    kind VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'medium',
    symbol VARCHAR(50),
    title VARCHAR(200) NOT NULL,
    detail TEXT,
    evidence_json TEXT,
    suspect_paths TEXT,
    status VARCHAR(20) NOT NULL DEFAULT 'new',
    occurrences INTEGER NOT NULL DEFAULT 1,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    alerted_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    telegram_message_id INTEGER,
    telegram_chat_id VARCHAR(50)
);
CREATE INDEX IF NOT EXISTS ix_watchdog_anomalies_status ON watchdog_anomalies (status);
CREATE INDEX IF NOT EXISTS ix_watchdog_anomalies_last_seen_at ON watchdog_anomalies (last_seen_at);
CREATE TABLE IF NOT EXISTS watchdog_fix_requests (
    id SERIAL PRIMARY KEY,
    anomaly_id INTEGER NOT NULL REFERENCES watchdog_anomalies (id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    requested_by VARCHAR(50),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    branch VARCHAR(200),
    commit_sha VARCHAR(64),
    result_summary TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS ix_watchdog_fix_requests_status ON watchdog_fix_requests (status);
"""


def ensure_watchdog_tables(db) -> None:
    """Idempotent DDL so the watchdog works without a migration deploy."""
    try:
        for stmt in [s.strip() for s in DDL.split(";") if s.strip()]:
            db.execute(text(stmt))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"[WATCHDOG] ensure tables failed (continuing): {e}")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _fingerprint(kind: str, symbol: Optional[str], anchor: str) -> str:
    return hashlib.sha1(f"{kind}|{symbol or ''}|{anchor}".encode("utf-8")).hexdigest()


def _role_of(order: ExchangeOrder) -> Optional[str]:
    """Normalise order_role / order_type into 'SL' | 'TP' | None (= entry)."""
    blob = f"{order.order_role or ''} {order.order_type or ''}".upper()
    if "STOP" in blob:
        return "SL"
    if "TAKE" in blob or "TP" in blob.split():
        return "TP"
    return None


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Timestamps read back from a non-TIMESTAMPTZ column are naive.

    Every arithmetic comparison in this module uses tz-aware UTC, so coerce
    once here instead of crashing with 'can't subtract offset-naive and
    offset-aware datetimes'.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _f(value: Any) -> Optional[float]:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _entry_price(order: ExchangeOrder) -> Optional[float]:
    return _f(order.avg_price) or _f(order.price)


def _filled_qty(order: ExchangeOrder) -> Optional[float]:
    return _f(order.cumulative_quantity) or _f(order.quantity)


def _position_usd(order: ExchangeOrder) -> float:
    val = _f(order.cumulative_value)
    if val:
        return val
    price = _entry_price(order) or 0.0
    qty = _filled_qty(order) or 0.0
    return price * qty


def _finding(
    kind: str,
    severity: str,
    symbol: Optional[str],
    anchor: str,
    title: str,
    detail: str,
    evidence: dict,
    suspects: Iterable[str],
) -> dict:
    return {
        "fingerprint": _fingerprint(kind, symbol, anchor),
        "kind": kind,
        "severity": severity,
        "symbol": symbol,
        "title": title,
        "detail": detail,
        "evidence": evidence,
        "suspects": list(suspects),
    }


def _children_of(db, entry_id: str) -> list[ExchangeOrder]:
    if not entry_id:
        return []
    return (
        db.query(ExchangeOrder)
        .filter(ExchangeOrder.parent_order_id == entry_id)
        .all()
    )


def _protection_alert_seen(db, entry_id: str, since: datetime, until: datetime) -> bool:
    """Did an 'SL/TP ORDERS ...' Telegram message mentioning this entry go out?"""
    if not entry_id:
        return False
    row = (
        db.query(TelegramMessage.id)
        .filter(
            TelegramMessage.timestamp >= since,
            TelegramMessage.timestamp <= until,
            TelegramMessage.message.like(f"%{entry_id}%"),
        )
        .first()
    )
    return row is not None


# --------------------------------------------------------------------------
# RULE 1 - entry filled without protection (and the reporting-loss variant)
# --------------------------------------------------------------------------
SUSPECTS_SL_TP = [
    "app/services/exchange_sync.py::_create_sl_tp_for_filled_order (line ~3017)",
    "app/services/exchange_sync.py::_create_sl_tp_impl (line ~3519)",
    "app/services/tp_sl_order_creator.py::create_stop_loss_order / create_take_profit_order",
    "app/services/sl_tp_checker.py::ensure_missing_protection",
]
SUSPECTS_NOTIFY = [
    "app/services/telegram_notifier.py::send_sl_tp_orders (line ~1220)",
    "app/services/telegram_notifier.py::send_message origin gatekeeper (line ~446)",
    "app/core/runtime.py::get_runtime_origin",
]


def _base_symbol(symbol: Optional[str]) -> str:
    sym = (symbol or "").upper().strip()
    if not sym:
        return ""
    return sym.split("_")[0] if "_" in sym else sym


def _load_wallet_by_base() -> dict[str, float]:
    """Best-effort signed wallet map for short-vs-long-close classification."""
    try:
        from app.services.brokers.crypto_com_trade import trade_client
        from app.services.dashboard_position_counts import wallet_balances_by_base

        summary = trade_client.get_account_summary()
        accounts = summary.get("accounts") or []
        rows = []
        for acc in accounts:
            if not isinstance(acc, dict):
                continue
            cur = acc.get("currency") or acc.get("instrument_name") or acc.get("asset")
            if not cur:
                continue
            bal = acc.get("balance")
            if bal is None:
                bal = acc.get("quantity") or acc.get("available") or 0
            rows.append({"currency": str(cur).split("_")[0], "balance": bal})
        return wallet_balances_by_base(rows)
    except Exception as err:
        logger.debug("[WATCHDOG] wallet load failed: %s", err)
        return {}


def detect_missing_protection(
    db,
    now: datetime,
    wallet_by_base: Optional[dict[str, float]] = None,
) -> list[dict]:
    findings: list[dict] = []
    grace = timedelta(minutes=GRACE_MINUTES())
    window_start = now - timedelta(hours=WINDOW_HOURS())
    cutoff = now - grace
    wallets = wallet_by_base if wallet_by_base is not None else _load_wallet_by_base()

    entries = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.exchange_update_time >= window_start,
            ExchangeOrder.exchange_update_time <= cutoff,
        )
        .all()
    )

    for entry in entries:
        if _role_of(entry) is not None:
            continue  # this IS an SL/TP leg, not an entry
        if entry.side == OrderSideEnum.BUY:
            pass  # long entries always eligible
        elif entry.side == OrderSideEnum.SELL:
            # Live shorts only (wallet < 0). Net-long ALERT sells are long-closes.
            base = _base_symbol(entry.symbol)
            bal = wallets.get(base)
            if bal is None or float(bal) >= 0:
                continue
        else:
            continue
        usd = _position_usd(entry)
        if usd < MIN_POSITION_USD():
            continue  # dust

        children = _children_of(db, entry.exchange_order_id)
        roles_active = {_role_of(c) for c in children if c.status in ACTIVE_STATUSES}
        roles_filled = {_role_of(c) for c in children if c.status == OrderStatusEnum.FILLED}
        roles_active.discard(None)
        roles_filled.discard(None)

        if roles_filled:
            continue  # position already closed through a protection leg

        missing = {"SL", "TP"} - roles_active
        filled_at = _as_utc(entry.exchange_update_time or entry.created_at)
        evidence = {
            "entry_order_id": entry.exchange_order_id,
            "symbol": entry.symbol,
            "side": str(entry.side),
            "entry_price": _entry_price(entry),
            "filled_qty": _filled_qty(entry),
            "position_usd": round(usd, 2),
            "wallet_balance": wallets.get(_base_symbol(entry.symbol)),
            "filled_at": filled_at.isoformat() if filled_at else None,
            "children": [
                {
                    "id": c.exchange_order_id,
                    "role": _role_of(c),
                    "type": c.order_type,
                    "status": str(c.status),
                    "price": _f(c.price),
                }
                for c in children
            ],
        }

        if not missing:
            # Orders exist. Did the operator ever hear about it?
            if filled_at and not _protection_alert_seen(db, entry.exchange_order_id, filled_at, now):
                findings.append(
                    _finding(
                        kind="PROTECTION_ALERT_LOST",
                        severity="medium",
                        symbol=entry.symbol,
                        anchor=entry.exchange_order_id,
                        title="SL/TP creados pero sin aviso en Telegram",
                        detail=(
                            f"La entrada <code>{entry.exchange_order_id}</code> se llenó y SÍ tiene "
                            f"SL y TP activos en el exchange, pero no salió ningún mensaje de "
                            f"«SL/TP ORDERS CREATED».\n"
                            f"Esto es un fallo de <b>notificación</b>, no de trading — el mismo patrón "
                            f"documentado en TELEGRAM_SL_TP_FIX.md (el gatekeeper descarta envíos "
                            f"cuando origin != AWS)."
                        ),
                        evidence=evidence,
                        suspects=SUSPECTS_NOTIFY,
                    )
                )
            continue

        if missing == {"SL", "TP"}:
            kind, title = "MISSING_SL_TP", "Entrada llenada SIN stop loss NI take profit"
        elif missing == {"SL"}:
            kind, title = "MISSING_SL", "Entrada llenada SIN stop loss"
        else:
            kind, title = "MISSING_TP", "Entrada llenada SIN take profit"

        age_min = int((now - filled_at).total_seconds() / 60) if filled_at else None
        findings.append(
            _finding(
                kind=kind,
                severity="high",
                symbol=entry.symbol,
                anchor=entry.exchange_order_id,
                title=title,
                detail=(
                    f"Orden de entrada <code>{entry.exchange_order_id}</code> "
                    f"({entry.symbol}, {_filled_qty(entry)} @ ${_entry_price(entry)}, "
                    f"~${usd:,.2f}) se llenó hace {age_min} min y sigue "
                    f"<b>sin {' ni '.join(sorted(missing))}</b>.\n"
                    f"Side={entry.side}; wallet_base={evidence.get('wallet_balance')}. "
                    f"La posición está expuesta: no hay orden de salida registrada en la BD."
                ),
                evidence=evidence,
                suspects=SUSPECTS_SL_TP,
            )
        )
    return findings


# --------------------------------------------------------------------------
# RULE 2 - explicit failure strings in the Telegram feed
# --------------------------------------------------------------------------
FAILURE_PATTERNS: list[tuple[str, str, str, list[str]]] = [
    # (needle, kind, severity, suspects)
    ("SL Order:</b> FAILED", "SL_CREATION_FAILED", "high", SUSPECTS_SL_TP),
    ("TP Order:</b> FAILED", "TP_CREATION_FAILED", "high", SUSPECTS_SL_TP),
    ("PROTECTION ORDER REJECTED", "PROTECTION_REJECTED", "high",
     ["app/services/exchange_sync.py (line ~1863)", "app/services/tp_sl_order_creator.py"]),
    ("CONDITIONAL ORDER REJECTED (140001)", "CONDITIONAL_ORDER_140001", "high",
     ["app/services/brokers/crypto_com_trade.py::_create_order_try_variants (line ~2595)",
      "app/services/brokers/crypto_com_trade.py (140001 alert, line ~2347)"]),
    ("ORDER FAILED", "ORDER_FAILED", "medium",
     ["app/utils/decision_reason.py::format_order_failed_telegram (line ~223)",
      "app/services/signal_monitor.py (ORDER FAILED emitters)"]),
    ("POSICIÓN SIN PROTECCIÓN", "POSITION_UNPROTECTED_ALERT", "high",
     ["app/services/sl_tp_checker.py::ensure_missing_protection (line ~897)"]),
]


def detect_failure_strings(db, now: datetime) -> list[dict]:
    findings: list[dict] = []
    window_start = now - timedelta(hours=WINDOW_HOURS())
    rows = (
        db.query(TelegramMessage)
        .filter(TelegramMessage.timestamp >= window_start)
        .order_by(TelegramMessage.timestamp.asc())
        .all()
    )
    for row in rows:
        body = row.message or ""
        for needle, kind, severity, suspects in FAILURE_PATTERNS:
            if needle in body:
                snippet = body.replace("\n", " ")[:400]
                findings.append(
                    _finding(
                        kind=kind,
                        severity=severity,
                        symbol=row.symbol,
                        anchor=f"tgmsg:{row.id}",
                        title=f"Fallo explícito reportado: {kind.replace('_', ' ').title()}",
                        detail=(
                            f"Mensaje #{row.id} del "
                            f"{row.timestamp.isoformat() if row.timestamp else '?'} contiene "
                            f"<code>{needle}</code>.\n\n<i>{snippet}</i>"
                        ),
                        evidence={
                            "telegram_message_id": row.id,
                            "needle": needle,
                            "symbol": row.symbol,
                            "reason_code": row.reason_code,
                            "decision_type": row.decision_type,
                            "exchange_error": row.exchange_error_snippet,
                            "message": body[:2000],
                        },
                        suspects=suspects,
                    )
                )
                break  # one finding per message
    return findings


# --------------------------------------------------------------------------
# RULE 3 - SL/TP price & quantity sanity
# --------------------------------------------------------------------------
def detect_price_sanity(db, now: datetime) -> list[dict]:
    findings: list[dict] = []
    window_start = now - timedelta(hours=WINDOW_HOURS())

    legs = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.status.in_(ACTIVE_STATUSES),
            ExchangeOrder.parent_order_id.isnot(None),
            ExchangeOrder.created_at >= window_start,
        )
        .all()
    )

    for leg in legs:
        role = _role_of(leg)
        if role is None:
            continue
        parent = (
            db.query(ExchangeOrder)
            .filter(ExchangeOrder.exchange_order_id == leg.parent_order_id)
            .first()
        )
        if not parent:
            continue
        entry_px = _entry_price(parent)
        leg_px = _f(leg.price)
        if not entry_px or not leg_px:
            continue

        is_long = parent.side == OrderSideEnum.BUY
        base_ev = {
            "leg_order_id": leg.exchange_order_id,
            "leg_role": role,
            "leg_type": leg.order_type,
            "leg_price": leg_px,
            "leg_trigger": _f(leg.trigger_condition),
            "leg_qty": _f(leg.quantity),
            "entry_order_id": parent.exchange_order_id,
            "entry_side": str(parent.side),
            "entry_price": entry_px,
            "entry_qty": _filled_qty(parent),
            "symbol": leg.symbol,
        }

        # -- direction sanity ------------------------------------------------
        bad_direction = (
            (is_long and role == "SL" and leg_px >= entry_px)
            or (is_long and role == "TP" and leg_px <= entry_px)
            or ((not is_long) and role == "SL" and leg_px <= entry_px)
            or ((not is_long) and role == "TP" and leg_px >= entry_px)
        )
        if bad_direction:
            side_txt = "LONG" if is_long else "SHORT"
            expect = "por debajo" if (is_long and role == "SL") or ((not is_long) and role == "TP") else "por encima"
            findings.append(
                _finding(
                    kind=f"{role}_WRONG_SIDE_OF_ENTRY",
                    severity="high",
                    symbol=leg.symbol,
                    anchor=leg.exchange_order_id,
                    title=f"{role} colocado al lado equivocado de la entrada",
                    detail=(
                        f"Posición <b>{side_txt}</b> en {leg.symbol}: entrada @ ${entry_px:,.4f}, "
                        f"pero el {role} está @ ${leg_px:,.4f} — debería estar {expect} de la entrada.\n"
                        f"Tal como está, el {role} se dispara inmediatamente o nunca."
                    ),
                    evidence=base_ev,
                    suspects=[
                        "app/services/exchange_sync.py::_create_sl_tp_impl (cálculo de precios, línea ~3519)",
                        "app/services/tp_sl_order_creator.py::get_closing_side_from_entry (línea ~38)",
                    ],
                )
            )

        # -- trigger vs limit price ------------------------------------------
        trig = _f(leg.trigger_condition)
        if trig and leg_px and abs(trig - leg_px) / leg_px > PRICE_TOLERANCE():
            findings.append(
                _finding(
                    kind="TRIGGER_PRICE_MISMATCH",
                    severity="medium",
                    symbol=leg.symbol,
                    anchor=f"{leg.exchange_order_id}:trigger",
                    title=f"Trigger del {role} no coincide con su precio límite",
                    detail=(
                        f"{role} <code>{leg.exchange_order_id}</code> ({leg.symbol}): "
                        f"trigger ${trig:,.4f} vs precio ${leg_px:,.4f} "
                        f"({abs(trig - leg_px) / leg_px * 100:.2f}% de diferencia).\n"
                        f"El notificador ya marca esto con ⚠️ «debe ser igual a SL/TP price»."
                    ),
                    evidence=base_ev,
                    suspects=[
                        "app/services/tp_sl_order_creator.py::create_stop_loss_order (línea ~681)",
                        "app/services/tp_sl_order_creator.py::create_take_profit_order (línea ~417)",
                    ],
                )
            )

        # -- quantity coverage -------------------------------------------------
        entry_qty = _filled_qty(parent)
        leg_qty = _f(leg.quantity)
        if entry_qty and leg_qty and abs(leg_qty - entry_qty) / entry_qty > QTY_TOLERANCE():
            findings.append(
                _finding(
                    kind="PROTECTION_QTY_MISMATCH",
                    severity="medium",
                    symbol=leg.symbol,
                    anchor=f"{leg.exchange_order_id}:qty",
                    title=f"Cantidad del {role} no cubre la posición",
                    detail=(
                        f"{role} <code>{leg.exchange_order_id}</code> cubre {leg_qty:,.6f} "
                        f"pero la entrada llenó {entry_qty:,.6f} "
                        f"({(leg_qty - entry_qty) / entry_qty * 100:+.2f}%).\n"
                        f"Parte de la posición queda sin proteger (o se intenta vender de más)."
                    ),
                    evidence=base_ev,
                    suspects=[
                        "app/services/exchange_sync.py::_create_sl_tp_impl (redondeo de cantidad)",
                        "app/services/tp_sl_order_creator.py (quantity precision)",
                    ],
                )
            )
    return findings


# --------------------------------------------------------------------------
# RULE 4 - orphan protection legs and OCO leaks
# --------------------------------------------------------------------------
def detect_orphans_and_oco(db, now: datetime) -> list[dict]:
    findings: list[dict] = []
    grace = timedelta(minutes=GRACE_MINUTES())

    # -- orphans: an active SL/TP whose parent entry is gone or dead ---------
    active_legs = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.status.in_(ACTIVE_STATUSES),
            ExchangeOrder.parent_order_id.isnot(None),
        )
        .all()
    )
    for leg in active_legs:
        role = _role_of(leg)
        if role is None:
            continue
        parent = (
            db.query(ExchangeOrder)
            .filter(ExchangeOrder.exchange_order_id == leg.parent_order_id)
            .first()
        )
        ev = {
            "leg_order_id": leg.exchange_order_id,
            "leg_role": role,
            "leg_status": str(leg.status),
            "parent_order_id": leg.parent_order_id,
            "parent_status": str(parent.status) if parent else None,
            "symbol": leg.symbol,
        }
        if parent is None:
            findings.append(
                _finding(
                    kind="ORPHAN_PROTECTION_NO_PARENT",
                    severity="medium",
                    symbol=leg.symbol,
                    anchor=leg.exchange_order_id,
                    title=f"{role} activo sin orden de entrada asociada",
                    detail=(
                        f"El {role} <code>{leg.exchange_order_id}</code> ({leg.symbol}) sigue activo, "
                        f"pero su parent <code>{leg.parent_order_id}</code> no existe en la BD.\n"
                        f"O la entrada nunca se guardó, o el enlace parent_order_id apunta mal."
                    ),
                    evidence=ev,
                    suspects=[
                        "app/services/exchange_sync.py (asignación de parent_order_id)",
                        "app/services/sl_tp_checker.py::send_orphan_order_alert (línea ~1142)",
                    ],
                )
            )
        elif parent.status in DEAD_STATUSES:
            findings.append(
                _finding(
                    kind="ORPHAN_PROTECTION_DEAD_PARENT",
                    severity="high",
                    symbol=leg.symbol,
                    anchor=f"{leg.exchange_order_id}:dead",
                    title=f"{role} activo sobre una entrada {parent.status}",
                    detail=(
                        f"El {role} <code>{leg.exchange_order_id}</code> sigue vivo en el exchange, "
                        f"pero la entrada <code>{parent.exchange_order_id}</code> está "
                        f"<b>{parent.status}</b>.\n"
                        f"Riesgo: una orden de salida sin posición que cerrar."
                    ),
                    evidence=ev,
                    suspects=[
                        "app/services/exchange_sync.py (limpieza de legs al cancelar entrada)",
                        "app/services/tp_sl_order_creator.py::cancel_protection_leg_on_exchange (línea ~80)",
                    ],
                )
            )

    # -- OCO leak: one leg filled, sibling still alive ----------------------
    # Se emparejan por oco_group_id cuando existe, y por parent_order_id + rol
    # opuesto cuando no. Filtrar solo por oco_group_id dejaba ciego al detector
    # en la mayoria de las filas: censo del 26-ago-2026 sobre 767 FILLED en
    # produccion -> 179 de 276 TAKE_PROFIT y 50 de 81 STOP_LOSS tienen
    # oco_group_id NULL. Es el mismo emparejamiento en dos pasos que ya hacen
    # exchange_sync._find_oco_siblings (~2730), sl_tp_checker (~1082) y
    # routes_orders (~1783); este detector era el unico sin el, y es el que
    # dispara la alerta de doble ejecucion.
    filled_legs = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            or_(
                ExchangeOrder.oco_group_id.isnot(None),
                ExchangeOrder.parent_order_id.isnot(None),
            ),
            ExchangeOrder.exchange_update_time >= now - timedelta(hours=WINDOW_HOURS()),
            ExchangeOrder.exchange_update_time <= now - grace,
        )
        .all()
    )
    seen_pairs: set = set()
    for leg in filled_legs:
        leg_role = _role_of(leg)
        if leg_role is None:
            continue
        if leg.oco_group_id:
            siblings = (
                db.query(ExchangeOrder)
                .filter(
                    ExchangeOrder.oco_group_id == leg.oco_group_id,
                    ExchangeOrder.exchange_order_id != leg.exchange_order_id,
                    ExchangeOrder.status.in_(ACTIVE_STATUSES),
                )
                .all()
            )
        else:
            # Sin grupo OCO: el hermano es la pata del rol CONTRARIO que cuelga
            # de la misma entrada. Exigir rol opuesto evita emparejar dos
            # protecciones del mismo tipo creadas en reintentos sucesivos.
            # _role_of normaliza a "SL" / "TP", no a los valores crudos de
            # order_role. Compararlo contra "STOP_LOSS"/"TAKE_PROFIT" no casa
            # nunca y deja el detector igual de ciego que antes.
            opposite = "SL" if leg_role == "TP" else "TP"
            siblings = [
                cand
                for cand in db.query(ExchangeOrder)
                .filter(
                    ExchangeOrder.parent_order_id == leg.parent_order_id,
                    ExchangeOrder.exchange_order_id != leg.exchange_order_id,
                    ExchangeOrder.status.in_(ACTIVE_STATUSES),
                )
                .all()
                if _role_of(cand) == opposite
            ]
        for sib in siblings:
            # Las dos patas de un par pueden llegar aqui por separado; un
            # hallazgo por pareja, no dos.
            pair_key = (leg.exchange_order_id, sib.exchange_order_id)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            findings.append(
                _finding(
                    kind="OCO_SIBLING_NOT_CANCELLED",
                    severity="high",
                    symbol=leg.symbol,
                    anchor=f"{leg.oco_group_id or ('parent:' + str(leg.parent_order_id))}:{sib.exchange_order_id}",
                    title="Pata OCO no cancelada tras ejecutarse la otra",
                    detail=(
                        f"En el grupo OCO <code>{leg.oco_group_id or 'sin grupo, enlazadas por entrada ' + str(leg.parent_order_id)}</code> ({leg.symbol}) se ejecutó "
                        f"el {_role_of(leg)} <code>{leg.exchange_order_id}</code>, pero el "
                        f"{_role_of(sib)} <code>{sib.exchange_order_id}</code> sigue "
                        f"<b>{sib.status}</b>.\n"
                        f"Riesgo real de <b>doble ejecución</b>: puede vender una posición que ya se cerró."
                    ),
                    evidence={
                        "oco_group_id": leg.oco_group_id,
                        "executed_order_id": leg.exchange_order_id,
                        "executed_role": _role_of(leg),
                        "executed_at": _as_utc(leg.exchange_update_time).isoformat() if leg.exchange_update_time else None,
                        "dangling_order_id": sib.exchange_order_id,
                        "dangling_role": _role_of(sib),
                        "dangling_status": str(sib.status),
                        "symbol": leg.symbol,
                    },
                    suspects=[
                        "app/services/exchange_sync.py (auto-cancel del sibling OCO, línea ~4141)",
                        "app/services/tp_sl_order_creator.py::create_oco_protection_orders (línea ~249)",
                    ],
                )
            )
    return findings


def _exchange_order_type(order_id: str) -> Optional[str]:
    """Real order type as the exchange holds it, or None if it cannot be read.

    Spot ``get-order-detail`` returns empty for trigger ids, so fall back to
    advanced detail — the same two-step ``exchange_sync`` already relies on.
    """
    try:
        from app.services.brokers.crypto_com_trade import trade_client
    except Exception as e:  # pragma: no cover - import guard
        logger.error(f"[WATCHDOG] cannot import trade_client: {e}")
        return None

    for fetch in (trade_client.get_order_detail, trade_client.get_advanced_order_detail):
        try:
            raw = fetch(str(order_id))
        except Exception:
            continue
        result = (raw or {}).get("result") or {}
        data = result.get("data")
        if isinstance(data, list) and data:
            result = data[0]
        order_type = str(result.get("type") or result.get("order_type") or "").strip().upper()
        if order_type:
            return order_type
    return None


def _parent_position_is_live(db, order: ExchangeOrder) -> bool:
    """True when the entry this leg protects still holds quantity."""
    parent_id = getattr(order, "parent_order_id", None)
    if not parent_id:
        return False
    parent = (
        db.query(ExchangeOrder)
        .filter(ExchangeOrder.exchange_order_id == str(parent_id))
        .first()
    )
    if parent is None or parent.status != OrderStatusEnum.FILLED:
        return False
    return (_filled_qty(parent) or 0.0) > 0.0


def detect_protection_type_mismatch(db, now: datetime) -> list[dict]:
    """A live protection leg whose real exchange type is not protective.

    #521: an order booked as ``STOP_LOSS`` that the exchange actually holds as
    a plain LIMIT never triggers. The position reads as protected and is not,
    and nothing in the books can reveal it: ``order_role`` is what the bot
    wrote and ``order_type`` is what the bot intended — only the exchange knows
    what it created. So this detector asks the exchange, one call per live leg.
    """
    live_legs = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.order_role.in_(("STOP_LOSS", "TAKE_PROFIT")),
            ExchangeOrder.status.in_(ACTIVE_STATUSES),
        )
        .order_by(ExchangeOrder.symbol.asc(), ExchangeOrder.id.asc())
        .all()
    )

    budget = MAX_TYPE_CHECKS()
    checked = live_legs[:budget] if budget > 0 else live_legs
    skipped = len(live_legs) - len(checked)

    findings: list[dict] = []
    unverified: list[str] = []

    for leg in checked:
        order_id = str(getattr(leg, "exchange_order_id", "") or "")
        role = (getattr(leg, "order_role", "") or "").upper()
        if not order_id or role not in ("STOP_LOSS", "TAKE_PROFIT"):
            continue

        real_type = _exchange_order_type(order_id)
        if real_type is None:
            unverified.append(f"{leg.symbol}:{order_id}")
            continue

        allowed = _SL_EXCHANGE_TYPES if role == "STOP_LOSS" else _TP_EXCHANGE_TYPES
        if real_type in allowed:
            continue

        position_live = _parent_position_is_live(db, leg)
        # A fake stop on a live position is an unprotected position, not a
        # bookkeeping nit — that is the #521 case and it pages.
        severity = "high" if (role == "STOP_LOSS" and position_live) else "medium"
        findings.append(
            _finding(
                kind="protection_type_mismatch",
                severity=severity,
                symbol=leg.symbol,
                anchor=order_id,
                title=f"{role} falso en {leg.symbol}: el exchange lo tiene como {real_type}",
                detail=(
                    f"La orden <code>{order_id}</code> ({leg.symbol}) figura en los libros como "
                    f"<b>{role}</b>, pero el exchange la tiene como <b>{real_type}</b>.\n"
                    f"Un {role} que no es de tipo protector <b>no se dispara</b>: "
                    f"la posición parece protegida y no lo está.\n"
                    f"Posición del padre: <b>{'VIVA' if position_live else 'no viva'}</b>."
                ),
                evidence={
                    "order_id": order_id,
                    "symbol": leg.symbol,
                    "side": str(leg.side),
                    "order_role": role,
                    "order_type_books": getattr(leg, "order_type", None),
                    "order_type_exchange": real_type,
                    "status": str(leg.status),
                    "parent_order_id": getattr(leg, "parent_order_id", None),
                    "parent_position_live": position_live,
                },
                suspects=[
                    "app/services/tp_sl_order_creator.py (creación de la pata de protección)",
                    "app/services/brokers/crypto_com_trade.py::_create_order_try_variants",
                ],
            )
        )

    # Never report a clean run that was actually a partial one.
    if unverified:
        findings.append(
            _finding(
                kind="protection_type_unverified",
                severity="medium",
                symbol=None,
                anchor=f"{now.date().isoformat()}:{len(unverified)}",
                title=f"{len(unverified)} protecciones sin poder verificar contra el exchange",
                detail=(
                    f"El exchange no devolvió tipo para {len(unverified)} patas de protección "
                    f"vivas, así que <b>no se puede afirmar que sean correctas</b>.\n"
                    f"Órdenes: <code>{', '.join(unverified[:20])}</code>"
                    + (" …" if len(unverified) > 20 else "")
                ),
                evidence={"unverified": unverified[:50], "count": len(unverified)},
                suspects=["app/services/brokers/crypto_com_trade.py::get_advanced_order_detail"],
            )
        )

    if skipped > 0:
        findings.append(
            _finding(
                kind="protection_type_check_truncated",
                severity="medium",
                symbol=None,
                anchor=f"{now.date().isoformat()}:{skipped}",
                title=f"{skipped} protecciones vivas quedaron sin comprobar (tope por ejecución)",
                detail=(
                    f"Hay {len(live_legs)} patas de protección vivas y el tope por ejecución es "
                    f"{budget}, así que <b>{skipped} no se comprobaron</b>. Subir "
                    f"<code>WATCHDOG_MAX_TYPE_CHECKS</code> si esto se repite."
                ),
                evidence={"live_legs": len(live_legs), "budget": budget, "skipped": skipped},
                suspects=["app/services/logic_watchdog.py::detect_protection_type_mismatch"],
            )
        )

    return findings


DETECTORS = (
    detect_missing_protection,
    detect_failure_strings,
    detect_price_sanity,
    detect_orphans_and_oco,
    detect_protection_type_mismatch,
)


# --------------------------------------------------------------------------
# persistence + alerting
# --------------------------------------------------------------------------
def persist_and_alert(db, findings: list[dict], dry_run: bool = False) -> dict:
    from app.models.watchdog import (
        WatchdogAnomaly,
        ANOMALY_STATUS_ALERTED,
        ANOMALY_STATUS_NEW,
    )
    now = datetime.now(timezone.utc)
    created, updated, alerted, skipped = 0, 0, 0, 0
    to_alert: list[Any] = []

    for f in findings:
        existing = (
            db.query(WatchdogAnomaly)
            .filter(WatchdogAnomaly.fingerprint == f["fingerprint"])
            .first()
        )
        if existing:
            existing.last_seen_at = now
            existing.occurrences = (existing.occurrences or 1) + 1
            updated += 1
            if existing.status == ANOMALY_STATUS_NEW and not dry_run:
                to_alert.append(existing)
            else:
                skipped += 1  # already alerted / ignored / being fixed
            continue

        anomaly = WatchdogAnomaly(
            fingerprint=f["fingerprint"],
            kind=f["kind"],
            severity=f["severity"],
            symbol=f["symbol"],
            title=f["title"][:200],
            detail=f["detail"],
            evidence_json=json.dumps(f["evidence"], default=str),
            suspect_paths="\n".join(f["suspects"]),
            status=ANOMALY_STATUS_NEW,
            occurrences=1,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(anomaly)
        created += 1
        to_alert.append(anomaly)

    if dry_run:
        db.rollback()
        return {
            "dry_run": True,
            "findings": len(findings),
            "would_create": created,
            "would_update": updated,
            "would_alert": len(to_alert),
        }

    db.commit()

    from app.services.watchdog_inline import send_anomaly_alert

    # Highest severity first, capped so a storm cannot flood the channel.
    order = {"high": 0, "medium": 1, "low": 2}
    to_alert.sort(key=lambda a: order.get((a.severity or "medium"), 1))
    cap = MAX_ALERTS_PER_RUN()
    suppressed = max(0, len(to_alert) - cap)

    for anomaly in to_alert[:cap]:
        ok, message_id, chat_id = send_anomaly_alert(anomaly)
        if ok:
            anomaly.status = ANOMALY_STATUS_ALERTED
            anomaly.alerted_at = now
            anomaly.telegram_message_id = message_id
            anomaly.telegram_chat_id = str(chat_id) if chat_id else None
            alerted += 1
    db.commit()

    if suppressed:
        logger.warning(
            f"[WATCHDOG] {suppressed} anomalies not alerted this run "
            f"(cap WATCHDOG_MAX_ALERTS_PER_RUN={cap}); they stay 'new' and go out next run"
        )

    return {
        "findings": len(findings),
        "created": created,
        "updated": updated,
        "alerted": alerted,
        "already_handled": skipped,
        "suppressed_by_cap": suppressed,
    }


def run_watchdog(db=None, dry_run: bool = False) -> dict:
    """Entry point. Returns a summary dict."""
    if not is_enabled():
        return {"skipped": "WATCHDOG_ENABLED=false"}

    own_session = db is None
    if own_session:
        from app.database import create_db_session

        db = create_db_session()

    try:
        ensure_watchdog_tables(db)
        now = datetime.now(timezone.utc)
        findings: list[dict] = []
        per_rule: dict[str, int] = {}
        for detector in DETECTORS:
            try:
                got = detector(db, now)
                per_rule[detector.__name__] = len(got)
                findings.extend(got)
            except Exception as e:
                logger.error(f"[WATCHDOG] detector {detector.__name__} failed: {e}", exc_info=True)
                per_rule[detector.__name__] = -1

        # de-dup within the run itself
        seen: set[str] = set()
        unique: list[dict] = []
        for f in findings:
            if f["fingerprint"] in seen:
                continue
            seen.add(f["fingerprint"])
            unique.append(f)

        result = persist_and_alert(db, unique, dry_run=dry_run)
        result["per_rule"] = per_rule
        logger.info(f"[WATCHDOG] run complete: {result}")
        return result
    finally:
        if own_session:
            try:
                db.close()
            except Exception:
                pass


if __name__ == "__main__":  # pragma: no cover
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Run the ATP logic watchdog")
    ap.add_argument("--dry-run", action="store_true", help="detect only, write nothing, send nothing")
    ap.add_argument("--hours", type=int, help="lookback window in hours")
    args = ap.parse_args()
    if args.hours:
        os.environ["WATCHDOG_WINDOW_HOURS"] = str(args.hours)
    print(json.dumps(run_watchdog(dry_run=args.dry_run), indent=2, default=str))
