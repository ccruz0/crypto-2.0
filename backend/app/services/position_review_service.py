"""Daily Position Review — prompt the operator about open positions (close / protect / snooze).

Once a day a Telegram message is sent for every open position (long or short). When the
position is missing SL and/or TP, the message states that problem clearly and offers:
**Crear SL**, **Crear TP**, and **Cerrar** (market sell for LONG / buy for SHORT). Fully
protected positions still get a simple close/snooze prompt. **Mantener 30 días** snoozes
prompts for that position for 30 days. A position that is closed and later re-opened is
treated as a NEW case and prompted again even if the old one was snoozed.

Design notes
------------
- Positions come from the live account summary (``trade_client.get_account_summary``), the
  same authoritative source used elsewhere. Net quantity < 0 => SHORT, > 0 => LONG.
- Fiat balances and dust are ignored.
- Snooze / reopen state lives in ``position_review_state`` keyed by "{symbol}:{side}".
- Pure logic (``evaluate_positions``) is separated from I/O (telegram send, order placement)
  so it can be unit-tested without the network.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# --- Config -----------------------------------------------------------------
# Fiat + stablecoins are cash/debt, never "positions" to prompt about. Extra entries can be
# added via env POSITION_REVIEW_EXTRA_STABLES (comma-separated).
_STABLE_AND_FIAT = {
    # USD stablecoins
    "USDT", "USDC", "DAI", "TUSD", "BUSD", "FDUSD", "PYUSD", "USDP", "GUSD", "USDD",
    "LUSD", "SUSD", "USDE", "FRAX", "USTC", "PAX", "USDG",
    # EUR stablecoins
    "EURT", "EURS", "EURC", "AGEUR",
    # Fiat
    "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "SGD", "BRL", "KRW", "TRY",
}
_EXTRA_STABLES = {
    c.strip().upper()
    for c in os.getenv("POSITION_REVIEW_EXTRA_STABLES", "").split(",")
    if c.strip()
}
FIAT_CURRENCIES = _STABLE_AND_FIAT | _EXTRA_STABLES
DUST_USD = float(os.getenv("POSITION_REVIEW_DUST_USD", "1.0"))
SNOOZE_DAYS = int(os.getenv("POSITION_REVIEW_SNOOZE_DAYS", "30"))
REVIEW_HOUR_UTC = int(os.getenv("POSITION_REVIEW_HOUR_UTC", "9"))  # daily send hour (UTC)

# --- Callback data prefixes (parsed by stripping the prefix; key may contain ':') ---
PREFIX_CLOSE = "posrev_close:"
PREFIX_CONFIRM = "posrev_confirm:"
PREFIX_CANCEL = "posrev_cancel:"
PREFIX_SNOOZE = "posrev_snooze:"


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _as_aware(dt: Optional[datetime]) -> Optional[datetime]:
    """Treat a tz-naive datetime (e.g. read back from SQLite) as UTC, for safe comparison."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _position_key(symbol: str, side: str) -> str:
    return f"{symbol.upper()}:{side.upper()}"


def _resolve_symbol(db: Session, currency: str) -> str:
    """Best-effort trading instrument for a base currency (e.g. DOT -> DOT_USD).

    Uses the most recent exchange_orders row for that base so we close on the exact pair
    the position was opened on (DOT_USD vs ETH_USDT differ); falls back to ``{cur}_USD``.
    """
    try:
        from sqlalchemy import text
        row = db.execute(
            text(
                "select symbol from exchange_orders where symbol like :p "
                "order by coalesce(exchange_create_time, created_at) desc limit 1"
            ),
            {"p": f"{currency.upper()}\\_%"},
        ).first()
        if row and row[0]:
            return str(row[0]).upper()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("posrev: symbol resolve failed for %s: %s", currency, e)
    return f"{currency.upper()}_USD"


def enumerate_open_positions(db: Session) -> List[Dict[str, Any]]:
    """Return the live open positions worth prompting about (excludes fiat and dust)."""
    from app.services.brokers.crypto_com_trade import trade_client

    summary = trade_client.get_account_summary() or {}
    positions: List[Dict[str, Any]] = []
    for acc in (summary.get("accounts") or []):
        currency = str(acc.get("currency", "")).upper()
        if not currency or currency in FIAT_CURRENCIES:
            continue
        try:
            qty = float(acc.get("quantity", acc.get("balance", "0")) or 0)
        except (TypeError, ValueError):
            continue
        if qty == 0:
            continue
        try:
            market_value = float(acc.get("market_value") or 0)
        except (TypeError, ValueError):
            market_value = 0.0
        if abs(market_value) < DUST_USD:
            continue
        side = "SHORT" if qty < 0 else "LONG"
        symbol = _resolve_symbol(db, currency)
        positions.append(
            {
                "currency": currency,
                "symbol": symbol,
                "side": side,
                "qty": abs(qty),
                "market_value": market_value,
                "key": _position_key(symbol, side),
            }
        )
    return positions


