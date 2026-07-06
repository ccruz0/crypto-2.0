"""Daily Position Review — prompt the operator to close each open position, with snooze.

Once a day a Telegram message is sent for every open position (long or short) with two
buttons: **Close** (executes a market close after a confirm tap) and **Keep 30 days**
(snoozes prompts for that position for 30 days). A position that is closed and later
re-opened is treated as a NEW case and prompted again even if the old one was snoozed.

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
FIAT_CURRENCIES = {"USD", "USDT", "USDC", "EUR", "DAI", "TUSD"}
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
def _alert_keyboard(position_key: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "🔴 Cerrar", "callback_data": f"{PREFIX_CLOSE}{position_key}"},
                {"text": "😴 Mantener 30 días", "callback_data": f"{PREFIX_SNOOZE}{position_key}"},
            ]
        ]
    }


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
    return (
        "📋 <b>REVISIÓN DE POSICIÓN</b>\n\n"
        f"📈 Símbolo: <b>{p['symbol']}</b>\n"
        f"🔄 Lado: <b>{p['side']}</b>\n"
        f"📦 Cantidad: {p['qty']}\n"
        f"💵 Valor: ${p['market_value']:.2f}\n\n"
        "¿Quieres cerrarla?"
    )


def send_review_alerts(positions: List[Dict[str, Any]]) -> int:
    """Send one Telegram prompt per position. Returns how many were sent."""
    from app.services.telegram_notifier import telegram_notifier

    sent = 0
    for p in positions:
        try:
            ok = telegram_notifier.send_message(_format_alert(p), reply_markup=_alert_keyboard(p["key"]))
            if ok:
                sent += 1
        except Exception as e:
            logger.error("posrev: failed to send alert for %s: %s", p.get("key"), e, exc_info=True)
    return sent


def run_review(db: Session, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Enumerate positions, update state, and send prompts for the non-snoozed ones."""
    positions = enumerate_open_positions(db)
    to_alert = evaluate_positions(db, positions, now=now)
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

        if qty < 0:  # SHORT -> cover with margin BUY (notional = quote value)
            notional = market_value if market_value > 0 else None
            if not notional:
                return {"error": "NO_PRICE", "message": f"Cannot size close for {symbol}"}
            # A short only exists on margin (is_margin=True); leverage is REQUIRED by the
            # broker for any margin order — omitting it raises "Margin trade requires leverage".
            result = trade_client.place_market_order(
                symbol=symbol, side="BUY", notional=notional,
                is_margin=True, leverage=DEFAULT_CONFIGURED_LEVERAGE,
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
                leverage=DEFAULT_CONFIGURED_LEVERAGE if is_margin else None,
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
    telegram_notifier.send_message(
        f"⚠️ ¿Confirmas <b>CERRAR</b> la posición <b>{key}</b>? Esto coloca una orden de mercado real.",
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