def _get_or_create_state(db: Session, position_key: str):
    from app.models.position_review_state import PositionReviewState

    row = (
        db.query(PositionReviewState)
        .filter(PositionReviewState.position_key == position_key)
        .first()
    )
    if row is None:
        row = PositionReviewState(position_key=position_key, last_seen_qty=0)
        db.add(row)
        db.flush()
    return row


def evaluate_positions(
    db: Session, positions: List[Dict[str, Any]], now: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    """Update per-position state and return the positions to alert on right now.

    State machine (per key):
      - closed since last run (was open, now absent)  -> reset snooze, last_seen_qty=0
      - new or re-opened (last_seen_qty == 0, now open) -> clear snooze -> ALERT
      - snoozed and continuously open                  -> skip
      - otherwise                                      -> ALERT
    """
    from app.models.position_review_state import PositionReviewState

    now = _now(now)
    current_keys = {p["key"] for p in positions}

    # Mark positions that disappeared (closed) since the last run: reset so a future
    # reopen is a fresh case.
    open_rows = (
        db.query(PositionReviewState)
        .filter(PositionReviewState.last_seen_qty != 0)
        .all()
    )
    for row in open_rows:
        if row.position_key not in current_keys:
            row.last_seen_qty = 0
            row.snoozed_until = None

    to_alert: List[Dict[str, Any]] = []
    for p in positions:
        row = _get_or_create_state(db, p["key"])
        reopened_or_new = float(row.last_seen_qty or 0) == 0
        if reopened_or_new:
            row.snoozed_until = None  # fresh case: never inherit an old snooze

        snoozed = row.snoozed_until is not None and _as_aware(row.snoozed_until) > now
        if not snoozed:
            row.last_alerted_at = now
            to_alert.append(p)

        row.last_seen_qty = p["qty"]

    db.commit()
    return to_alert


def snooze_position(db: Session, position_key: str, now: Optional[datetime] = None) -> datetime:
    """Snooze close-prompts for a position for SNOOZE_DAYS. Returns the new snoozed_until."""
    now = _now(now)
    until = now + timedelta(days=SNOOZE_DAYS)
    row = _get_or_create_state(db, position_key)
    row.snoozed_until = until
    db.commit()
    logger.info("posrev: snoozed %s until %s", position_key, until)
    return until  # aware; do not re-read row (SQLite would return it tz-naive)


# --- Telegram rendering -----------------------------------------------------
def _close_action_label(side: str) -> str:
    """Market close wording: LONG closes with SELL, SHORT covers with BUY."""
    return "vender" if str(side).upper() == "LONG" else "comprar"


def _close_button_text(side: str) -> str:
    return f"🔴 Cerrar ({_close_action_label(side)})"


def _missing_protection_items(has_sl: bool, has_tp: bool) -> List[str]:
    missing: List[str] = []
    if not has_sl:
        missing.append("SL")
    if not has_tp:
        missing.append("TP")
    return missing


def _get_protection_status(db: Session, symbol: str) -> Dict[str, bool]:
    """Best-effort SL/TP presence for a live position (exchange open orders, DB fallback).

    On any failure assumes unprotected so the operator still sees Create SL/TP options.
    """
    symbol_u = str(symbol).upper()
    variants = {symbol_u}
    if symbol_u.endswith("_USDT"):
        variants.add(symbol_u.replace("_USDT", "_USD"))
    elif symbol_u.endswith("_USD"):
        variants.add(symbol_u.replace("_USD", "_USDT"))

    try:
        from app.services.brokers.crypto_com_trade import trade_client

        all_orders = (trade_client.get_open_orders() or {}).get("data") or []
        matched = []
        for order in all_orders:
            inst = str(order.get("instrument_name") or "").replace("/", "_").upper()
            if inst in variants:
                matched.append(order)

        has_sl = False
        has_tp = False
        for o in matched:
            status = (o.get("order_status") or o.get("status") or "").upper()
            if status and status not in ("ACTIVE", "NEW", "PENDING"):
                continue
            otype = str(o.get("order_type") or "").lower()
            if any(t in otype for t in ("stop", "stop_loss")):
                has_sl = True
            if "take" in otype and "profit" in otype:
                has_tp = True
            elif "profit" in otype and "take" in otype:
                has_tp = True
        return {"has_sl": has_sl, "has_tp": has_tp}
    except Exception as e:
        logger.warning("posrev: exchange protection check failed for %s: %s", symbol, e)

    try:
        from sqlalchemy import or_

        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum

        active = [
            OrderStatusEnum.NEW,
            OrderStatusEnum.ACTIVE,
            OrderStatusEnum.PENDING,
        ]
        sl_n = (
            db.query(ExchangeOrder)
            .filter(
                or_(*[ExchangeOrder.symbol == v for v in variants]),
                ExchangeOrder.order_type.in_(["STOP_LIMIT", "STOP_LOSS", "STOP_LOSS_LIMIT"]),
                ExchangeOrder.status.in_(active),
            )
            .count()
        )
        tp_n = (
            db.query(ExchangeOrder)
            .filter(
                or_(*[ExchangeOrder.symbol == v for v in variants]),
                ExchangeOrder.order_type.in_(["TAKE_PROFIT_LIMIT", "TAKE_PROFIT"]),
                ExchangeOrder.status.in_(active),
            )
            .count()
        )
        return {"has_sl": sl_n > 0, "has_tp": tp_n > 0}
    except Exception as e:
        logger.warning("posrev: DB protection check failed for %s: %s", symbol, e)
        return {"has_sl": False, "has_tp": False}


def enrich_positions_with_protection(
    db: Session, positions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Attach has_sl / has_tp to each position dict (mutates copies)."""
    enriched: List[Dict[str, Any]] = []
    for p in positions:
        row = dict(p)
        status = _get_protection_status(db, row["symbol"])
        row["has_sl"] = bool(status.get("has_sl"))
        row["has_tp"] = bool(status.get("has_tp"))
        enriched.append(row)
    return enriched


def _alert_keyboard(p: Dict[str, Any]) -> dict:
    """Inline actions: create missing SL/TP and/or market-close (+ snooze)."""
    position_key = p["key"]
    symbol = p["symbol"]
    side = p.get("side", "LONG")
    has_sl = bool(p.get("has_sl"))
    has_tp = bool(p.get("has_tp"))
    missing = _missing_protection_items(has_sl, has_tp)

    rows: List[List[Dict[str, str]]] = []
    if missing:
        create_row: List[Dict[str, str]] = []
        if not has_sl:
            create_row.append({"text": "🛑 Crear SL", "callback_data": f"create_sl_{symbol}"})
        if not has_tp:
            create_row.append({"text": "🚀 Crear TP", "callback_data": f"create_tp_{symbol}"})
        if create_row:
            rows.append(create_row)
        if not has_sl and not has_tp:
            rows.append(
                [{"text": "🛡️ Crear SL y TP", "callback_data": f"create_sl_tp_{symbol}"}]
            )

    rows.append(
        [
            {"text": _close_button_text(side), "callback_data": f"{PREFIX_CLOSE}{position_key}"},
            {"text": "😴 Mantener 30 días", "callback_data": f"{PREFIX_SNOOZE}{position_key}"},
        ]
    )
    return {"inline_keyboard": rows}


def _confirm_keyboard(position_key: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Confirmar cierre", "callback_data": f"{PREFIX_CONFIRM}{position_key}"},
                {"text": "↩️ Cancelar", "callback_data": f"{PREFIX_CANCEL}{position_key}"},
            ]
        ]
    }


def _format_alert(p: Dict[str, Any]) -> str:
    """Spanish operator copy: state the problem when SL/TP is missing, then list options."""
    side = str(p.get("side", "LONG")).upper()
    has_sl = bool(p.get("has_sl"))
    has_tp = bool(p.get("has_tp"))
    missing = _missing_protection_items(has_sl, has_tp)
    close_verb = _close_action_label(side)
    close_side = "SELL" if side == "LONG" else "BUY"

    header = "📋 <b>REVISIÓN DE POSICIÓN</b>\n\n"
    facts = (
        f"📈 Símbolo: <b>{p['symbol']}</b>\n"
        f"🔄 Lado: <b>{side}</b>\n"
        f"📦 Cantidad: {p['qty']}\n"
        f"💵 Valor: ${float(p['market_value']):.2f}\n"
    )

    if missing:
        sl_status = "✅ Activo" if has_sl else "❌ Falta"
        tp_status = "✅ Activo" if has_tp else "❌ Falta"
        missing_es = " y ".join(missing)
        problem = (
            f"⚠️ <b>Problema:</b> hay una posición abierta <b>sin {missing_es}</b>.\n"
            "Sin esa protección la posición queda expuesta.\n\n"
            f"🛑 Stop Loss: {sl_status}\n"
            f"🚀 Take Profit: {tp_status}\n\n"
            "<b>Opciones:</b>\n"
        )
        options: List[str] = []
        n = 1
        if not has_sl:
            options.append(f"{n}. Crear un SL")
            n += 1
        if not has_tp:
            options.append(f"{n}. Crear un TP")
            n += 1
        options.append(
            f"{n}. Cerrar la posición ({close_verb} a mercado → orden {close_side})"
        )
        return header + facts + "\n" + problem + "\n".join(options) + "\n\nElige un botón abajo."

    return (
        header
        + facts
        + "\n"
        + "✅ Esta posición ya tiene SL y TP.\n\n"
        + f"¿Quieres cerrarla de todas formas ({close_verb} a mercado → {close_side})?"
    )


def send_review_alerts(positions: List[Dict[str, Any]]) -> int:
    """Send one Telegram prompt per position. Returns how many were sent."""
    from app.services.telegram_notifier import telegram_notifier

    sent = 0
    for p in positions:
        try:
            ok = telegram_notifier.send_message(
                _format_alert(p), reply_markup=_alert_keyboard(p)
            )
            if ok:
                sent += 1
        except Exception as e:
            logger.error("posrev: failed to send alert for %s: %s", p.get("key"), e, exc_info=True)
    return sent


def run_review(db: Session, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Enumerate positions, update state, and send prompts for the non-snoozed ones."""
    positions = enumerate_open_positions(db)
    to_alert = evaluate_positions(db, positions, now=now)
    to_alert = enrich_positions_with_protection(db, to_alert)
    sent = send_review_alerts(to_alert)
    logger.info("posrev: reviewed %d positions, alerted %d, sent %d", len(positions), len(to_alert), sent)
    return {"open": len(positions), "alerted": len(to_alert), "sent": sent}


# --- Close execution --------------------------------------------------------
def execute_close(db: Session, symbol: str, side: str) -> Dict[str, Any]:
    """Close an open position with a market order in the SAME margin mode it was opened.

    Re-reads the live position for accuracy. A SHORT is covered with a margin BUY (notional);
    a LONG is closed with a SELL (margin if it is a margin long, else spot). Returns the
    broker result or an ``error`` dict. Never raises.
    """
    from app.services.brokers.crypto_com_trade import trade_client

    try:
        base = symbol.split("_")[0].upper()
        summary = trade_client.get_account_summary() or {}
        acc = next((a for a in (summary.get("accounts") or []) if str(a.get("currency", "")).upper() == base), None)
        if acc is None:
            return {"error": "POSITION_NOT_FOUND", "message": f"No live position for {symbol}"}
        qty = float(acc.get("quantity", acc.get("balance", "0")) or 0)
        if qty == 0:
            return {"error": "POSITION_ALREADY_FLAT", "message": f"{symbol} is already flat"}
        market_value = abs(float(acc.get("market_value") or 0))

        from app.services.margin_decision_helper import DEFAULT_CONFIGURED_LEVERAGE
        from app.services.risk_config import MAX_LEVERAGE

        # Margin orders require leverage, but it must not exceed the risk cap
        # (else risk_guard rejects with "Leverage N exceeds cap M").
        close_leverage = min(DEFAULT_CONFIGURED_LEVERAGE, MAX_LEVERAGE)

        if qty < 0:  # SHORT -> cover with margin BUY (notional = quote value)
            notional = market_value if market_value > 0 else None
            if not notional:
                return {"error": "NO_PRICE", "message": f"Cannot size close for {symbol}"}
            # A short only exists on margin (is_margin=True); leverage is REQUIRED by the
            # broker for any margin order — omitting it raises "Margin trade requires leverage".
            result = trade_client.place_market_order(
                symbol=symbol, side="BUY", notional=notional,
                is_margin=True, leverage=close_leverage,
                dry_run=False, source="AUTO",
            )
        else:  # LONG -> SELL the base
            available = float(acc.get("available", acc.get("max_withdrawal", qty)) or 0)
            # Spot-available (tolerant of 8-decimal truncation of `available`) -> plain spot
            # SELL. Otherwise it is a margin long: SELL on margin WITH leverage.
            is_margin = available < qty * 0.99
            result = trade_client.place_market_order(
                symbol=symbol, side="SELL", qty=abs(qty),
                is_margin=is_margin,
                leverage=close_leverage if is_margin else None,
                dry_run=False, source="AUTO",
            )
        logger.warning("posrev: close %s %s -> %s", symbol, side, result)
        return result or {"error": "NO_RESULT"}
    except Exception as e:
        logger.error("posrev: execute_close failed for %s: %s", symbol, e, exc_info=True)
        return {"error": "CLOSE_FAILED", "message": str(e)}


# --- Telegram callback handlers (called from the telegram_commands dispatcher) ---
def handle_snooze_callback(chat_id: str, callback_data: str, db: Session) -> bool:
    from app.services.telegram_notifier import telegram_notifier

    key = callback_data[len(PREFIX_SNOOZE):]
    until = snooze_position(db, key)
    telegram_notifier.send_message(
        f"😴 Ok, no te preguntaré por <b>{key}</b> hasta <b>{until:%Y-%m-%d}</b> "
        f"({SNOOZE_DAYS} días). Si la cierras y reabres, volveré a preguntar."
    )
    return True


def handle_close_request_callback(chat_id: str, callback_data: str, db: Session) -> bool:
    """First tap on Close: ask for confirmation (no order placed yet)."""
    from app.services.telegram_notifier import telegram_notifier

    key = callback_data[len(PREFIX_CLOSE):]
    try:
        _symbol, side = key.rsplit(":", 1)
    except ValueError:
        side = "LONG"
    close_verb = _close_action_label(side)
    close_side = "SELL" if str(side).upper() == "LONG" else "BUY"
    telegram_notifier.send_message(
        f"⚠️ ¿Confirmas <b>CERRAR</b> la posición <b>{key}</b>?\n\n"
        f"Esto coloca una orden de mercado real: <b>{close_verb}</b> ({close_side}).",
        reply_markup=_confirm_keyboard(key),
    )
    return True


def handle_cancel_callback(chat_id: str, callback_data: str, db: Session) -> bool:
    from app.services.telegram_notifier import telegram_notifier

    key = callback_data[len(PREFIX_CANCEL):]
    telegram_notifier.send_message(f"↩️ Cierre de <b>{key}</b> cancelado. La posición sigue abierta.")
    return True


def handle_close_confirm_callback(chat_id: str, callback_data: str, db: Session) -> bool:
    """Second tap: actually place the close order."""
    from app.services.telegram_notifier import telegram_notifier

    key = callback_data[len(PREFIX_CONFIRM):]
    try:
        symbol, side = key.rsplit(":", 1)
    except ValueError:
        telegram_notifier.send_message(f"❌ Clave de posición inválida: {key}")
        return False
    result = execute_close(db, symbol, side)
    if result.get("error"):
        telegram_notifier.send_message(f"❌ No se pudo cerrar <b>{key}</b>: {result.get('message') or result['error']}")
        return False
    oid = result.get("order_id") or result.get("exchange_order_id") or "?"
    telegram_notifier.send_message(f"✅ Orden de cierre enviada para <b>{key}</b> (order_id={oid}).")
    return True


def dispatch_callback(chat_id: str, callback_data: str, db: Session) -> bool:
    """Route any posrev_* callback to its handler. Returns False if not a posrev callback."""
    if callback_data.startswith(PREFIX_CONFIRM):
        return handle_close_confirm_callback(chat_id, callback_data, db)
    if callback_data.startswith(PREFIX_CLOSE):
        return handle_close_request_callback(chat_id, callback_data, db)
    if callback_data.startswith(PREFIX_CANCEL):
        return handle_cancel_callback(chat_id, callback_data, db)
    if callback_data.startswith(PREFIX_SNOOZE):
        return handle_snooze_callback(chat_id, callback_data, db)
    return False


# --- Daily scheduler loop ---------------------------------------------------
async def start_position_review_loop() -> None:
    """Fire run_review once per day at REVIEW_HOUR_UTC. Mirrors the daily-report loop."""
    import asyncio

    from app.database import SessionLocal

    logger.info("posrev: daily review loop started (hour=%02d:00 UTC)", REVIEW_HOUR_UTC)
    while True:
        try:
            now = datetime.now(timezone.utc)
            nxt = now.replace(hour=REVIEW_HOUR_UTC, minute=0, second=0, microsecond=0)
            if nxt <= now:
                nxt += timedelta(days=1)
            await asyncio.sleep(max(1.0, (nxt - now).total_seconds()))
            db = SessionLocal()
            try:
                run_review(db)
            finally:
                db.close()
        except asyncio.CancelledError:  # pragma: no cover
            logger.info("posrev: review loop cancelled")
            raise
        except Exception as e:  # pragma: no cover - keep the loop alive
            logger.error("posrev: review loop iteration failed: %s", e, exc_info=True)
            await asyncio.sleep(3600)
