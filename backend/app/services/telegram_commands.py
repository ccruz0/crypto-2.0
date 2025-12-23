"""

Telegram Command Handler
Handles incoming Telegram commands and responds with formatted messages
"""
import os
import logging
import math
import requests
import time
import tempfile
import sys
import json
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime, timedelta
from copy import deepcopy
import pytz
from app.services.telegram_notifier import telegram_notifier
from app.core.runtime import is_aws_runtime
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.watchlist import WatchlistItem
from app.models.telegram_state import TelegramState
from app.database import SessionLocal, engine

logger = logging.getLogger(__name__)

# File locking for preventing multiple processes from polling Telegram
try:
    import fcntl
    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
    logger.warning("[TG] fcntl not available - file locking disabled (may cause 409 conflicts)")

# Constants
# Use environment variables only (no repo defaults)
_env_chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
_env_bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
AUTH_CHAT_ID = _env_chat_id or None
BOT_TOKEN = _env_bot_token or None
TELEGRAM_ENABLED = bool(BOT_TOKEN and AUTH_CHAT_ID)
if not TELEGRAM_ENABLED:
    logger.warning("Telegram disabled: missing env vars - Telegram commands inactive")

API_BASE_URL = (
    os.getenv("API_BASE_URL")
    or os.getenv("AWS_BACKEND_URL")
    or "http://localhost:8000"
)
SERVICE_ENDPOINT = f"{API_BASE_URL.rstrip('/')}/api/services"
SERVICE_NAMES = ["exchange_sync", "signal_monitor", "trading_scheduler"]
LAST_UPDATE_ID = 0  # Global variable to track last processed update (loaded from DB on startup)
PROCESSED_CALLBACK_IDS = set()  # Track processed callback query IDs to prevent duplicate processing
_POLLER_LOCK_ACQUIRED = False  # Track if this process has the poller lock
_NO_UPDATE_COUNT = 0  # Track consecutive cycles with no updates
# CRITICAL: Track processed callbacks by data+timestamp to prevent duplicates across multiple chats
PROCESSED_CALLBACK_DATA: Dict[str, float] = {}  # {callback_data: timestamp}
CALLBACK_DATA_TTL = 5.0  # 5 seconds - ignore duplicate callback data within this window
# CRITICAL: Track processed text commands to prevent duplicates when multiple instances (local/AWS) process same command
PROCESSED_TEXT_COMMANDS: Dict[str, float] = {}  # {chat_id:command: timestamp}
TEXT_COMMAND_TTL = 3.0  # 3 seconds - ignore duplicate text commands within this window
WATCHLIST_PAGE_SIZE = 9
MAX_SYMBOLS_PER_ROW = 3
PENDING_VALUE_INPUTS: Dict[str, Dict[str, Any]] = {}


# PostgreSQL advisory lock ID for Telegram poller (arbitrary but consistent)
TELEGRAM_POLLER_LOCK_ID = 1234567890


def _acquire_poller_lock(db: Session) -> bool:
    """Acquire PostgreSQL advisory lock for single poller enforcement.
    Returns True if lock acquired, False if another poller is active.
    """
    global _POLLER_LOCK_ACQUIRED
    if not db or not engine:
        logger.warning("[TG] Database not available for poller lock")
        return False
    
    try:
        # Try to acquire advisory lock (non-blocking)
        result = db.execute(text("SELECT pg_try_advisory_lock(:lock_id)"), {"lock_id": TELEGRAM_POLLER_LOCK_ID})
        acquired = result.scalar()
        if acquired:
            _POLLER_LOCK_ACQUIRED = True
            logger.info("[TG] Poller lock acquired")
            return True
        else:
            logger.warning("[TG] Another poller is active, cannot acquire lock")
            return False
    except Exception as e:
        logger.error(f"[TG] Error acquiring poller lock: {e}")
        return False


def _release_poller_lock(db: Session) -> None:
    """Release PostgreSQL advisory lock."""
    global _POLLER_LOCK_ACQUIRED
    if not db or not engine or not _POLLER_LOCK_ACQUIRED:
        return
    
    try:
        db.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": TELEGRAM_POLLER_LOCK_ID})
        _POLLER_LOCK_ACQUIRED = False
        logger.debug("[TG] Poller lock released")
    except Exception as e:
        logger.error(f"[TG] Error releasing poller lock: {e}")


def _load_last_update_id(db: Session) -> int:
    """Load LAST_UPDATE_ID from database."""
    global LAST_UPDATE_ID
    if not db:
        return 0
    
    try:
        state = db.query(TelegramState).filter(TelegramState.id == 1).first()
        if state:
            LAST_UPDATE_ID = state.last_update_id
            logger.info(f"[TG] Loaded LAST_UPDATE_ID from DB: {LAST_UPDATE_ID}")
            return LAST_UPDATE_ID
        else:
            # Create initial state
            state = TelegramState(id=1, last_update_id=0)
            db.add(state)
            db.commit()
            LAST_UPDATE_ID = 0
            logger.info("[TG] Created initial TelegramState with LAST_UPDATE_ID=0")
            return 0
    except Exception as e:
        logger.error(f"[TG] Error loading LAST_UPDATE_ID from DB: {e}")
        return 0


def _save_last_update_id(db: Session, update_id: int) -> None:
    """Save LAST_UPDATE_ID to database."""
    global LAST_UPDATE_ID
    if not db:
        return
    
    try:
        state = db.query(TelegramState).filter(TelegramState.id == 1).first()
        if state:
            state.last_update_id = update_id
            state.updated_at = datetime.now(pytz.UTC)
        else:
            state = TelegramState(id=1, last_update_id=update_id)
            db.add(state)
        db.commit()
        LAST_UPDATE_ID = update_id
        logger.debug(f"[TG] Saved LAST_UPDATE_ID to DB: {update_id}")
    except Exception as e:
        logger.error(f"[TG] Error saving LAST_UPDATE_ID to DB: {e}")
        db.rollback()


def _run_startup_diagnostics() -> None:
    """Run startup diagnostics: getMe, getWebhookInfo, delete webhook if present, and getUpdates probe.
    
    Can be enabled with TELEGRAM_DIAGNOSTICS=1 environment variable.
    When enabled, also performs a no-offset getUpdates probe to check for pending updates.
    """
    # Check if diagnostics mode is enabled
    diagnostics_enabled = os.getenv("TELEGRAM_DIAGNOSTICS", "0").strip() == "1"
    
    if not TELEGRAM_ENABLED or not BOT_TOKEN:
        logger.warning("[TG] Startup diagnostics skipped: Telegram not enabled")
        return
    
    try:
        # 1. Call getMe
        log_prefix = "[TG_DIAG]" if diagnostics_enabled else "[TG]"
        if diagnostics_enabled:
            logger.info(f"{log_prefix} Running startup diagnostics (TELEGRAM_DIAGNOSTICS=1)...")
        else:
            logger.info(f"{log_prefix} Running startup diagnostics...")
        response = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
        response.raise_for_status()
        bot_info = response.json()
        if bot_info.get("ok"):
            bot_data = bot_info.get("result", {})
            bot_username = bot_data.get("username", "N/A")
            bot_id = bot_data.get("id", "N/A")
            logger.info(f"{log_prefix} Bot identity: username={bot_username}, id={bot_id}")
        else:
            logger.error(f"{log_prefix} getMe failed: {bot_info}")
        
        # 2. Call getWebhookInfo
        response = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo", timeout=5)
        response.raise_for_status()
        webhook_info = response.json()
        if webhook_info.get("ok"):
            webhook_data = webhook_info.get("result", {})
            webhook_url = webhook_data.get("url", "")
            pending_count = webhook_data.get("pending_update_count", 0)
            last_error = webhook_data.get("last_error_message", "")
            last_error_date = webhook_data.get("last_error_date", 0)
            logger.info(f"{log_prefix} Webhook info: url={webhook_url or 'None'}, pending_updates={pending_count}, last_error={last_error or 'None'}")
            
            # 3. Delete webhook if present (always delete on startup to ensure polling works)
            if webhook_url:
                logger.warning(f"{log_prefix} Webhook detected at {webhook_url}, deleting it...")
                response = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
                    json={"drop_pending_updates": True},
                    timeout=5
                )
                response.raise_for_status()
                delete_result = response.json()
                if delete_result.get("ok"):
                    logger.info(f"{log_prefix} Webhook deleted successfully")
                else:
                    logger.error(f"{log_prefix} Failed to delete webhook: {delete_result}")
            else:
                logger.info(f"{log_prefix} No webhook configured (polling mode)")
        else:
            logger.error(f"{log_prefix} getWebhookInfo failed: {webhook_info}")
        
        # 4. Diagnostics mode: Probe getUpdates without offset
        if diagnostics_enabled:
            logger.info(f"{log_prefix} Probing getUpdates (no offset, limit=10, timeout=0)...")
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
                params = {"limit": 10, "timeout": 0}
                response = requests.get(url, params=params, timeout=5)
                response.raise_for_status()
                data = response.json()
                if data.get("ok"):
                    updates = data.get("result", [])
                    update_count = len(updates)
                    if update_count > 0:
                        update_ids = [u.get("update_id", 0) for u in updates]
                        max_id = max(update_ids) if update_ids else 0
                        logger.info(f"{log_prefix} getUpdates probe: found {update_count} pending updates, max update_id={max_id}, ids={update_ids[:5]}")
                    else:
                        logger.info(f"{log_prefix} getUpdates probe: no pending updates")
                else:
                    logger.warning(f"{log_prefix} getUpdates probe failed: {data}")
            except Exception as probe_err:
                logger.error(f"{log_prefix} getUpdates probe error: {probe_err}")
            
    except Exception as e:
        logger.error(f"{log_prefix} Startup diagnostics failed: {e}", exc_info=True)


def _probe_updates_without_offset() -> List[Dict]:
    """Probe Telegram for updates without offset to detect missed updates."""
    if not TELEGRAM_ENABLED or not BOT_TOKEN:
        return []
    
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {"limit": 50}  # Get up to 50 updates
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data.get("ok"):
            return data.get("result", [])
        return []
    except Exception as e:
        logger.error(f"[TG] Probe updates failed: {e}")
        return []


def _build_keyboard(rows: List[List[Dict[str, str]]]) -> Dict[str, List[List[Dict[str, str]]]]:
    """Create inline keyboard payload."""
    return {"inline_keyboard": rows}


def _send_or_edit_menu(chat_id: str, text: str, keyboard: Dict, message_id: Optional[int] = None) -> bool:
    """
    Try to edit the existing message; fall back to sending a new one if edit fails.
    This keeps chats tidy while still guaranteeing the user sees the latest menu.
    
    CRITICAL: Always try to edit first if message_id is provided to prevent duplicate messages.
    """
    if message_id:
        # Try to edit the existing message first
        if _edit_menu_message(chat_id, message_id, text, keyboard):
            return True
        # If edit fails (e.g., message was deleted or content is identical), 
        # log it but don't send a new message to avoid duplicates
        logger.debug(f"[TG] Failed to edit message {message_id} for chat {chat_id}, not sending duplicate")
        return False
    # Only send new message if no message_id provided (first time showing menu)
    return _send_menu_message(chat_id, text, keyboard)


def _format_coin_status_icons(item: WatchlistItem) -> str:
    """Compact status badges for watchlist buttons (tested separately)."""
    alert_icon = "🔔" if getattr(item, "alert_enabled", False) else "🔕"
    trade_icon = "🤖" if getattr(item, "trade_enabled", False) else "⛔"
    margin_icon = "⚡" if getattr(item, "trade_on_margin", False) else "💤"
    return f"{alert_icon}{trade_icon}{margin_icon}"


def _format_coin_summary(item: WatchlistItem) -> str:
    """Detailed summary block for a single coin."""
    amount = getattr(item, "trade_amount_usd", None)
    amount_text = f"${amount:,.2f}" if (isinstance(amount, (int, float)) and amount > 0) else "N/A"
    min_pct = getattr(item, "min_price_change_pct", None)
    min_pct_text = f"{min_pct:.2f}%" if isinstance(min_pct, (int, float)) else "Strategy default"
    cooldown = getattr(item, "alert_cooldown_minutes", None)
    cooldown_text = f"{cooldown:.1f} min" if isinstance(cooldown, (int, float)) else "Strategy default"
    sl_mode = getattr(item, "sl_tp_mode", None) or "conservative"
    sl_pct = getattr(item, "sl_percentage", None)
    tp_pct = getattr(item, "tp_percentage", None)
    sl_text = f"{sl_pct:.2f}%" if isinstance(sl_pct, (int, float)) else "Auto"
    tp_text = f"{tp_pct:.2f}%" if isinstance(tp_pct, (int, float)) else "Auto"
    buy_alert = "ENABLED" if getattr(item, "buy_alert_enabled", False) else "DISABLED"
    sell_alert = "ENABLED" if getattr(item, "sell_alert_enabled", False) else "DISABLED"
    return (
        f"🔔 Alert: <b>{'ENABLED' if item.alert_enabled else 'DISABLED'}</b>\n"
        f"🟢 Buy Alert: <b>{buy_alert}</b> | 🔻 Sell Alert: <b>{sell_alert}</b>\n"
        f"🤖 Trade: <b>{'ENABLED' if item.trade_enabled else 'DISABLED'}</b>\n"
        f"⚡ Margin: <b>{'ON' if item.trade_on_margin else 'OFF'}</b>\n"
        f"💵 Amount USD: <b>{amount_text}</b>\n"
        f"🎯 Risk Mode: <b>{sl_mode.title()}</b>\n"
        f"📉 SL%: <b>{sl_text}</b> | 📈 TP%: <b>{tp_text}</b>\n"
        f"📊 Min Price Change: <b>{min_pct_text}</b>\n"
        f"⏱ Cooldown: <b>{cooldown_text}</b>"
    )


def _load_watchlist_items(db: Session) -> List[WatchlistItem]:
    """Fetch non-deleted watchlist items ordered by symbol."""
    return db.query(WatchlistItem).filter(
        WatchlistItem.symbol.isnot(None),
        WatchlistItem.symbol != "",
        WatchlistItem.is_deleted == False  # noqa
    ).order_by(WatchlistItem.symbol.asc()).all()


def _get_watchlist_item(db: Session, symbol: str) -> Optional[WatchlistItem]:
    """Return latest watchlist item for symbol."""
    return (
        db.query(WatchlistItem)
        .filter(WatchlistItem.symbol == symbol, WatchlistItem.is_deleted == False)  # noqa
        .order_by(WatchlistItem.created_at.desc())
        .first()
    )


def _update_watchlist_fields(db: Session, symbol: str, updates: Dict[str, Any]) -> WatchlistItem:
    """
    Apply partial updates to a watchlist item and persist them.
    
    CRITICAL: Use the same API endpoint as the frontend to ensure consistent behavior
    and prevent issues like trade_enabled being immediately deactivated.
    """
    item = _get_watchlist_item(db, symbol)
    if not item:
        raise ValueError(f"Symbol {symbol} not found")
    
    # CRITICAL: Normalize boolean fields to prevent NULL values
    # This matches the logic in routes_dashboard.py
    boolean_fields = {
        "alert_enabled", "buy_alert_enabled", "sell_alert_enabled",
        "trade_enabled", "trade_on_margin", "sold", "skip_sl_tp_reminder"
    }
    
    for field, value in updates.items():
        if not hasattr(item, field):
            logger.warning(f"[TG] Field {field} missing on WatchlistItem, skipping update for {symbol}")
            continue
        
        # CRITICAL: Normalize boolean fields - convert None to False
        if field in boolean_fields and value is None:
            value = False
        
        setattr(item, field, value)
    
    db.commit()
    db.refresh(item)
    
    # CRITICAL: Verify that boolean fields were actually saved correctly
    # This prevents the issue where trade_enabled gets deactivated immediately
    for field in boolean_fields:
        if field in updates:
            expected_value = updates[field]
            if expected_value is None:
                expected_value = False
            actual_value = getattr(item, field)
            if actual_value != expected_value:
                logger.error(f"❌ [TG] SYNC ERROR: {field} mismatch for {symbol}: "
                           f"Expected {expected_value}, but DB has {actual_value}. "
                           f"Attempting to fix...")
                setattr(item, field, expected_value)
                db.commit()
                db.refresh(item)
                logger.info(f"✅ [TG] Fixed {field} sync issue for {symbol}")
    
    return item


def _create_watchlist_symbol(db: Session, symbol: str) -> WatchlistItem:
    """Create a new watchlist entry with safe defaults."""
    normalized = symbol.upper()
    existing = _get_watchlist_item(db, normalized)
    if existing:
        raise ValueError(f"{normalized} ya existe en la watchlist")
    item = WatchlistItem(
        symbol=normalized,
        exchange="CRYPTO_COM",
        alert_enabled=False,
        trade_enabled=False,
        trade_amount_usd=None,
        trade_on_margin=False,
        sl_tp_mode="conservative",
        is_deleted=False,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _delete_watchlist_symbol(db: Session, symbol: str) -> None:
    """Soft delete symbol if column exists, fallback to hard delete."""
    item = _get_watchlist_item(db, symbol)
    if not item:
        raise ValueError(f"{symbol} no existe")
    if hasattr(item, "is_deleted"):
        item.is_deleted = True
        item.alert_enabled = False
        item.trade_enabled = False
        item.trade_on_margin = False
    else:
        db.delete(item)
    db.commit()


def _prompt_value_input(
    chat_id: str,
    prompt: str,
    *,
    symbol: Optional[str],
    field: Optional[str],
    action: str,
    value_type: str = "float",
    allow_clear: bool = True,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Store pending input metadata and prompt the user."""
    pending_state: Dict[str, Any] = {
        "symbol": symbol,
        "field": field,
        "action": action,
        "value_type": value_type,
        "allow_clear": allow_clear,
        "min_value": min_value,
        "max_value": max_value,
    }
    if extra:
        pending_state.update(extra)
    PENDING_VALUE_INPUTS[chat_id] = pending_state
    footer = "\n\nEnvía el valor por chat. Escribe 'cancel' para salir."
    keyboard = _build_keyboard([[{"text": "❌ Cancelar", "callback_data": "input:cancel"}]])
    _send_menu_message(chat_id, prompt + footer, keyboard)


def _parse_pending_value(state: Dict[str, Any], raw_value: str) -> Tuple[Optional[Any], str]:
    """Validate and convert user text based on pending state. Returns (value, error)."""
    value_type = state.get("value_type", "float")
    allow_clear = state.get("allow_clear", True)
    min_value = state.get("min_value")
    max_value = state.get("max_value")
    normalized = raw_value.strip()
    if allow_clear and normalized.lower() in {"clear", "none", "null", "0"}:
        return None, ""
    try:
        if value_type == "float":
            val = float(normalized)
        elif value_type == "int":
            val = int(normalized)
        elif value_type == "symbol":
            val = normalized.upper()
            if "_" not in val:
                val = f"{val}_USDT"
        else:  # string
            val = normalized
    except ValueError:
        return None, "Valor inválido. Usa números (ej: 100.5)."
    if isinstance(val, (int, float)):
        if min_value is not None and val < min_value:
            return None, f"El valor debe ser ≥ {min_value}"
        if max_value is not None and val > max_value:
            return None, f"El valor debe ser ≤ {max_value}"
    return val, ""


def _handle_pending_value_message(chat_id: str, text: str, db: Session) -> bool:
    """If chat has a pending input request, process it and return True."""
    state = PENDING_VALUE_INPUTS.get(chat_id)
    if not state:
        return False
    if text.strip().lower() in {"cancel", "/cancel"}:
        PENDING_VALUE_INPUTS.pop(chat_id, None)
        send_command_response(chat_id, "❌ Entrada cancelada.")
        symbol = state.get("symbol")
        if symbol and db:
            show_coin_menu(chat_id, symbol, db)
        return True
    value, error = _parse_pending_value(state, text)
    if error:
        send_command_response(chat_id, f"⚠️ {error}")
        return True
    try:
        action = state.get("action")
        symbol = state.get("symbol")
        if action == "update_field" and symbol and state.get("field"):
            updates = {state["field"]: value}
            _update_watchlist_fields(db, symbol, updates)
            send_command_response(chat_id, f"✅ Guardado para {symbol}")
            show_coin_menu(chat_id, symbol, db)
        elif action == "add_symbol" and isinstance(value, str):
            new_item = _create_watchlist_symbol(db, value)
            send_command_response(chat_id, f"✅ {new_item.symbol} agregado con Alert=NO / Trade=NO.")
            show_coin_menu(chat_id, new_item.symbol, db)
        elif action == "set_notes" and symbol:
            _update_watchlist_fields(db, symbol, {"notes": value})
            send_command_response(chat_id, f"📝 Notas actualizadas para {symbol}")
            show_coin_menu(chat_id, symbol, db)
        elif action == "update_rule":
            preset = state.get("preset")
            risk_mode = state.get("risk")
            rule_path = state.get("rule_path")
            label = state.get("label") or rule_path
            if not preset or not risk_mode or not rule_path:
                send_command_response(chat_id, "❌ No se pudo determinar la regla a actualizar.")
            else:
                try:
                    _update_signal_rule_value(preset, risk_mode, rule_path, value)
                    send_command_response(chat_id, f"✅ {label} actualizado para {preset.title()} · {risk_mode}")
                    show_signal_config_detail(chat_id, preset, risk_mode)
                except Exception as update_err:
                    logger.error(f"[TG][ERROR] Failed to update rule {rule_path}: {update_err}", exc_info=True)
                    send_command_response(chat_id, f"❌ Error guardando regla: {update_err}")
        else:
            send_command_response(chat_id, "⚠️ Acción no soportada.")
        PENDING_VALUE_INPUTS.pop(chat_id, None)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to handle pending value: {e}", exc_info=True)
        send_command_response(chat_id, f"❌ Error guardando valor: {e}")
    return True
def _send_menu_message(chat_id: str, text: str, keyboard: Dict) -> bool:
    """Send a message with inline keyboard."""
    if not TELEGRAM_ENABLED:
        logger.debug("Telegram disabled: skipping menu message")
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        }
        logger.info(f"[TG] Sending menu message to chat_id={chat_id}, text_preview={text[:50]}..., keyboard_type={list(keyboard.keys())}")
        logger.debug(f"[TG] Full keyboard structure: {json.dumps(keyboard, indent=2)}")
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        result = response.json()
        if result.get("ok"):
            message_id = result.get('result', {}).get('message_id')
            logger.info(f"[TG] Menu message sent successfully to chat_id={chat_id}, message_id={message_id}")
            return True
        else:
            error_desc = result.get('description', 'Unknown error')
            logger.error(f"[TG] Menu message API returned not OK: {error_desc}, full response: {result}")
            return False
    except requests.exceptions.HTTPError as e:
        error_body = e.response.text if hasattr(e, 'response') and e.response else str(e)
        logger.error(f"[TG][ERROR] HTTP error sending menu message to chat_id={chat_id}: {e}, response: {error_body}")
        return False
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to send menu message to chat_id={chat_id}: {e}", exc_info=True)
        return False


def _edit_menu_message(chat_id: str, message_id: int, text: str, keyboard: Dict) -> bool:
    """Edit an existing message to display another menu."""
    if not TELEGRAM_ENABLED:
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 400:
            # Check if it's because message is unchanged (this is OK)
            error_data = response.json() if response.content else {}
            error_description = error_data.get("description", "").lower()
            if "message is not modified" in error_description:
                # Message content is identical - this is OK, consider it success
                logger.debug(f"[TG] Message {message_id} unchanged (content identical)")
                return True
            # Other 400 errors (e.g., message not found) - log but don't send duplicate
            logger.debug(f"[TG] editMessageText 400 error: {response.text}")
            return False
        response.raise_for_status()
        return True
    except Exception as e:
        # Don't log as error if it's just that the message was deleted or not found
        # This prevents spam in logs when messages are legitimately missing
        error_msg = str(e).lower()
        if "message not found" in error_msg or "message to edit not found" in error_msg:
            logger.debug(f"[TG] Message {message_id} not found (may have been deleted)")
        else:
            logger.error(f"[TG][ERROR] Failed to edit menu message: {e}", exc_info=True)
        return False


def setup_bot_commands():
    """Setup Telegram bot commands menu"""
    if not TELEGRAM_ENABLED:
        logger.debug("Telegram disabled: skipping setup_bot_commands")
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands"
        
        commands = [
            {"command": "start", "description": "Mostrar mensaje de bienvenida"},
            {"command": "help", "description": "Mostrar ayuda con todos los comandos"},
            {"command": "status", "description": "Estado del bot y trading"},
            {"command": "portfolio", "description": "Órdenes abiertas y posiciones activas"},
            {"command": "signals", "description": "Últimas 5 señales BUY/SELL"},
            {"command": "balance", "description": "Balance de la cuenta"},
            {"command": "watchlist", "description": "Monedas con Trade=YES"},
            {"command": "alerts", "description": "Monedas con Alert=YES"},
            {"command": "analyze", "description": "Analizar una moneda (ej: /analyze BTC_USDT)"},
            {"command": "add", "description": "Agregar una moneda al watchlist (ej: /add BTC_USDT)"},
            {"command": "create_sl_tp", "description": "Crear SL/TP para posiciones sin protección"},
            {"command": "create_sl", "description": "Crear solo SL para una posición"},
            {"command": "create_tp", "description": "Crear solo TP para una posición"},
            {"command": "skip_sl_tp_reminder", "description": "No preguntar más sobre SL/TP"}
        ]
        
        payload = {
            "commands": commands
        }
        
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        if result.get("ok"):
            logger.info("[TG] Bot commands menu configured successfully")
            return True
        else:
            logger.warning(f"[TG] Failed to set commands: {result.get('description', 'Unknown error')}")
            return False
            
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to setup bot commands: {e}")
        return False


def get_telegram_updates(offset: Optional[int] = None, timeout_override: Optional[int] = None, db: Optional[Session] = None) -> List[Dict]:
    """Get updates from Telegram API using long polling.
    
    RUNTIME GUARD: Only AWS should poll Telegram to avoid 409 conflicts.
    LOCAL runtime should not poll, as AWS is already polling.
    
    NOTE: Lock acquisition is handled by the caller (process_telegram_commands).
    This function assumes the lock is already held.
    """
    # RUNTIME GUARD: Only AWS should poll Telegram
    if not is_aws_runtime():
        logger.debug("[TG_LOCAL_DEBUG] Skipping getUpdates in LOCAL runtime to avoid 409 conflicts")
        return []
    
    if not TELEGRAM_ENABLED:
        return []
    
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {}
        if offset is not None:
            params["offset"] = offset
        # Include message and my_chat_member updates to ensure /start works in both private and group chats
        # my_chat_member is needed for bot being added to groups
        params["allowed_updates"] = ["message", "my_chat_member", "edited_message", "callback_query"]
        
        # Use long polling: Telegram will wait up to 30 seconds for new messages
        # This allows real-time command processing
        # Allow timeout override for quick checks
        # NOTE: Using shorter timeout (10s) to release lock more frequently and allow other pollers
        params["timeout"] = timeout_override if timeout_override is not None else 10
        
        # Increase timeout to account for network delay
        request_timeout = (timeout_override + 5) if timeout_override else 35
        response = requests.get(url, params=params, timeout=request_timeout)
        response.raise_for_status()
        
        data = response.json()
        if data.get("ok"):
            return data.get("result", [])
        return []
    except requests.exceptions.Timeout:
        # Timeout is expected when no new messages - return empty list
        return []
    except requests.exceptions.HTTPError as http_err:
        status = getattr(http_err.response, 'status_code', None)
        if status == 409:
            # 409 conflict - another client is polling or webhook is active
            # This is expected when multiple pollers try to poll simultaneously
            # The lock should prevent this, but if it happens, just skip this cycle
            logger.debug(
                "[TG] getUpdates conflict (409) - Another webhook or polling client is active. "
                "This may be due to race condition between pollers. Skipping this cycle."
            )
            return []
        logger.error(f"[TG] getUpdates HTTP error: {http_err}")
        return []
    except Exception as e:
        logger.error(f"[TG] getUpdates failed: {e}")
        return []


def send_command_response(chat_id: str, message: str) -> bool:
    """Send response message to Telegram"""
    if not TELEGRAM_ENABLED:
        logger.debug("Telegram disabled: skipping command response")
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"  # Use HTML instead of Markdown (more reliable)
        }
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            logger.error(f"[TG][ERROR] Failed to send message: {response.status_code} - {error_data}")
            # Try without parse_mode as fallback
            try:
                payload_no_parse = {
                    "chat_id": chat_id,
                    "text": message
                }
                response2 = requests.post(url, json=payload_no_parse, timeout=10)
                response2.raise_for_status()
                logger.info(f"[TG] Sent message without parse_mode")
                return True
            except Exception as e2:
                logger.error(f"[TG][ERROR] Failed to send message without parse_mode: {e2}")
                return False
        
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to send command response: {e}")
        # Try to get more details about the error
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_data = e.response.json()
                logger.error(f"[TG][ERROR] Error details: {error_data}")
            except:
                logger.error(f"[TG][ERROR] Error response: {e.response.text[:200]}")
        return False


def _setup_custom_keyboard(chat_id: str) -> bool:
    """Set up custom keyboard with persistent buttons at the bottom of the chat"""
    if not TELEGRAM_ENABLED:
        return False
    try:
        # Create custom keyboard with buttons
        keyboard = {
            "keyboard": [
                [{"text": "🚀 Start"}],
                [{"text": "📊 Status"}, {"text": "💰 Portfolio"}],
                [{"text": "📈 Signals"}, {"text": "📋 Watchlist"}],
                [{"text": "⚙️ Menu"}, {"text": "❓ Help"}]
            ],
            "resize_keyboard": True,
            "one_time_keyboard": False  # Keep keyboard persistent
        }
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": "🎉 <b>Welcome! Use the buttons below to interact with the bot.</b>",
            "parse_mode": "HTML",
            "reply_markup": keyboard
        }
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"[TG] Custom keyboard set up for chat_id={chat_id}")
        return True
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to setup custom keyboard: {e}", exc_info=True)
        return False


def send_welcome_message(chat_id: str) -> bool:
    """Send welcome message with inline keyboard buttons"""
    if not TELEGRAM_ENABLED:
        return False
    try:
        message = """🎉 <b>Welcome to Trading Bot</b>

Use the buttons below to interact with the bot.

<b>Available Commands:</b>
/start - Show this welcome message
/status - Get bot status
/portfolio - View portfolio
/signals - View recent signals
/watchlist - View watchlist
/alerts - View alerts
/menu - Show main menu
/help - Show help

<b>Note:</b> Only authorized users can use these commands."""
        
        # Create inline keyboard (buttons in the message)
        keyboard = _build_keyboard([
            [{"text": "📊 Status", "callback_data": "cmd:status"}],
            [{"text": "💼 Portfolio", "callback_data": "cmd:portfolio"}],
            [{"text": "📈 Signals", "callback_data": "cmd:signals"}],
            [{"text": "📋 Watchlist", "callback_data": "cmd:watchlist"}],
            [{"text": "⚙️ Main Menu", "callback_data": "menu:main"}],
            [{"text": "❓ Help", "callback_data": "cmd:help"}],
        ])
        
        logger.info(f"[TG] Sending welcome message with inline keyboard to chat_id={chat_id}")
        return _send_menu_message(chat_id, message, keyboard)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to send welcome message: {e}", exc_info=True)
        return False


def send_help_message(chat_id: str) -> bool:
    """Send help message with command descriptions"""
    message = """📚 <b>Command Help</b>

/start - Show welcome message and command list
/help - Show this help message
/status - Get bot status report (system, trading status, settings)
/portfolio - List all open orders and active positions
/signals - Display last 5 trading signals (BUY/SELL)
/balance - Show exchange account balance
/watchlist - Show all coins currently tracked with Trade=YES
/alerts - Show all coins with Alert=YES (automatic alerts enabled)
/analyze &lt;symbol&gt; - Get detailed analysis for a coin (e.g., /analyze BTC_USDT) or show menu if no symbol
/add &lt;symbol&gt; - Add a coin to the watchlist (e.g., /add BTC_USDT)
/create_sl_tp [symbol] - Create SL/TP orders for positions missing protection
/create_sl [symbol] - Create only SL order for a position
/create_tp [symbol] - Create only TP order for a position
/skip_sl_tp_reminder [symbol] - Don't ask about SL/TP for these positions anymore

<b>Note:</b> Only authorized users can use these commands."""
    return send_command_response(chat_id, message)


def show_main_menu(chat_id: str, db: Session = None) -> bool:
    """Show main menu with buttons matching dashboard layout - Reference Specification v1.0
    
    Menu structure (exact order per specification):
    1. Portfolio
    2. Watchlist
    3. Open Orders
    4. Expected Take Profit
    5. Executed Orders
    6. Monitoring
    7. Version History
    """
    try:
        text = "📋 <b>Main Menu</b>\n\nSelect a section:"
        keyboard = _build_keyboard([
            [{"text": "💼 Portfolio", "callback_data": "menu:portfolio"}],
            [{"text": "📊 Watchlist", "callback_data": "menu:watchlist"}],
            [{"text": "📋 Open Orders", "callback_data": "menu:open_orders"}],
            [{"text": "🎯 Expected Take Profit", "callback_data": "menu:expected_tp"}],
            [{"text": "✅ Executed Orders", "callback_data": "menu:executed_orders"}],
            [{"text": "🔍 Monitoring", "callback_data": "menu:monitoring"}],
            [{"text": "📝 Version History", "callback_data": "cmd:version"}],
        ])
        logger.info(f"[TG][MENU] Building main menu for chat_id={chat_id}, keyboard structure: {keyboard}")
        logger.info(f"[TG][MENU] Keyboard JSON: {json.dumps(keyboard, indent=2)}")
        result = _send_menu_message(chat_id, text, keyboard)
        logger.info(f"[TG][MENU] Main menu send result: {result}")
        if not result:
            logger.error(f"[TG][MENU] Failed to send main menu! chat_id={chat_id}")
        return result
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing main menu: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error showing menu: {str(e)}")


def show_watchlist_menu(chat_id: str, db: Session, page: int = 1, message_id: Optional[int] = None) -> bool:
    """Show paginated watchlist with per-symbol buttons."""
    if not db:
        return send_command_response(chat_id, "❌ Database not available")
    try:
        items = _load_watchlist_items(db)
        if not items:
            text = "👀 <b>Watchlist</b>\n\nNo hay monedas configuradas. Agrega una con el botón de abajo."
            keyboard = _build_keyboard([
                [{"text": "➕ Add Symbol", "callback_data": "watchlist:add"}],
                [{"text": "🏠 Main", "callback_data": "menu:main"}],
            ])
            return _send_or_edit_menu(chat_id, text, keyboard, message_id)
        total_pages = max(1, math.ceil(len(items) / WATCHLIST_PAGE_SIZE))
        page = max(1, min(page, total_pages))
        start = (page - 1) * WATCHLIST_PAGE_SIZE
        subset = items[start:start + WATCHLIST_PAGE_SIZE]
        rows: List[List[Dict[str, str]]] = []
        for i in range(0, len(subset), MAX_SYMBOLS_PER_ROW):
            chunk = subset[i:i + MAX_SYMBOLS_PER_ROW]
            row = []
            for item in chunk:
                label = f"{(item.symbol or '').upper()} {_format_coin_status_icons(item)}"
                row.append({
                    "text": label[:64],
                    "callback_data": f"wl:coin:{(item.symbol or '').upper()}"
                })
            rows.append(row)
        nav_row: List[Dict[str, str]] = []
        if page > 1:
            nav_row.append({"text": "⬅️ Prev", "callback_data": f"watchlist:page:{page - 1}"})
        nav_row.append({"text": f"📄 {page}/{total_pages}", "callback_data": "noop"})
        if page < total_pages:
            nav_row.append({"text": "Next ➡️", "callback_data": f"watchlist:page:{page + 1}"})
        rows.append(nav_row)
        rows.append([
            {"text": "➕ Add Symbol", "callback_data": "watchlist:add"},
            {"text": "🔄 Refresh", "callback_data": f"watchlist:page:{page}"},
        ])
        rows.append([{"text": "🏠 Main Menu", "callback_data": "menu:main"}])
        text = "⚙️ <b>Watchlist Control</b>\n\nSelecciona un símbolo para ajustar sus parámetros."
        return _send_or_edit_menu(chat_id, text, _build_keyboard(rows), message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing watchlist menu: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error mostrando watchlist: {e}")


def show_coin_menu(chat_id: str, symbol: str, db: Session, message_id: Optional[int] = None) -> bool:
    """Show detailed controls for a specific symbol."""
    if not db:
        return send_command_response(chat_id, "❌ Database not available")
    try:
        normalized = (symbol or "").upper()
        item = _get_watchlist_item(db, normalized)
        if not item:
            return send_command_response(chat_id, f"❌ {normalized} no existe en la watchlist.")
        text = f"⚙️ <b>{normalized} Settings</b>\n\n{_format_coin_summary(item)}"
        rows = [
            [
                {"text": "🔔 Alert", "callback_data": f"wl:coin:{normalized}:toggle:alert"},
                {"text": "🟢 Buy Alert", "callback_data": f"wl:coin:{normalized}:toggle:buy_alert"},
                {"text": "🔻 Sell Alert", "callback_data": f"wl:coin:{normalized}:toggle:sell_alert"},
            ],
            [
                {"text": "🤖 Trade", "callback_data": f"wl:coin:{normalized}:toggle:trade"},
                {"text": "⚡ Margin", "callback_data": f"wl:coin:{normalized}:toggle:margin"},
                {"text": "🎯 Risk Mode", "callback_data": f"wl:coin:{normalized}:toggle:risk"},
            ],
            [
                {"text": "💵 Amount USD", "callback_data": f"wl:coin:{normalized}:set:amount"},
                {"text": "📊 Min %", "callback_data": f"wl:coin:{normalized}:set:min_pct"},
                {"text": "⏱ Cooldown", "callback_data": f"wl:coin:{normalized}:set:cooldown"},
            ],
            [
                {"text": "📉 SL%", "callback_data": f"wl:coin:{normalized}:set:sl_pct"},
                {"text": "📈 TP%", "callback_data": f"wl:coin:{normalized}:set:tp_pct"},
                {"text": "🧠 Preset", "callback_data": f"wl:coin:{normalized}:preset"},
            ],
            [
                {"text": "📝 Notas", "callback_data": f"wl:coin:{normalized}:set:notes"},
                {"text": "🧪 Test Alert", "callback_data": f"wl:coin:{normalized}:test"},
                {"text": "🗑️ Delete", "callback_data": f"wl:coin:{normalized}:delete"},
            ],
            [
                {"text": "🔙 Back", "callback_data": "menu:watchlist"},
                {"text": "🏠 Main", "callback_data": "menu:main"},
            ],
        ]
        return _send_or_edit_menu(chat_id, text, _build_keyboard(rows), message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing coin menu for {symbol}: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error mostrando {symbol}: {e}")


# Track recent toggles to prevent duplicate messages
_TOGGLE_CACHE: Dict[str, float] = {}  # {(chat_id, symbol, field): timestamp}
_TOGGLE_CACHE_TTL = 2.0  # 2 seconds - ignore duplicate toggles within this window

def _handle_watchlist_toggle(chat_id: str, symbol: str, field: str, db: Session, message_id: Optional[int]) -> None:
    """Generic toggle handler for alert/trade/margin/risk flags."""
    # DEDUPLICATION: Prevent duplicate toggles within a short time window
    cache_key = f"{chat_id}:{symbol}:{field}"
    now = time.time()
    if cache_key in _TOGGLE_CACHE:
        last_toggle_time = _TOGGLE_CACHE[cache_key]
        if now - last_toggle_time < _TOGGLE_CACHE_TTL:
            logger.debug(f"[TG] Skipping duplicate toggle {cache_key} (last toggle was {now - last_toggle_time:.2f}s ago)")
            # Still update the menu to show current state, but don't send duplicate status message
            show_coin_menu(chat_id, symbol, db, message_id=message_id)
            return
    
    try:
        item = _get_watchlist_item(db, symbol)
        if not item:
            send_command_response(chat_id, f"❌ {symbol} no existe.")
            return
        
        # Record this toggle to prevent duplicates
        _TOGGLE_CACHE[cache_key] = now
        # Clean up old cache entries (keep only last 100)
        if len(_TOGGLE_CACHE) > 100:
            # Remove entries older than TTL
            cutoff_time = now - _TOGGLE_CACHE_TTL
            _TOGGLE_CACHE = {k: v for k, v in _TOGGLE_CACHE.items() if v > cutoff_time}
        
        if field == "sl_tp_mode":
            current = (item.sl_tp_mode or "conservative").lower()
            new_value = "aggressive" if current == "conservative" else "conservative"
            updated = _update_watchlist_fields(db, symbol, {field: new_value})
            status = new_value.title()
            send_command_response(chat_id, f"🎯 Modo de riesgo para {symbol}: {status}")
        else:
            current = bool(getattr(item, field))
            new_value = not current
            logger.info(f"[TG] Toggling {field} for {symbol}: {current} -> {new_value}")
            
            # Update the field
            updated = _update_watchlist_fields(db, symbol, {field: new_value})
            
            # CRITICAL: Verify the value was actually saved correctly
            db.refresh(updated)
            actual_value = bool(getattr(updated, field))
            
            if actual_value != new_value:
                logger.error(f"❌ [TG] SYNC ERROR: {field} for {symbol} was set to {new_value} but DB has {actual_value}")
                # Try to fix it
                setattr(updated, field, new_value)
                db.commit()
                db.refresh(updated)
                actual_value = bool(getattr(updated, field))
                logger.info(f"✅ [TG] Fixed {field} for {symbol}: now {actual_value}")
            
            status = "✅ ACTIVADO" if actual_value else "❌ DESACTIVADO"
            # Format field name for display (e.g., "trade_enabled" -> "Trade Enabled")
            field_display = field.replace('_', ' ').title()
            send_command_response(chat_id, f"{field_display} {status} para {symbol}")
        show_coin_menu(chat_id, symbol, db, message_id=message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Toggle {field} for {symbol} failed: {e}", exc_info=True)
        send_command_response(chat_id, f"❌ Error cambiando {field}: {e}")


def _show_preset_selection_menu(chat_id: str, symbol: str) -> None:
    """Display available strategy presets for a symbol."""
    from app.services.config_loader import load_config

    cfg = load_config()
    presets = sorted(cfg.get("presets", {}).keys())
    if not presets:
        send_command_response(chat_id, "❌ No hay presets configurados en trading_config.")
        return
    coin_cfg = cfg.get("coins", {}).get(symbol, {})
    current = coin_cfg.get("preset") or cfg.get("defaults", {}).get("preset", "swing")
    rows: List[List[Dict[str, str]]] = []
    for i in range(0, len(presets), 2):
        chunk = presets[i:i + 2]
        row = []
        for preset in chunk:
            display = preset
            if preset == current:
                display = f"✅ {preset}"
            row.append({
                "text": display[:64],
                "callback_data": f"wl:coin:{symbol}:preset:set:{preset}"
            })
        rows.append(row)
    rows.append([{"text": "🔙 Regresar", "callback_data": f"wl:coin:{symbol}"}])
    text = f"🧠 <b>{symbol} - Presets</b>\n\nActual: <b>{current}</b>\nSelecciona un preset para actualizar trading_config."
    _send_menu_message(chat_id, text, _build_keyboard(rows))


def _apply_preset_change(chat_id: str, symbol: str, preset: str) -> None:
    """Persist preset change inside trading_config."""
    from app.services.config_loader import load_config, save_config

    cfg = load_config()
    if preset not in cfg.get("presets", {}):
        send_command_response(chat_id, f"❌ Preset desconocido: {preset}")
        return
    cfg.setdefault("coins", {}).setdefault(symbol, {})
    cfg["coins"][symbol]["preset"] = preset
    save_config(cfg)
    send_command_response(chat_id, f"🧠 {symbol} ahora usa preset <b>{preset}</b>")


def _trigger_watchlist_test(chat_id: str, symbol: str, db: Session) -> None:
    """Simulate BUY/SELL alerts for the given symbol matching dashboard test button."""
    if not db:
        send_command_response(chat_id, "❌ Database not available.")
        return
    item = _get_watchlist_item(db, symbol)
    if not item:
        send_command_response(chat_id, f"❌ {symbol} no existe en la watchlist.")
        return
    buy_enabled = bool(getattr(item, "buy_alert_enabled", False))
    sell_enabled = bool(getattr(item, "sell_alert_enabled", False))
    if not buy_enabled and not sell_enabled:
        send_command_response(
            chat_id,
            f"⚠️ No hay alerts activas para {symbol}.\nActiva BUY o SELL antes de ejecutar una prueba.",
        )
        return
    url = f"{API_BASE_URL.rstrip('/')}/api/test/simulate-alert"
    results: List[str] = []
    errors: List[str] = []
    for signal_type, enabled in (("BUY", buy_enabled), ("SELL", sell_enabled)):
        if not enabled:
            continue
        payload = {
            "symbol": symbol,
            "signal_type": signal_type,
            "force_order": False,
        }
        amount = getattr(item, "trade_amount_usd", None)
        if isinstance(amount, (int, float)) and amount > 0:
            payload["trade_amount_usd"] = amount
        try:
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code != 200:
                errors.append(f"{signal_type}: {response.text}")
                continue
            data = response.json()
            alert_sent = "✅" if data.get("alert_sent") else "❌"
            order_created = "✅" if data.get("order_created") else "❌"
            note = data.get("order_error") or data.get("note") or ""
            results.append(
                f"{'🟢' if signal_type == 'BUY' else '🔴'} <b>{signal_type}</b> → Alert {alert_sent} | Order {order_created}"
                + (f"\n   {note}" if note else "")
            )
        except Exception as exc:
            logger.error(f"[TG][ERROR] simulate alert {symbol} {signal_type}: {exc}", exc_info=True)
            errors.append(f"{signal_type}: {exc}")
    if not results and errors:
        send_command_response(
            chat_id,
            "❌ Error simulando alertas:\n" + "\n".join(errors),
        )
        return
    message_lines = [f"🧪 <b>Simulación para {symbol}</b>"]
    message_lines.extend(results)
    if errors:
        message_lines.append("\n⚠️ Errores:")
        message_lines.extend([f"• {err}" for err in errors])
    send_command_response(chat_id, "\n".join(message_lines))

def send_status_message(chat_id: str, db: Session = None) -> bool:
    """Send bot status report"""
    try:
        # Check exchange connection (simplified - check if we can get price)
        exchange_connected = False
        try:
            from price_fetcher import get_price_with_fallback
            result = get_price_with_fallback("BTC_USDT", "15m")
            exchange_connected = result is not None and result.get('price') is not None
        except:
            pass
        
        # Check sheet connection (check if we can read from DB)
        sheet_connected = db is not None
        
        # Get trading stats from database
        active_positions = 0
        tracked_coins = 0
        auto_trading_coins = []
        trade_amounts_list = []
        last_update = "N/A"
        
        if db:
            try:
                from app.models.watchlist import WatchlistItem
                
                # Count active positions (coins with Trade=YES)
                active_positions = db.query(WatchlistItem).filter(
                    WatchlistItem.trade_enabled == True,
                    WatchlistItem.is_deleted == False
                ).count()
                
                # Count tracked coins (all coins, not just Trade=YES)
                tracked_coins = db.query(WatchlistItem).filter(
                    WatchlistItem.symbol.isnot(None),
                    WatchlistItem.is_deleted == False
                ).count()
                
                # Count coins with Trade=YES separately
                # IMPORTANT: Get all coins first to log them for debugging
                active_trade_coins = db.query(WatchlistItem).filter(
                    WatchlistItem.trade_enabled == True,
                    WatchlistItem.symbol.isnot(None),
                    WatchlistItem.is_deleted == False
                ).all()
                
                tracked_coins_with_trade = len(active_trade_coins)
                
                # Log all coins with Trade=YES for debugging
                if tracked_coins_with_trade > 0:
                    trade_yes_symbols = [coin.symbol for coin in active_trade_coins]
                    logger.debug(f"[TG][STATUS] Found {tracked_coins_with_trade} coins with Trade=YES: {', '.join(trade_yes_symbols)}")
                else:
                    logger.debug("[TG][STATUS] No coins found with Trade=YES")
                
                # Use dictionaries to deduplicate by symbol (keep most recent entry)
                auto_trading_dict = {}
                trade_amounts_dict = {}
                
                # Sort by created_at descending to keep most recent entry for each symbol
                # Handle None created_at by using a default datetime
                min_datetime = datetime(1970, 1, 1)
                sorted_coins = sorted(
                    active_trade_coins, 
                    key=lambda c: c.created_at if c.created_at else min_datetime, 
                    reverse=True
                )
                
                for coin in sorted_coins:
                    symbol = coin.symbol or "N/A"
                    
                    # Only add if we haven't seen this symbol before (deduplication)
                    if symbol not in auto_trading_dict:
                        margin = "✅" if coin.trade_on_margin else "❌"
                        auto_trading_dict[symbol] = f"{symbol} (Margin: {margin})"
                    
                    # Only add trade amount if we haven't seen this symbol before
                    if symbol not in trade_amounts_dict:
                        amount = coin.trade_amount_usd or 0
                        if amount > 0:
                            trade_amounts_dict[symbol] = f"{symbol}: ${amount:,.2f}"
                        else:
                            trade_amounts_dict[symbol] = f"{symbol}: N/A"
                
                # Convert dictionaries to lists (sorted by symbol for consistency)
                auto_trading_coins = [auto_trading_dict[s] for s in sorted(auto_trading_dict.keys())]
                trade_amounts_list = [trade_amounts_dict[s] for s in sorted(trade_amounts_dict.keys())]
                
                # Get last update from any coin (use created_at if last_updated doesn't exist)
                try:
                    last_item = db.query(WatchlistItem).filter(
                        WatchlistItem.created_at.isnot(None)
                    ).order_by(WatchlistItem.created_at.desc()).first()
                    
                    if last_item and last_item.created_at:
                        tz = pytz.timezone("Asia/Makassar")  # Bali time (UTC+8)
                        if isinstance(last_item.created_at, datetime):
                            last_update = last_item.created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S WIB")
                        else:
                            last_update = str(last_item.created_at)
                except:
                    pass
                    
            except Exception as e:
                logger.error(f"[TG][STATUS] Error reading from DB: {e}", exc_info=True)
        
        # Count last 24h signals (use order_date if available)
        last_24h_signals = 0
        last_24h_trades = 0
        if db:
            try:
                since = datetime.utcnow() - timedelta(hours=24)
                
                # Count orders placed in last 24h (using order_date)
                last_24h_signals = db.query(WatchlistItem).filter(
                    WatchlistItem.order_date.isnot(None),
                    WatchlistItem.order_date >= since
                ).count()
                
                # Count trades sold in last 24h (using sold=True and sell_date if available, or order_date)
                last_24h_trades = db.query(WatchlistItem).filter(
                    WatchlistItem.sold == True,
                    WatchlistItem.order_date.isnot(None),
                    WatchlistItem.order_date >= since
                ).count()
            except Exception as e:
                logger.debug(f"[TG][STATUS] Error counting 24h stats: {e}")
        
        # Build status message
        tz = pytz.timezone("Asia/Makassar")  # Bali time (UTC+8)
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S WIB")
        
        # Build auto trading section
        if auto_trading_coins:
            auto_trading_section = "✅ Enabled:\n"
            for coin_info in auto_trading_coins[:10]:  # Limit to 10 coins
                auto_trading_section += f"  • {coin_info}\n"
            if len(auto_trading_coins) > 10:
                auto_trading_section += f"  ... and {len(auto_trading_coins) - 10} more"
        else:
            auto_trading_section = "❌ No coins with Trade=YES"
        
        # Build trade amounts section
        if trade_amounts_list:
            trade_amounts_section = ""
            for amount_info in trade_amounts_list[:10]:  # Limit to 10 coins
                trade_amounts_section += f"  • {amount_info}\n"
            if len(trade_amounts_list) > 10:
                trade_amounts_section += f"  ... and {len(trade_amounts_list) - 10} more"
        else:
            trade_amounts_section = "  • No trade amounts configured"
        
        message = f"""📊 <b>Bot Status Report</b>

🤖 <b>System Status:</b>

• Bot: ✅ Active
• Exchange: {'✅ Connected' if exchange_connected else '❌ Disconnected'}
• Database: {'✅ Connected' if sheet_connected else '❌ Disconnected'}
• Signal Engine: ✅ Active

📈 <b>Trading Status:</b>

• Active Positions (Trade=YES): {active_positions}
• Tracked Coins (Total): {tracked_coins}
• Tracked Coins (Trade=YES): {tracked_coins_with_trade}
• Last 24h Signals: {last_24h_signals}
• Last 24h Trades: {last_24h_trades}

⚙️ <b>Settings:</b>

• Trade Amounts:
{trade_amounts_section}
• Auto Trading:
{auto_trading_section}

⏰ <b>Last Update:</b> {last_update if last_update != 'N/A' else now}"""
        
        logger.info(f"[TG][CMD] /status")
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build status: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building status: {str(e)}")


def send_portfolio_message(chat_id: str, db: Session = None) -> bool:
    """Send portfolio with PnL breakdown - Reference Specification Section 3"""
    try:
        if not db:
            error_message = "❌ Database not available"
            error_keyboard = _build_keyboard([
                [{"text": "🔄 Retry", "callback_data": "cmd:portfolio"}],
                [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}],
            ])
            return _send_menu_message(chat_id, error_message, error_keyboard)
        
        # Get portfolio data from API endpoint (same as Dashboard)
        try:
            from app.services.portfolio_cache import get_portfolio_summary
            portfolio_data = get_portfolio_summary(db)
        except Exception as api_err:
            logger.error(f"[TG][ERROR] Failed to fetch portfolio from API: {api_err}", exc_info=True)
            error_message = f"❌ Error fetching portfolio: {str(api_err)}"
            error_keyboard = _build_keyboard([
                [{"text": "🔄 Retry", "callback_data": "cmd:portfolio"}],
                [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}],
            ])
            return _send_menu_message(chat_id, error_message, error_keyboard)
        
        if not portfolio_data:
            message = """💼 <b>Portfolio</b>

No portfolio data available.
Check if exchange sync is running."""
            # Create keyboard even when no data
            keyboard = _build_keyboard([
                [{"text": "🔄 Refresh", "callback_data": "cmd:portfolio"}],
                [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}],
            ])
            logger.info(f"[TG][CMD] /portfolio (no data)")
            return _send_menu_message(chat_id, message, keyboard)
        else:
            # Portfolio Overview (Section 3.1)
            total_value = portfolio_data.get("total_usd", 0.0)
            
            # Calculate PnL breakdown (Section 3.1)
            # Note: These calculations should match Dashboard exactly
            # For now, using placeholder values - should be calculated from executed orders and open positions
            realized_pnl = 0.0  # TODO: Calculate from executed orders
            potential_pnl = 0.0  # TODO: Calculate from open positions (unrealized)
            total_pnl = realized_pnl + potential_pnl
            
            message = f"""💼 <b>Portfolio Overview</b>

💰 <b>Total Portfolio Value:</b> ${total_value:,.2f}

📊 <b>Profit and Loss Breakdown:</b>
  📈 Realized PnL: ${realized_pnl:+,.2f}
  📊 Potential PnL: ${potential_pnl:+,.2f}
  💵 Total PnL: ${total_pnl:+,.2f}

📋 <b>Portfolio Positions</b>
(Sorted by position value, descending)"""
            
            # Portfolio Positions List (Section 3.2)
            assets = portfolio_data.get("balances", [])
            if assets:
                # Get TP/SL values from API endpoint
                tp_sl_values = {}
                try:
                    response = requests.get(
                        f"{API_BASE_URL.rstrip('/')}/api/orders/tp-sl-values",
                        timeout=10
                    )
                    if response.status_code == 200:
                        tp_sl_values = response.json()
                        logger.info(f"[TG][PORTFOLIO] Fetched TP/SL values for {len(tp_sl_values)} currencies")
                    else:
                        logger.warning(f"[TG][PORTFOLIO] Failed to fetch TP/SL values: HTTP {response.status_code}")
                except Exception as tp_sl_err:
                    logger.warning(f"[TG][PORTFOLIO] Error fetching TP/SL values: {tp_sl_err}")
                
                # Sort by USD value descending
                sorted_assets = sorted(assets, key=lambda x: x.get("usd_value", 0), reverse=True)
                
                # Get open orders count per symbol
                from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
                open_orders_by_symbol = {}
                open_orders = db.query(ExchangeOrder).filter(
                    ExchangeOrder.status.in_([
                        OrderStatusEnum.NEW,
                        OrderStatusEnum.ACTIVE,
                        OrderStatusEnum.PARTIALLY_FILLED
                    ])
                ).all()
                for order in open_orders:
                    symbol = order.symbol or "N/A"
                    # Extract base currency from symbol (e.g., "BTC_USDT" -> "BTC")
                    base_currency = symbol.split('_')[0].upper() if '_' in symbol else symbol.upper()
                    open_orders_by_symbol[base_currency] = open_orders_by_symbol.get(base_currency, 0) + 1
                
                # Display all positions
                for asset in sorted_assets:
                    coin = asset.get("currency", "N/A")
                    balance = asset.get("balance", 0.0)
                    usd_value = asset.get("usd_value", 0.0)
                    available = asset.get("available", 0.0)
                    reserved = balance - available
                    
                    # Format balance
                    if balance >= 1:
                        balance_str = f"{balance:,.4f}"
                    elif balance >= 0.000001:
                        balance_str = f"{balance:,.6f}"
                    else:
                        balance_str = f"{balance:.8f}"
                    
                    # Get open orders count
                    order_count = open_orders_by_symbol.get(coin, 0)
                    
                    # Get TP/SL values from API response
                    coin_tp_sl = tp_sl_values.get(coin, {})
                    tp_value = coin_tp_sl.get("tp_value_usd", 0.0) or 0.0
                    sl_value = coin_tp_sl.get("sl_value_usd", 0.0) or 0.0
                    
                    # Indicate if this is an open position (has reserved balance)
                    position_status = "🔒 Open Position" if reserved > 0 else "💤 Available"
                    
                    # Add each position to the message
                    message += f"""

🪙 <b>{coin}</b> {position_status}
  Position Value: ${usd_value:,.2f}
  Units Held: {balance_str}
  Available: {available:,.4f} | Reserved: {reserved:,.4f}
  Open Orders: {order_count}
  TP Value: ${tp_value:,.2f} | SL Value: ${sl_value:,.2f}"""
            else:
                message += "\n\nNo positions found."
        
        # Add back button
        keyboard = _build_keyboard([
            [{"text": "🔄 Refresh", "callback_data": "cmd:portfolio"}],
            [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}],
        ])
        
        logger.info(f"[TG][CMD] /portfolio")
        
        # Check message length (Telegram limit is 4096 characters)
        if len(message) > 4096:
            logger.warning(f"[TG][PORTFOLIO] Message too long ({len(message)} chars), truncating...")
            # Truncate message but keep the header and footer
            header_end = message.find("📋 <b>Portfolio Positions</b>")
            if header_end > 0:
                header = message[:header_end + len("📋 <b>Portfolio Positions</b>\n(Sorted by position value, descending)")]
                message = header + "\n\n⚠️ Message truncated due to length. Showing first positions only."
            else:
                message = message[:4000] + "\n\n⚠️ Message truncated..."
        
        return _send_menu_message(chat_id, message, keyboard)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build portfolio: {e}", exc_info=True)
        # Send error with menu keyboard so user can navigate back
        error_message = f"❌ Error building portfolio: {str(e)}"
        error_keyboard = _build_keyboard([
            [{"text": "🔄 Retry", "callback_data": "cmd:portfolio"}],
            [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}],
        ])
        return _send_menu_message(chat_id, error_message, error_keyboard)


def send_signals_message(chat_id: str, db: Session = None) -> bool:
    """Send all trading signals with detailed information"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Get signals from TradeSignal model (primary source)
        from app.models.trade_signal import TradeSignal
        from app.models.watchlist import WatchlistItem
        from app.models.exchange_order import ExchangeOrder
        from app.models.market_price import MarketData
        
        # Get recent signals (last 10)
        # Show signals with trade_enabled coins or recent signals
        from app.models.watchlist import WatchlistItem as WL
        
        # Get signals for coins with alert_enabled or trade_enabled
        enabled_symbols = db.query(WL.symbol).filter(
            (WL.alert_enabled == True) | (WL.trade_enabled == True)
        ).all()
        enabled_symbols_list = [s[0] for s in enabled_symbols] if enabled_symbols else []
        
        if enabled_symbols_list:
            trade_signals = db.query(TradeSignal).filter(
                TradeSignal.symbol.in_(enabled_symbols_list)
            ).order_by(
                TradeSignal.last_update_at.desc()
            ).limit(10).all()
        else:
            # Fallback: show all recent signals
            trade_signals = db.query(TradeSignal).order_by(
                TradeSignal.last_update_at.desc()
            ).limit(10).all()
        
        if not trade_signals:
            message = """📈 Signals

No signals generated yet."""
        else:
            message = f"""📈 *Signals ({len(trade_signals)} total)*"""
            
            for signal in trade_signals:
                symbol = signal.symbol or "N/A"
                
                # Get signal price (historical - when signal was CREATED)
                # Use entry_price which is never updated
                signal_price = signal.entry_price or signal.current_price or 0
                
                # Get market data for this symbol (has all technical indicators)
                market_data = db.query(MarketData).filter(MarketData.symbol == symbol).first()
                
                # Get current price from multiple sources
                current_price = 0
                
                # 1. Try MarketData (most reliable source for current price)
                if market_data and market_data.price and market_data.price > 0:
                    current_price = market_data.price
                
                # 2. Try watchlist as backup
                watchlist_item = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
                if current_price == 0 and watchlist_item and watchlist_item.price and watchlist_item.price > 0:
                    current_price = watchlist_item.price
                
                # 2. If not in watchlist or no price, try fetching from API
                if current_price == 0:
                    try:
                        import requests
                        # Try Crypto.com API (get-tickers returns all tickers)
                        ticker_url = "https://api.crypto.com/exchange/v1/public/get-tickers"
                        ticker_response = requests.get(ticker_url, timeout=10)
                        if ticker_response.status_code == 200:
                            ticker_data = ticker_response.json()
                            if "result" in ticker_data and "data" in ticker_data["result"]:
                                tickers = ticker_data["result"]["data"]
                                # Find ticker for our symbol
                                for ticker in tickers:
                                    if ticker.get("i") == symbol:
                                        current_price = float(ticker.get("a", 0))  # ask price
                                        logger.info(f"[TG][SIGNALS] Fetched current price for {symbol}: ${current_price:.2f}")
                                        break
                    except Exception as e:
                        logger.debug(f"[TG][SIGNALS] Could not fetch price for {symbol}: {e}")
                
                # 3. Fallback to signal price if still no current price
                if current_price == 0:
                    current_price = signal_price
                
                # Calculate percentage change
                price_change_pct = 0
                change_emoji = ""
                if signal_price > 0 and current_price > 0:
                    price_change_pct = ((current_price - signal_price) / signal_price) * 100
                    if price_change_pct > 0:
                        change_emoji = "🟢"  # Green for profit
                    elif price_change_pct < 0:
                        change_emoji = "🔴"  # Red for loss
                    else:
                        change_emoji = "⚪"  # Neutral
                
                # Format prices
                if signal_price >= 100:
                    signal_price_str = f"${signal_price:,.2f}"
                elif signal_price > 0:
                    signal_price_str = f"${signal_price:,.4f}"
                else:
                    signal_price_str = "N/A"
                
                if current_price >= 100:
                    current_price_str = f"${current_price:,.2f}"
                elif current_price > 0:
                    current_price_str = f"${current_price:,.4f}"
                else:
                    current_price_str = "N/A"
                
                # Get technical parameters from signal, or fallback to market_data
                # Priority: signal > market_data > "No data"
                rsi = signal.rsi or (market_data.rsi if market_data else None)
                ma50 = signal.ma50 or (market_data.ma50 if market_data else None)
                ema10 = signal.ema10 or (market_data.ema10 if market_data else None)
                atr = signal.atr or (market_data.atr if market_data else None)
                volume_24h = signal.volume_24h or (market_data.volume_24h if market_data else None)
                volume_ratio = signal.volume_ratio or (market_data.volume_ratio if market_data else None)
                
                params = []
                if rsi:
                    params.append(f"RSI: {rsi:.1f}")
                if ma50:
                    params.append(f"MA50: ${ma50:,.2f}" if ma50 >= 100 else f"MA50: ${ma50:,.4f}")
                if ema10:
                    params.append(f"EMA10: ${ema10:,.2f}" if ema10 >= 100 else f"EMA10: ${ema10:,.4f}")
                if volume_ratio:
                    params.append(f"Vol: {volume_ratio:.2f}x")
                
                params_str = " | ".join(params) if params else "No params available"
                
                # Format timestamp - use created_at to show when signal was CREATED
                tz = pytz.timezone("Asia/Makassar")  # Bali time (UTC+8)
                if signal.created_at:
                    ts = signal.created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S WIB")
                elif signal.last_update_at:
                    ts = signal.last_update_at.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S WIB")
                else:
                    ts = "N/A"
                
                # Get order information
                order_info = ""
                if signal.exchange_order_id:
                    # Try to find order in database
                    order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.exchange_order_id == signal.exchange_order_id
                    ).first()
                    
                    if order:
                        order_info = f"\n📦 *Order:* {order.exchange_order_id[:12]}..."
                        order_info += f"\n   Status: {order.status.value if hasattr(order.status, 'value') else order.status}"
                        if order.price:
                            order_price = f"${float(order.price):,.2f}" if float(order.price) >= 100 else f"${float(order.price):,.4f}"
                            order_info += f" | Price: {order_price}"
                    else:
                        order_info = f"\n📦 *Order:* {signal.exchange_order_id[:12]}... (Status: {signal.status.value if signal.status else 'PENDING'})"
                else:
                    # No order placed - show reason
                    status_val = signal.status.value if signal.status else 'PENDING'
                    if status_val == 'pending':
                        order_info = "\n⏸️ *Order not placed yet* (waiting for signal confirmation)"
                    elif status_val == 'order_placed':
                        order_info = "\n✅ *Order placed* (ID not synced yet)"
                    else:
                        order_info = f"\n📋 *Status:* {status_val}"
                
                # Build message
                emoji = "🟢"  # BUY signals
                
                message += f"""

{emoji} *{symbol}* BUY
━━━━━━━━━━━━━━━━━━━━
🕐 Signal Created: {ts}
💰 Signal Price: {signal_price_str}
💵 Current Price: {current_price_str} {change_emoji}
{'   Change: ' + f'{price_change_pct:+.2f}%' if signal_price > 0 and current_price > 0 else ''}
📊 {params_str}{order_info}"""
        
        logger.info(f"[TG][CMD] /signals")
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build signals: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building signals: {str(e)}")


def send_balance_message(chat_id: str, db: Session = None) -> bool:
    """Send balance information"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Import ExchangeBalance model
        from app.models.exchange_balance import ExchangeBalance
        
        # Get exchange balances
        balances = db.query(ExchangeBalance).filter(
            ExchangeBalance.total > 0
        ).order_by(ExchangeBalance.total.desc()).all()
        
        if not balances:
            message = """💰 <b>Balance</b>

No balances found.
Check if exchange sync is running and API credentials are configured."""
        else:
            # Calculate total USD value
            total_usd = 0
            balance_items = []
            
            for bal in balances:
                asset = bal.asset
                total = float(bal.total)
                usd_value = float(bal.usd_value) if bal.usd_value else 0
                
                # For USDT/USD, the total is already in USD
                if asset == 'USDT' or asset == 'USD':
                    usd_value = total
                
                total_usd += usd_value
                
                # Format balance
                if asset == 'USDT' or asset == 'USD':
                    total_str = f"${total:,.2f}"
                elif total >= 1:
                    total_str = f"{total:,.4f}"
                else:
                    total_str = f"{total:.8f}"
                
                usd_value_str = f"${usd_value:,.2f}" if usd_value > 0 else "N/A"
                
                balance_items.append({
                    'asset': asset,
                    'total_str': total_str,
                    'usd_value_str': usd_value_str,
                    'usd_value': usd_value
                })
            
            # Sort by USD value descending
            balance_items.sort(key=lambda x: x['usd_value'], reverse=True)
            
            message = f"""💰 <b>Balance</b>

💵 <b>Total Value:</b> ${total_usd:,.2f}

📊 <b>Assets ({len(balances)}):</b>"""
            
            for item in balance_items[:10]:  # Show top 10
                message += f"""

🪙 <b>{item['asset']}</b>
• Amount: {item['total_str']}
• Value: {item['usd_value_str']}"""
            
            if len(balances) > 10:
                message += f"\n\n… and {len(balances) - 10} more assets"
            
            logger.info(f"[TG][CMD] /balance")
            return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build balance: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building balance: {str(e)}")


def send_watchlist_message(chat_id: str, db: Session = None) -> bool:
    """Send watchlist of coins with Trade=YES"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        from app.services.config_loader import load_config
        
        config = load_config()
        coins_config = config.get("coins", {})
        
        # Pull every visible watchlist entry, not only Trade=YES
        coins = db.query(WatchlistItem).filter(
            WatchlistItem.symbol.isnot(None),
            WatchlistItem.symbol != "",
            WatchlistItem.is_deleted == False  # noqa
        ).order_by(WatchlistItem.symbol.asc()).all()
        
        if not coins:
            return send_command_response(chat_id, "👀 <b>Watchlist</b>\n\nNo hay monedas en la cartera.")
        
        trade_enabled_coins = [c for c in coins if c.trade_enabled]
        disabled_coins = [c for c in coins if not c.trade_enabled]
        
        def _format_entry(coin: WatchlistItem) -> str:
            symbol = (coin.symbol or "N/A").upper()
            last_price = coin.price or 0
            buy_target = coin.buy_target
            preset = coins_config.get(symbol, {}).get("preset", "swing")
            if "-" not in preset:
                preset = f"{preset}-{(coin.sl_tp_mode or 'conservative')}"
            price_str = (
                f"${last_price:,.2f}" if isinstance(last_price, (int, float)) and last_price >= 1
                else (f"${last_price:,.4f}" if isinstance(last_price, (int, float)) and last_price > 0 else "N/A")
            )
            target_str = (
                f"${buy_target:,.2f}" if isinstance(buy_target, (int, float)) and buy_target >= 1
                else (f"${buy_target:,.4f}" if isinstance(buy_target, (int, float)) and buy_target and buy_target > 0 else "N/A")
            )
            amount_str = f"${coin.trade_amount_usd:,.2f}" if coin.trade_amount_usd else "N/A"
            alert_icon = "🔔" if coin.alert_enabled else "🔕"
            trade_icon = "🤖" if coin.trade_enabled else "⛔"
            margin_icon = "⚡" if coin.trade_on_margin else "💤"
            return (
                f"\n📊 <b>{symbol}</b>\n"
                f"  {alert_icon} | {trade_icon} | {margin_icon}\n"
                f"  🎯 Estrategia: <b>{preset}</b>\n"
                f"  💵 Amount: {amount_str}\n"
                f"  💰 Precio: {price_str} | Objetivo: {target_str}"
            )
        
        message = f"👀 <b>Watchlist Completa</b>\n\nTotal monedas: {len(coins)}"
        if trade_enabled_coins:
            message += f"\n\n✅ <b>Trade = YES ({len(trade_enabled_coins)})</b>"
            for coin in trade_enabled_coins[:20]:
                message += _format_entry(coin)
            if len(trade_enabled_coins) > 20:
                message += f"\n… y {len(trade_enabled_coins) - 20} más con Trade=YES"
        if disabled_coins:
            message += f"\n\n⚪ <b>Trade = NO ({len(disabled_coins)})</b>"
            for coin in disabled_coins[:20]:
                message += _format_entry(coin)
            if len(disabled_coins) > 20:
                message += f"\n… y {len(disabled_coins) - 20} más con Trade=NO"
        
        message += "\n\n💡 Usa el menú ⚙️ Watchlist Control para editar cualquier símbolo."
        
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build watchlist: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building watchlist: {str(e)}")


def send_open_orders_message(chat_id: str, db: Session = None) -> bool:
    """Send open orders list"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        
        # Get open orders
        open_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.status.in_([
                OrderStatusEnum.NEW,
                OrderStatusEnum.ACTIVE,
                OrderStatusEnum.PARTIALLY_FILLED
            ])
        ).order_by(ExchangeOrder.exchange_create_time.desc()).limit(20).all()
        
        if not open_orders:
            message = """📋 <b>Open Orders</b>

No open orders found."""
        else:
            message = f"""📋 <b>Open Orders ({len(open_orders)})</b>"""
            
            for order in open_orders:
                symbol = order.symbol or "N/A"
                side = order.side.value if order.side else "N/A"
                status = order.status.value if order.status else "N/A"
                quantity = float(order.quantity) if order.quantity else 0
                price = float(order.price) if order.price else 0
                order_type = order.order_type or "LIMIT"
                
                # Format price
                if price > 0:
                    if price >= 100:
                        price_str = f"${price:,.2f}"
                    else:
                        price_str = f"${price:,.4f}"
                else:
                    price_str = "Market"
                
                # Format quantity
                if quantity >= 1:
                    quantity_str = f"{quantity:,.4f}"
                elif quantity >= 0.000001:
                    quantity_str = f"{quantity:,.6f}"
                else:
                    quantity_str = f"{quantity:.8f}"
                
                # Calculate value
                if price > 0 and quantity > 0:
                    value = price * quantity
                    value_str = f"${value:,.2f}"
                else:
                    value_str = "N/A"
                
                # Order type indicator
                if order_type == "STOP_LIMIT" or (order.order_role and "STOP" in str(order.order_role)):
                    type_emoji = "🛑"
                elif order_type == "TAKE_PROFIT_LIMIT" or (order.order_role and "TAKE_PROFIT" in str(order.order_role)):
                    type_emoji = "🎯"
                else:
                    type_emoji = "📝"
                
                side_emoji = "🟢" if side == "BUY" else "🔴"
                
                message += f"""

{type_emoji} {side_emoji} <b>{symbol}</b> {side}
  Type: {order_type} | Status: {status}
  Qty: {quantity_str} | Price: {price_str}
  Value: {value_str}"""
        
        logger.info(f"[TG][CMD] /open_orders")
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build open orders: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building open orders: {str(e)}")


def send_executed_orders_message(chat_id: str, db: Session = None) -> bool:
    """Send executed orders list"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        from datetime import timezone
        
        # Get executed orders (FILLED status) from last 24 hours
        yesterday = datetime.now(timezone.utc) - timedelta(hours=24)
        executed_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.exchange_create_time >= yesterday
        ).order_by(ExchangeOrder.exchange_create_time.desc()).limit(20).all()
        
        if not executed_orders:
            message = """✅ <b>Executed Orders (Last 24h)</b>

No executed orders found in the last 24 hours."""
        else:
            # Calculate total P&L
            total_pnl = 0
            
            message = f"""✅ <b>Executed Orders (Last 24h)</b>

📊 <b>Total: {len(executed_orders)} order(s)</b>"""
            
            for order in executed_orders:
                symbol = order.symbol or "N/A"
                side = order.side.value if order.side else "N/A"
                quantity = float(order.quantity) if order.quantity else 0
                price = float(order.price) if order.price else 0
                
                # Format price
                if price > 0:
                    if price >= 100:
                        price_str = f"${price:,.2f}"
                    else:
                        price_str = f"${price:,.4f}"
                else:
                    price_str = "Market"
                
                # Format quantity
                if quantity >= 1:
                    quantity_str = f"{quantity:,.4f}"
                elif quantity >= 0.000001:
                    quantity_str = f"{quantity:,.6f}"
                else:
                    quantity_str = f"{quantity:.8f}"
                
                # Calculate value
                if price > 0 and quantity > 0:
                    value = price * quantity
                    value_str = f"${value:,.2f}"
                else:
                    value_str = "N/A"
                
                # Format timestamp
                if order.exchange_create_time:
                    try:
                        if isinstance(order.exchange_create_time, datetime):
                            ts = order.exchange_create_time
                        else:
                            ts = datetime.fromtimestamp(order.exchange_create_time / 1000, tz=timezone.utc)
                        tz = pytz.timezone("Asia/Makassar")  # Bali time
                        ts_local = ts.astimezone(tz)
                        time_str = ts_local.strftime("%Y-%m-%d %H:%M")
                    except:
                        time_str = "N/A"
                else:
                    time_str = "N/A"
                
                side_emoji = "🟢" if side == "BUY" else "🔴"
                
                message += f"""

{side_emoji} <b>{symbol}</b> {side}
  Qty: {quantity_str} | Price: {price_str}
  Value: {value_str}
  Time: {time_str}"""
            
            # Add total P&L if calculated
            if total_pnl != 0:
                pnl_emoji = "📈" if total_pnl > 0 else "📉"
                message += f"""

{pnl_emoji} <b>Total P&L: ${total_pnl:,.2f}</b>"""
        
        logger.info(f"[TG][CMD] /executed_orders")
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build executed orders: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building executed orders: {str(e)}")


def send_expected_take_profit_message(chat_id: str, db: Session = None) -> bool:
    """Send expected take profit summary for all open positions - Reference Specification Section 6"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Call API endpoint to get expected take profit summary
        try:
            response = requests.get(
                f"{API_BASE_URL.rstrip('/')}/api/dashboard/expected-take-profit",
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
        except Exception as api_err:
            logger.error(f"[TG][ERROR] Failed to fetch expected TP from API: {api_err}", exc_info=True)
            return send_command_response(chat_id, f"❌ Error fetching expected take profit: {str(api_err)}")
        
        summary = data.get("summary", [])
        total_symbols = data.get("total_symbols", 0)
        last_updated = data.get("last_updated")
        
        if not summary:
            message = """🎯 <b>Expected Take Profit</b>

No open positions with take profit orders found."""
        else:
            message = f"""🎯 <b>Expected Take Profit</b>

📊 <b>Total Symbols: {total_symbols}</b>"""
            
            # Format last updated time
            if last_updated:
                try:
                    if isinstance(last_updated, str):
                        ts = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                    else:
                        from datetime import timezone
                        ts = datetime.fromtimestamp(last_updated, tz=timezone.utc)
                    tz = pytz.timezone("Asia/Makassar")
                    ts_local = ts.astimezone(tz)
                    time_str = ts_local.strftime("%Y-%m-%d %H:%M")
                    message += f"\n🕐 Last update: {time_str}"
                except:
                    pass
            
            message += "\n\n"
            
            # Display each symbol's expected TP
            for item in summary[:20]:  # Limit to 20 for readability
                symbol = item.get("symbol", "N/A")
                net_qty = item.get("net_qty", 0)
                expected_tp = item.get("expected_tp", 0)
                position_value = item.get("position_value", 0)
                avg_entry = item.get("avg_entry_price", 0)
                current_price = item.get("current_price", 0)
                unrealized_pnl = item.get("unrealized_pnl", 0)
                
                # Format values
                expected_tp_str = f"${expected_tp:,.2f}" if expected_tp else "N/A"
                position_value_str = f"${position_value:,.2f}" if position_value else "N/A"
                
                # Format quantity
                if abs(net_qty) >= 1:
                    qty_str = f"{net_qty:,.4f}"
                elif abs(net_qty) >= 0.000001:
                    qty_str = f"{net_qty:,.6f}"
                else:
                    qty_str = f"{net_qty:.8f}"
                
                message += f"""📈 <b>{symbol}</b>
  Net Qty: {qty_str}
  Position Value: {position_value_str}
  Expected TP: {expected_tp_str}"""
                
                if avg_entry and current_price:
                    pnl_pct = ((current_price - avg_entry) / avg_entry * 100) if avg_entry > 0 else 0
                    pnl_emoji = "📈" if pnl_pct >= 0 else "📉"
                    message += f"\n  {pnl_emoji} Unrealized P&L: {pnl_pct:+.2f}%"
                
                # Add button to view details
                message += "\n"
            
            if len(summary) > 20:
                message += f"\n... and {len(summary) - 20} more positions"
        
        # Add back button
        keyboard = _build_keyboard([
            [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}]
        ])
        
        logger.info(f"[TG][CMD] /expected_take_profit")
        return _send_menu_message(chat_id, message, keyboard)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build expected take profit: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building expected take profit: {str(e)}")


def show_portfolio_menu(chat_id: str, db: Session = None, message_id: Optional[int] = None) -> bool:
    """Show portfolio sub-menu with options"""
    try:
        logger.info(f"[TG][MENU] show_portfolio_menu called for chat_id={chat_id}, message_id={message_id}")
        text = "💼 <b>Portfolio</b>\n\nSelect an option:"
        keyboard = _build_keyboard([
            [{"text": "📊 View Portfolio", "callback_data": "cmd:portfolio"}],
            [{"text": "🔄 Refresh", "callback_data": "cmd:portfolio"}],
            [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}],
        ])
        logger.info(f"[TG][MENU] Portfolio menu keyboard: {json.dumps(keyboard, indent=2)}")
        result = _send_or_edit_menu(chat_id, text, keyboard, message_id)
        logger.info(f"[TG][MENU] Portfolio menu send result: {result}")
        return result
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing portfolio menu: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error showing portfolio menu: {str(e)}")


def show_open_orders_menu(chat_id: str, db: Session = None, message_id: Optional[int] = None) -> bool:
    """Show open orders sub-menu with options"""
    try:
        text = "📋 <b>Open Orders</b>\n\nSelect an option:"
        keyboard = _build_keyboard([
            [{"text": "📊 View Open Orders", "callback_data": "cmd:open_orders"}],
            [{"text": "🔄 Refresh", "callback_data": "cmd:open_orders"}],
            [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}],
        ])
        return _send_or_edit_menu(chat_id, text, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing open orders menu: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error showing open orders menu: {str(e)}")


def show_expected_tp_menu(chat_id: str, db: Session = None, message_id: Optional[int] = None) -> bool:
    """Show expected take profit sub-menu with options"""
    try:
        text = "🎯 <b>Expected Take Profit</b>\n\nSelect an option:"
        keyboard = _build_keyboard([
            [{"text": "📊 View Expected TP", "callback_data": "cmd:expected_tp"}],
            [{"text": "🔄 Refresh", "callback_data": "cmd:expected_tp"}],
            [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}],
        ])
        return _send_or_edit_menu(chat_id, text, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing expected TP menu: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error showing expected TP menu: {str(e)}")


def show_executed_orders_menu(chat_id: str, db: Session = None, message_id: Optional[int] = None) -> bool:
    """Show executed orders sub-menu with options"""
    try:
        text = "✅ <b>Executed Orders</b>\n\nSelect an option:"
        keyboard = _build_keyboard([
            [{"text": "📊 View Executed Orders", "callback_data": "cmd:executed_orders"}],
            [{"text": "🔄 Refresh", "callback_data": "cmd:executed_orders"}],
            [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}],
        ])
        return _send_or_edit_menu(chat_id, text, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing executed orders menu: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error showing executed orders menu: {str(e)}")


def show_monitoring_menu(chat_id: str, db: Session = None, message_id: Optional[int] = None) -> bool:
    """Show monitoring sub-menu with sections - Reference Specification Section 8"""
    try:
        text = "🔍 <b>Monitoring</b>\n\nSelect a monitoring section:"
        keyboard = _build_keyboard([
            [{"text": "🖥️ System Monitoring", "callback_data": "monitoring:system"}],
            [{"text": "⏱️ Throttle", "callback_data": "monitoring:throttle"}],
            [{"text": "⚙️ Monitoring Workflows", "callback_data": "monitoring:workflows"}],
            [{"text": "🚫 Blocked Telegram Messages", "callback_data": "monitoring:blocked"}],
            [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}],
        ])
        return _send_or_edit_menu(chat_id, text, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing monitoring menu: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error showing monitoring menu: {str(e)}")


def send_system_monitoring_message(chat_id: str, db: Session = None, message_id: Optional[int] = None) -> bool:
    """Send system monitoring information - Reference Specification Section 8.1"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Get system health from API
        try:
            response = requests.get(
                f"{API_BASE_URL.rstrip('/')}/api/monitoring/health",
                timeout=10
            )
            if response.status_code == 200:
                health_data = response.json()
            else:
                health_data = {}
        except:
            health_data = {}
        
        # Build message from health data
        message = "🖥️ <b>System Monitoring</b>\n\n"
        
        # Backend status
        backend_status = health_data.get("backend", {}).get("status", "unknown")
        backend_emoji = "✅" if backend_status == "healthy" else "⚠️" if backend_status == "unhealthy" else "❌"
        message += f"{backend_emoji} <b>Backend:</b> {backend_status}\n"
        
        # Database status
        db_status = health_data.get("database", {}).get("status", "unknown")
        db_emoji = "✅" if db_status == "connected" else "❌"
        message += f"{db_emoji} <b>Database:</b> {db_status}\n"
        
        # Exchange API status
        exchange_status = health_data.get("exchange", {}).get("status", "unknown")
        exchange_emoji = "✅" if exchange_status == "connected" else "❌"
        message += f"{exchange_emoji} <b>Exchange API:</b> {exchange_status}\n"
        
        # Trading bot status
        bot_status = health_data.get("bot", {}).get("status", "unknown")
        bot_emoji = "🟢" if bot_status == "running" else "🔴"
        message += f"{bot_emoji} <b>Trading Bot:</b> {bot_status}\n"
        
        # Live trading mode
        live_trading = health_data.get("bot", {}).get("live_trading_enabled", False)
        mode_emoji = "🟢" if live_trading else "🔴"
        mode_text = "LIVE" if live_trading else "DRY RUN"
        message += f"{mode_emoji} <b>Mode:</b> {mode_text}\n"
        
        # Last sync times
        if "last_sync" in health_data:
            message += f"\n🕐 <b>Last Sync:</b> {health_data.get('last_sync', 'N/A')}\n"
        
        keyboard = _build_keyboard([
            [{"text": "🔄 Refresh", "callback_data": "monitoring:system"}],
            [{"text": "🔙 Back to Monitoring", "callback_data": "menu:monitoring"}],
        ])
        
        return _send_or_edit_menu(chat_id, message, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build system monitoring: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building system monitoring: {str(e)}")


def send_throttle_message(chat_id: str, db: Session = None, message_id: Optional[int] = None) -> bool:
    """Send throttle information (recent Telegram messages) - Reference Specification Section 8.2"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Get recent Telegram messages from API
        try:
            response = requests.get(
                f"{API_BASE_URL.rstrip('/')}/api/monitoring/telegram-messages",
                params={"limit": 20},
                timeout=10
            )
            if response.status_code == 200:
                messages_data = response.json()
                messages = messages_data.get("messages", [])
            else:
                messages = []
        except:
            messages = []
        
        message = "⏱️ <b>Throttle</b>\n\n"
        message += f"📊 <b>Recent Messages ({len(messages)} shown)</b>\n\n"
        
        if not messages:
            message += "No recent messages found."
        else:
            for msg in messages[:10]:  # Show last 10
                timestamp = msg.get("timestamp", "N/A")
                content = msg.get("content", "")[:50]  # Truncate long messages
                msg_type = msg.get("type", "unknown")
                status = msg.get("status", "sent")
                
                status_emoji = "✅" if status == "sent" else "⏸️" if status == "throttled" else "🚫"
                message += f"{status_emoji} <b>{timestamp}</b> [{msg_type}]\n"
                message += f"   {content}...\n\n"
        
        keyboard = _build_keyboard([
            [{"text": "🔄 Refresh", "callback_data": "monitoring:throttle"}],
            [{"text": "🔙 Back to Monitoring", "callback_data": "menu:monitoring"}],
        ])
        
        return _send_or_edit_menu(chat_id, message, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build throttle: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building throttle: {str(e)}")


def send_workflows_monitoring_message(chat_id: str, db: Session = None, message_id: Optional[int] = None) -> bool:
    """Send workflow monitoring information - Reference Specification Section 8.3"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Get workflow status from API
        try:
            response = requests.get(
                f"{API_BASE_URL.rstrip('/')}/api/monitoring/workflows",
                timeout=10
            )
            if response.status_code == 200:
                workflows_data = response.json()
                workflows = workflows_data.get("workflows", [])
            else:
                workflows = []
        except:
            workflows = []
        
        message = "⚙️ <b>Monitoring Workflows</b>\n\n"
        
        if not workflows:
            message += "No workflow information available."
        else:
            for workflow in workflows:
                name = workflow.get("name", "Unknown")
                last_execution = workflow.get("last_execution", "N/A")
                status = workflow.get("status", "unknown")
                count = workflow.get("execution_count", 0)
                
                status_emoji = "✅" if status == "success" else "❌" if status == "error" else "⏳"
                message += f"{status_emoji} <b>{name}</b>\n"
                message += f"   Last: {last_execution}\n"
                message += f"   Count: {count}\n"
                if status == "error":
                    error = workflow.get("last_error", "")
                    if error:
                        message += f"   Error: {error[:50]}...\n"
                message += "\n"
        
        keyboard = _build_keyboard([
            [{"text": "🔄 Refresh", "callback_data": "monitoring:workflows"}],
            [{"text": "🔙 Back to Monitoring", "callback_data": "menu:monitoring"}],
        ])
        
        return _send_or_edit_menu(chat_id, message, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build workflows monitoring: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building workflows monitoring: {str(e)}")


def send_blocked_messages_message(chat_id: str, db: Session = None, message_id: Optional[int] = None) -> bool:
    """Send blocked Telegram messages - Reference Specification Section 8.4"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Get blocked messages from API (filter for blocked=True)
        try:
            response = requests.get(
                f"{API_BASE_URL.rstrip('/')}/api/monitoring/telegram-messages",
                params={"blocked": True, "limit": 20},
                timeout=10
            )
            if response.status_code == 200:
                messages_data = response.json()
                messages = messages_data.get("messages", [])
            else:
                messages = []
        except:
            messages = []
        
        message = "🚫 <b>Blocked Telegram Messages</b>\n\n"
        message += f"📊 <b>Blocked Messages ({len(messages)} shown)</b>\n\n"
        
        if not messages:
            message += "No blocked messages found."
        else:
            for msg in messages[:10]:  # Show last 10
                timestamp = msg.get("timestamp", "N/A")
                content = msg.get("content", "")[:50]  # Truncate long messages
                reason = msg.get("block_reason", "Unknown")
                
                message += f"🚫 <b>{timestamp}</b>\n"
                message += f"   Reason: {reason}\n"
                message += f"   {content}...\n\n"
        
        keyboard = _build_keyboard([
            [{"text": "🔄 Refresh", "callback_data": "monitoring:blocked"}],
            [{"text": "🔙 Back to Monitoring", "callback_data": "menu:monitoring"}],
        ])
        
        return _send_or_edit_menu(chat_id, message, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build blocked messages: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building blocked messages: {str(e)}")


def send_version_message(chat_id: str) -> bool:
    """Send version information"""
    try:
        # Get version from main module or use default
        version = "0.40.0"  # Default version
        
        try:
            # Try to import version from main
            from app.main import app
            if hasattr(app, 'version'):
                version = app.version
        except:
            try:
                # Try reading from file as fallback
                import os
                main_path = os.path.join(os.path.dirname(__file__), "..", "main.py")
                if os.path.exists(main_path):
                    with open(main_path, 'r') as f:
                        content = f.read()
                        import re
                        match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
                        if match:
                            version = match.group(1)
            except:
                pass
        
        message = f"""📝 <b>Version Information</b>

Current Version: <b>{version}</b>

For detailed version history, check the dashboard Version History tab."""
        
        # Add back button to menu
        keyboard = _build_keyboard([
            [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}]
        ])
        
        logger.info(f"[TG][CMD] /version")
        return _send_menu_message(chat_id, message, keyboard)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build version: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building version: {str(e)}")


def send_alerts_list_message(chat_id: str, db: Session = None) -> bool:
    """Send list of coins with Alert=YES"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Get coins with Alert=YES
        coins = db.query(WatchlistItem).filter(
            WatchlistItem.alert_enabled == True,
            WatchlistItem.symbol.isnot(None)
        ).order_by(WatchlistItem.symbol).all()
        
        logger.info(f"[TG][ALERTS] Found {len(coins)} coins with Alert=YES")
        
        if not coins:
            message = """🔔 *Alerts*

No coins with Alert=YES."""
        else:
            message = f"""🔔 *Alerts ({len(coins)} coins with Alert=YES)*"""
            
            for coin in coins:
                symbol = coin.symbol or "N/A"
                last_price = coin.price or 0
                buy_target = coin.buy_target or "N/A"
                
                # Status indicators
                trade_status = "✅ Trade" if coin.trade_enabled else "❌ Trade"
                margin_status = "✅ Margin" if coin.trade_on_margin else "❌ Margin"
                
                if isinstance(last_price, (int, float)) and last_price > 0:
                    if last_price >= 100:
                        price_str = f"${last_price:,.2f}"
                    else:
                        price_str = f"${last_price:,.4f}"
                else:
                    price_str = "N/A"
                
                if isinstance(buy_target, (int, float)) and buy_target > 0:
                    if buy_target >= 100:
                        target_str = f"${buy_target:,.2f}"
                    else:
                        target_str = f"${buy_target:,.4f}"
                else:
                    target_str = "N/A"
                
                # Add trade amount if available
                amount_str = ""
                if coin.trade_amount_usd:
                    amount_str = f" | Amount: ${coin.trade_amount_usd:,.2f}"
                
                message += f"""

• *{symbol}*
  {trade_status} | {margin_status}
  Price: {price_str} | Target: {target_str}{amount_str}"""
        
        logger.info(f"[TG][CMD] /alerts")
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build alerts list: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building alerts list: {str(e)}")


def send_analyze_message(chat_id: str, text: str, db: Session = None) -> bool:
    """Send analysis for a specific coin - or show menu if no symbol provided"""
    try:
        # Parse symbol from command
        parts = text.split()
        if len(parts) < 2:
            # No symbol provided - show menu with all watchlist coins
            if not db:
                return send_command_response(chat_id, "❌ Database not available")
            
            # Get all watchlist items
            coins = db.query(WatchlistItem).filter(
                WatchlistItem.symbol.isnot(None)
            ).order_by(WatchlistItem.symbol).limit(20).all()
            
            if not coins:
                return send_command_response(chat_id, "❌ No coins in watchlist")
            
            # Create inline keyboard with coin buttons
            buttons = []
            row = []
            for i, coin in enumerate(coins):
                # Add button to current row
                row.append({
                    "text": coin.symbol,
                    "callback_data": f"analyze_{coin.symbol}"
                })
                
                # Create new row after 2 buttons
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            
            # Add remaining buttons
            if row:
                buttons.append(row)
            
            message = f"""📊 *Select coin to analyze*

Choose a coin from your watchlist ({len(coins)} coins):"""
            
            # Send message with inline keyboard
            reply_markup = {"inline_keyboard": buttons}
            
            try:
                import requests
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                    "reply_markup": reply_markup
                }
                response = requests.post(url, json=payload, timeout=10)
                response.raise_for_status()
                logger.info(f"[TG][CMD] /analyze (menu sent with {len(coins)} coins)")
                return True
            except Exception as e:
                logger.error(f"[TG][ERROR] Failed to send analyze menu: {e}", exc_info=True)
                # Fallback to text list
                coin_list = "\n".join([f"• {c.symbol}" for c in coins[:10]])
                return send_command_response(chat_id, f"Available coins in watchlist:\n{coin_list}\n\nUsage: /analyze <symbol>\nExample: /analyze BTC_USDT")
        
        symbol = parts[1].upper()
        if "_" not in symbol:
            # Try to add _USDT if not present
            symbol = f"{symbol}_USDT"
        
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Find coin in database
        coin = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol
        ).first()
        
        if not coin:
            return send_command_response(chat_id, f"⚠️ Coin {symbol} not found in watchlist.\n\nUse /watchlist to see available coins.")
        
        # Build analysis message
        last_price = coin.price or 0
        buy_target = coin.buy_target or "N/A"
        res_up = coin.res_up or "N/A"
        res_down = coin.res_down or "N/A"
        rsi = coin.rsi or "N/A"
        
        # Determine status from order_status field
        status = coin.order_status or "PENDING"
        
        # Additional status indicators
        trade_status = "✅ Trade: YES" if coin.trade_enabled else "❌ Trade: NO"
        alert_status = "🔔 Alert: YES" if coin.alert_enabled else "❌ Alert: NO"
        margin_status = "✅ Margin: YES" if coin.trade_on_margin else "❌ Margin: NO"
        
        # Format prices
        if isinstance(last_price, (int, float)):
            if last_price >= 100:
                price_str = f"${last_price:,.2f}"
            else:
                price_str = f"${last_price:,.4f}"
        else:
            price_str = "N/A"
        
        if isinstance(buy_target, (int, float)):
            if buy_target >= 100:
                target_str = f"${buy_target:,.2f}"
            else:
                target_str = f"${buy_target:,.4f}"
        else:
            target_str = "N/A"
        
        if isinstance(res_up, (int, float)):
            if res_up >= 100:
                res_up_str = f"${res_up:,.2f}"
            else:
                res_up_str = f"${res_up:,.4f}"
        else:
            res_up_str = "N/A"
        
        if isinstance(res_down, (int, float)):
            if res_down >= 100:
                res_down_str = f"${res_down:,.2f}"
            else:
                res_down_str = f"${res_down:,.4f}"
        else:
            res_down_str = "N/A"
        
        # Add trade amount if available
        amount_info = ""
        if coin.trade_amount_usd:
            amount_info = f"\n• *Trade Amount:* ${coin.trade_amount_usd:,.2f}"
        
        # Check if coin has any market data
        has_data = (last_price and last_price > 0) or rsi != "N/A"
        data_warning = ""
        if not has_data:
            data_warning = "\n\n⚠️ _No market data available yet. Data will be updated by background services._"
        
        message = f"""📊 *Analysis: {symbol}*

{trade_status}
{alert_status}
{margin_status}

• *Last Price:* {price_str}
• *Buy Target:* {target_str}
• *Resistance Up:* {res_up_str}
• *Resistance Down:* {res_down_str}
• *RSI:* {rsi}{amount_info}
• *Status:* {status}{data_warning}"""
        
        logger.info(f"[TG][CMD] /analyze {symbol}")
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build analysis: {e}")
        return send_command_response(chat_id, f"❌ Error building analysis: {str(e)}")


def handle_create_sl_tp_command(chat_id: str, text: str, db: Session = None) -> bool:
    """Handle /create_sl_tp command"""
    try:
        from app.services.sl_tp_checker import sl_tp_checker_service
        
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        parts = text.split()
        
        if len(parts) > 1:
            # Create SL/TP for specific symbol
            symbol = parts[1].upper()
            if "_" not in symbol:
                symbol = f"{symbol}_USDT"
            
            result = sl_tp_checker_service.create_sl_tp_for_position(db, symbol)
            
            if result.get('success'):
                message = f"✅ <b>SL/TP CREATED</b>\n\n"
                message += f"📊 Symbol: <b>{symbol}</b>\n"
                if result.get('sl_order_id'):
                    message += f"🛑 SL Order ID: {result['sl_order_id']}\n"
                if result.get('tp_order_id'):
                    message += f"🚀 TP Order ID: {result['tp_order_id']}\n"
                if result.get('dry_run'):
                    message += f"\n🧪 Mode: DRY RUN"
                
                if result.get('sl_error'):
                    message += f"\n⚠️ SL Error: {result['sl_error']}"
                if result.get('tp_error'):
                    message += f"\n⚠️ TP Error: {result['tp_error']}"
            else:
                message = f"❌ <b>ERROR CREATING SL/TP</b>\n\n"
                message += f"📊 Symbol: <b>{symbol}</b>\n"
                message += f"💡 Error: {result.get('error', 'Unknown error')}"
        else:
            # Create SL/TP for all positions missing them
            check_result = sl_tp_checker_service.check_positions_for_sl_tp(db)
            positions_missing = check_result.get('positions_missing_sl_tp', [])
            
            if not positions_missing:
                message = "✅ All positions have SL/TP configured."
            else:
                created_count = 0
                errors = []
                
                for pos in positions_missing:
                    symbol = pos['symbol']
                    result = sl_tp_checker_service.create_sl_tp_for_position(db, symbol, force=True)
                    if result.get('success'):
                        created_count += 1
                    else:
                        errors.append(f"{symbol}: {result.get('error', 'Unknown error')}")
                
                message = f"✅ <b>SL/TP CREATED</b>\n\n"
                message += f"📊 Positions processed: {len(positions_missing)}\n"
                message += f"✅ Created: {created_count}\n"
                
                if errors:
                    message += f"\n❌ Errors:\n"
                    for error in errors[:5]:  # Limit to 5 errors
                        message += f"  • {error}\n"
        
        logger.info(f"[TG][CMD] /create_sl_tp {text}")
        return send_command_response(chat_id, message)
        
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to create SL/TP: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error creating SL/TP: {str(e)}")


def handle_create_sl_command(chat_id: str, text: str, db: Session = None) -> bool:
    """Handle /create_sl command - create only SL order"""
    try:
        from app.services.sl_tp_checker import sl_tp_checker_service
        
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        parts = text.split()
        
        if len(parts) < 2:
            return send_command_response(chat_id, "❌ Usage: /create_sl <symbol>\nExample: /create_sl ETH_USDT")
        
        symbol = parts[1].upper()
        if "_" not in symbol:
            symbol = f"{symbol}_USDT"
        
        result = sl_tp_checker_service.create_sl_for_position(db, symbol)
        
        if result.get('success'):
            message = f"✅ <b>SL CREATED</b>\n\n"
            message += f"📊 Symbol: <b>{symbol}</b>\n"
            if result.get('sl_order_id'):
                message += f"🛑 SL Order ID: {result['sl_order_id']}\n"
            if result.get('dry_run'):
                message += f"\n🧪 Mode: DRY RUN"
            
            if result.get('sl_error'):
                message += f"\n⚠️ Error: {result['sl_error']}"
        else:
            message = f"❌ <b>ERROR CREATING SL</b>\n\n"
            message += f"📊 Symbol: <b>{symbol}</b>\n"
            # Prioritize main error, then sl_error, then fallback
            error_msg = result.get('error') or result.get('sl_error') or 'Unknown error'
            message += f"💡 Error: {error_msg}"
        
        logger.info(f"[TG][CMD] /create_sl {symbol}")
        return send_command_response(chat_id, message)
        
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to create SL: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error creating SL: {str(e)}")


def handle_create_tp_command(chat_id: str, text: str, db: Session = None) -> bool:
    """Handle /create_tp command - create only TP order"""
    try:
        from app.services.sl_tp_checker import sl_tp_checker_service
        
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        parts = text.split()
        
        if len(parts) < 2:
            return send_command_response(chat_id, "❌ Usage: /create_tp <symbol>\nExample: /create_tp ETH_USDT")
        
        symbol = parts[1].upper()
        if "_" not in symbol:
            symbol = f"{symbol}_USDT"
        
        result = sl_tp_checker_service.create_tp_for_position(db, symbol)
        
        if result.get('success'):
            message = f"✅ <b>TP CREATED</b>\n\n"
            message += f"📊 Symbol: <b>{symbol}</b>\n"
            if result.get('tp_order_id'):
                message += f"🚀 TP Order ID: {result['tp_order_id']}\n"
            if result.get('dry_run'):
                message += f"\n🧪 Mode: DRY RUN"
            
            if result.get('tp_error'):
                message += f"\n⚠️ Error: {result['tp_error']}"
        else:
            message = f"❌ <b>ERROR CREATING TP</b>\n\n"
            message += f"📊 Symbol: <b>{symbol}</b>\n"
            # Prioritize main error, then tp_error, then fallback
            error_msg = result.get('error') or result.get('tp_error') or 'Unknown error'
            message += f"💡 Error: {error_msg}"
        
        logger.info(f"[TG][CMD] /create_tp {symbol}")
        return send_command_response(chat_id, message)
        
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to create TP: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error creating TP: {str(e)}")


def handle_add_coin_command(chat_id: str, text: str, db: Session = None) -> bool:
    """Handle /add command - add a coin to the watchlist"""
    try:
        # Parse symbol from command
        parts = text.split()
        if len(parts) < 2:
            return send_command_response(chat_id, "❌ Usage: /add <symbol>\nExample: /add BTC_USDT")
        
        symbol = parts[1].upper()
        
        # Validate symbol format
        if "_" not in symbol:
            # Try to add _USDT if not present
            symbol = f"{symbol}_USDT"
        
        # Split symbol into base and quote currency
        try:
            base_currency, quote_currency = symbol.split("_", 1)
            if not base_currency or not quote_currency:
                return send_command_response(chat_id, f"❌ Invalid symbol format: {symbol}\nUse format: BASE_QUOTE (e.g., BTC_USDT)")
        except ValueError:
            return send_command_response(chat_id, f"❌ Invalid symbol format: {symbol}\nUse format: BASE_QUOTE (e.g., BTC_USDT)")
        
        # Add to custom top coins database
        try:
            import sqlite3
            from app.api.routes_market import _get_db_connection, _ensure_custom_table, _upsert_custom_coin
            
            conn = _get_db_connection()
            try:
                _ensure_custom_table(conn)
                _upsert_custom_coin(conn, symbol, base_currency, quote_currency)
                logger.info(f"[TG] Added custom coin: {symbol}")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"[TG][ERROR] Failed to add to custom top coins: {e}")
            # Continue anyway - might still add to watchlist
        
        # Add to watchlist if database is available
        if db:
            try:
                # Check if coin already exists in watchlist
                existing = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
                
                if existing:
                    message = f"✅ <b>COIN ALREADY IN WATCHLIST</b>\n\n"
                    message += f"📊 Symbol: <b>{symbol}</b>\n"
                    message += f"💡 Coin is already in your watchlist."
                else:
                    # Create new watchlist item
                    watchlist_item = WatchlistItem(
                        symbol=symbol,
                        exchange="CRYPTO_COM",
                        alert_enabled=False,
                        trade_enabled=False,
                        trade_amount_usd=None,
                        trade_on_margin=False,
                        sl_tp_mode="conservative"
                    )
                    db.add(watchlist_item)
                    db.commit()
                    db.refresh(watchlist_item)
                    
                    message = f"✅ <b>COIN ADDED</b>\n\n"
                    message += f"📊 Symbol: <b>{symbol}</b>\n"
                    message += f"💡 Coin has been added to your watchlist.\n"
                    message += f"💡 Use /watchlist to see all coins."
                    
                    logger.info(f"[TG] Added coin to watchlist: {symbol}")
            except Exception as e:
                logger.error(f"[TG][ERROR] Failed to add to watchlist: {e}", exc_info=True)
                message = f"✅ <b>COIN ADDED TO TOP COINS</b>\n\n"
                message += f"📊 Symbol: <b>{symbol}</b>\n"
                message += f"⚠️ Added to custom top coins, but failed to add to watchlist: {str(e)}"
        else:
            message = f"✅ <b>COIN ADDED TO TOP COINS</b>\n\n"
            message += f"📊 Symbol: <b>{symbol}</b>\n"
            message += f"💡 Coin has been added to custom top coins.\n"
            message += f"⚠️ Database not available for watchlist."
        
        logger.info(f"[TG][CMD] /add {symbol}")
        return send_command_response(chat_id, message)
        
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to add coin: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error adding coin: {str(e)}")


def handle_skip_sl_tp_reminder_command(chat_id: str, text: str, db: Session = None) -> bool:
    """Handle /skip_sl_tp_reminder command"""
    try:
        from app.services.sl_tp_checker import sl_tp_checker_service
        
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        parts = text.split()
        
        if len(parts) > 1:
            # Skip reminder for specific symbol
            symbol = parts[1].upper()
            if "_" not in symbol:
                symbol = f"{symbol}_USDT"
            
            success = sl_tp_checker_service.skip_reminder_for_symbol(db, symbol)
            
            if success:
                message = f"✅ <b>REMINDER DISABLED</b>\n\n"
                message += f"📊 Symbol: <b>{symbol}</b>\n"
                message += f"💡 No more SL/TP reminders will be sent for this position."
            else:
                message = f"❌ Error disabling reminder for {symbol}"
        else:
            # Skip reminder for all positions currently missing SL/TP
            check_result = sl_tp_checker_service.check_positions_for_sl_tp(db)
            positions_missing = check_result.get('positions_missing_sl_tp', [])
            
            if not positions_missing:
                message = "✅ All positions already have SL/TP or reminders disabled."
            else:
                skipped_count = 0
                
                for pos in positions_missing:
                    symbol = pos['symbol']
                    if sl_tp_checker_service.skip_reminder_for_symbol(db, symbol):
                        skipped_count += 1
                
                message = f"✅ <b>REMINDERS DISABLED</b>\n\n"
                message += f"📊 Positions: {skipped_count}/{len(positions_missing)}\n"
                message += f"💡 No more SL/TP reminders will be sent for these positions."
        
        logger.info(f"[TG][CMD] /skip_sl_tp_reminder {text}")
        return send_command_response(chat_id, message)
        
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to skip reminder: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error skipping reminder: {str(e)}")


def handle_telegram_update(update: Dict, db: Session = None) -> None:
    """Handle a single Telegram update (messages and callback queries)"""
    global PROCESSED_TEXT_COMMANDS, PROCESSED_CALLBACK_DATA, PROCESSED_CALLBACK_IDS
    update_id = update.get("update_id", 0)
    logger.info(f"[TG][HANDLER] handle_telegram_update called for update_id={update_id}")
    
    # DEDUPLICATION LEVEL 0: Check if this update_id was already processed
    # Use database for cross-instance deduplication (works between local and AWS)
    # CRITICAL: This prevents the same update from being processed by both local and AWS instances
    if db and update_id > 0:
        try:
            from app.models.telegram_message import TelegramMessage
            update_marker = f"UPDATE_{update_id}"
            
            # Check if this update was already processed by another instance
            existing = db.query(TelegramMessage).filter(
                TelegramMessage.symbol == update_marker,
                TelegramMessage.message == "update_deduplication"
            ).first()
            
            if existing:
                logger.debug(f"[TG] Skipping duplicate update_id={update_id} (already processed by another instance)")
                return
            
            # Mark as processed in database - this instance will process it
            # Use symbol field to store update_id marker
            processed_marker = TelegramMessage(
                symbol=update_marker,
                message="update_deduplication",
                blocked=False,
                order_skipped=False
            )
            db.add(processed_marker)
            db.commit()
            
            # CRITICAL: Double-check after commit to handle race conditions
            # If another instance inserted between our check and commit, we should skip
            db.refresh(processed_marker)
            # Verify we're the first by checking if there are multiple entries
            # (should only be 1 if we were first)
            count = db.query(TelegramMessage).filter(
                TelegramMessage.symbol == update_marker,
                TelegramMessage.message == "update_deduplication"
            ).count()
            
            if count > 1:
                # Another instance also inserted - we're not the first, skip processing
                logger.debug(f"[TG] Skipping duplicate update_id={update_id} (race condition detected, {count} instances processed)")
                return
            
            logger.debug(f"[TG] Marked update_id={update_id} as processed in DB (this instance will process)")
            
            # Clean up old markers periodically (keep only last 1000)
            # Only do this occasionally to avoid overhead
            import random
            if random.random() < 0.1:  # 10% chance to cleanup
                try:
                    old_markers = db.query(TelegramMessage).filter(
                        TelegramMessage.message == "update_deduplication"
                    ).order_by(TelegramMessage.id.desc()).offset(1000).all()
                    for marker in old_markers:
                        db.delete(marker)
                    db.commit()
                except Exception as cleanup_err:
                    logger.debug(f"[TG] Cleanup of old update markers failed: {cleanup_err}")
                    db.rollback()
        except Exception as db_err:
            # If database check fails, fall back to in-memory deduplication
            logger.debug(f"[TG] Database deduplication failed, using in-memory: {db_err}")
            if not hasattr(handle_telegram_update, 'processed_update_ids'):
                handle_telegram_update.processed_update_ids = set()
            
            if update_id in handle_telegram_update.processed_update_ids:
                logger.debug(f"[TG] Skipping duplicate update_id={update_id} (in-memory)")
                return
            
            handle_telegram_update.processed_update_ids.add(update_id)
            if len(handle_telegram_update.processed_update_ids) > 1000:
                handle_telegram_update.processed_update_ids = set(list(handle_telegram_update.processed_update_ids)[-500:])
    else:
        # No database available, use in-memory deduplication
        if not hasattr(handle_telegram_update, 'processed_update_ids'):
            handle_telegram_update.processed_update_ids = set()
        
        if update_id in handle_telegram_update.processed_update_ids:
            logger.debug(f"[TG] Skipping duplicate update_id={update_id} (in-memory, no DB)")
            return
        
        handle_telegram_update.processed_update_ids.add(update_id)
        if len(handle_telegram_update.processed_update_ids) > 1000:
            handle_telegram_update.processed_update_ids = set(list(handle_telegram_update.processed_update_ids)[-500:])
    
    # Handle callback_query (button clicks)
    callback_query = update.get("callback_query")
    if callback_query:
        callback_query_id = callback_query.get("id")
        callback_data = callback_query.get("data", "")
        
        # DEDUPLICATION LEVEL 1: Check if this callback_query_id was already processed
        # This prevents duplicate processing when multiple workers handle the same update
        if callback_query_id and callback_query_id in PROCESSED_CALLBACK_IDS:
            logger.debug(f"[TG] Skipping duplicate callback_query_id={callback_query_id}")
            return
        
        # DEDUPLICATION LEVEL 2: Check if this callback_data was recently processed
        # This prevents the same action from being processed multiple times across different chats
        # (e.g., when both hilovivo-alerts and hilovivo-alerts-local receive the same callback)
        if callback_data and callback_data != "noop":
            now = time.time()
            if callback_data in PROCESSED_CALLBACK_DATA:
                last_processed = PROCESSED_CALLBACK_DATA[callback_data]
                if now - last_processed < CALLBACK_DATA_TTL:
                    logger.debug(f"[TG] Skipping duplicate callback_data={callback_data} (processed {now - last_processed:.2f}s ago)")
                    # Still answer the callback to remove loading state
                    if callback_query_id:
                        try:
                            url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                            requests.post(url, json={"callback_query_id": callback_query_id}, timeout=5)
                        except:
                            pass
                    return
            # Mark this callback_data as processed
            PROCESSED_CALLBACK_DATA[callback_data] = now
            # Clean up old entries (keep only last 1000)
            if len(PROCESSED_CALLBACK_DATA) > 1000:
                cutoff_time = now - CALLBACK_DATA_TTL
                # Use dict comprehension but assign to a temporary variable first, then update
                filtered = {k: v for k, v in PROCESSED_CALLBACK_DATA.items() if v > cutoff_time}
                PROCESSED_CALLBACK_DATA.clear()
                PROCESSED_CALLBACK_DATA.update(filtered)
        
        from_user = callback_query.get("from", {})
        message = callback_query.get("message", {})
        chat = message.get("chat", {})
        # Get chat ID from the message (group/channel), not from the user who clicked
        chat_id = str(chat.get("id", ""))
        user_id = str(from_user.get("id", ""))
        message_id = message.get("message_id")
        logger.info(f"[TG][CALLBACK] Processing callback_data='{callback_data}' from chat_id={chat_id}, user_id={user_id}, message_id={message_id}")
        # callback_data was already extracted above for deduplication
        message_id = message.get("message_id")
        
        # Only authorized chat (group/channel) or user
        # For groups, check the chat ID; for private chats, check user ID
        is_authorized = (chat_id == AUTH_CHAT_ID) or (user_id == AUTH_CHAT_ID)
        if not is_authorized:
            logger.warning(f"[TG][DENY] callback_query from chat_id={chat_id}, user_id={user_id}, AUTH_CHAT_ID={AUTH_CHAT_ID}")
            return
        
        # Mark this callback as processed BEFORE processing to prevent race conditions
        if callback_query_id:
            PROCESSED_CALLBACK_IDS.add(callback_query_id)
            # Clean up old callback IDs (keep only last 1000 to prevent memory leak)
            if len(PROCESSED_CALLBACK_IDS) > 1000:
                # Remove oldest 500 entries (simple cleanup)
                old_ids = list(PROCESSED_CALLBACK_IDS)[:500]
                PROCESSED_CALLBACK_IDS.difference_update(old_ids)
            
            # Answer callback query to remove loading state
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                requests.post(url, json={"callback_query_id": callback_query_id}, timeout=5)
            except:
                pass
        
        # Process callback data
        logger.info(f"[TG] Processing callback_query: {callback_data} from chat_id={chat_id}")
        
        if callback_data == "noop":
            return
        elif callback_data == "menu:watchlist":
            show_watchlist_menu(chat_id, db, page=1, message_id=message_id)
        elif callback_data == "menu:signal_config":
            show_signal_config_menu(chat_id, message_id=message_id)
        elif callback_data.startswith("watchlist:page:"):
            try:
                page = int(callback_data.split(":")[-1])
            except ValueError:
                page = 1
            show_watchlist_menu(chat_id, db, page=page, message_id=message_id)
        elif callback_data == "watchlist:add":
            _prompt_value_input(
                chat_id,
                "➕ <b>Agregar símbolo</b>\n\nFormato: BASE_QUOTE (ej. BTC_USDT)",
                symbol=None,
                field=None,
                action="add_symbol",
                value_type="symbol",
                allow_clear=False,
            )
        elif callback_data == "input:cancel":
            if PENDING_VALUE_INPUTS.pop(chat_id, None):
                send_command_response(chat_id, "❌ Entrada cancelada.")
            return
        elif callback_data.startswith("wl:coin:"):
            parts = callback_data.split(":")
            if len(parts) < 3:
                return
            symbol = parts[2]
            if len(parts) == 3:
                show_coin_menu(chat_id, symbol, db, message_id=message_id)
                return
            action = parts[3]
            if action == "toggle" and len(parts) >= 5:
                field_key = parts[4]
                toggle_map = {
                    "alert": "alert_enabled",
                    "buy_alert": "buy_alert_enabled",
                    "sell_alert": "sell_alert_enabled",
                    "trade": "trade_enabled",
                    "margin": "trade_on_margin",
                    "risk": "sl_tp_mode",
                }
                target_field = toggle_map.get(field_key)
                if target_field:
                    _handle_watchlist_toggle(chat_id, symbol, target_field, db, message_id)
            elif action == "set" and len(parts) >= 5:
                field_key = parts[4]
                if field_key == "amount":
                    _prompt_value_input(
                        chat_id,
                        f"💵 <b>{symbol}</b>\nIngresa Amount USD.",
                        symbol=symbol,
                        field="trade_amount_usd",
                        action="update_field",
                        value_type="float",
                        min_value=0.0,
                    )
                elif field_key == "min_pct":
                    _prompt_value_input(
                        chat_id,
                        f"📊 <b>{symbol}</b>\nNuevo porcentaje mínimo (ej. 1.5).",
                        symbol=symbol,
                        field="min_price_change_pct",
                        action="update_field",
                        value_type="float",
                        min_value=0.1,
                    )
                elif field_key == "sl_pct":
                    _prompt_value_input(
                        chat_id,
                        f"📉 <b>{symbol}</b>\nIngresa SL% (ej. 5).",
                        symbol=symbol,
                        field="sl_percentage",
                        action="update_field",
                        value_type="float",
                        min_value=0.1,
                    )
                elif field_key == "tp_pct":
                    _prompt_value_input(
                        chat_id,
                        f"📈 <b>{symbol}</b>\nIngresa TP% (ej. 10).",
                        symbol=symbol,
                        field="tp_percentage",
                        action="update_field",
                        value_type="float",
                        min_value=0.1,
                    )
                elif field_key == "notes":
                    _prompt_value_input(
                        chat_id,
                        f"📝 <b>{symbol}</b>\nEscribe nuevas notas.",
                        symbol=symbol,
                        field="notes",
                        action="set_notes",
                        value_type="string",
                    )
                elif field_key == "cooldown":
                    _prompt_value_input(
                        chat_id,
                        f"⏱ <b>{symbol}</b>\nIngresa el cooldown en minutos (ej. 5).",
                        symbol=symbol,
                        field="alert_cooldown_minutes",
                        action="update_field",
                        value_type="float",
                        min_value=0.0,
                    )
            elif action == "preset":
                if len(parts) >= 6 and parts[4] == "set":
                    preset_value = parts[5]
                    _apply_preset_change(chat_id, symbol, preset_value)
                    show_coin_menu(chat_id, symbol, db, message_id=message_id)
                else:
                    _show_preset_selection_menu(chat_id, symbol)
            elif action == "delete":
                try:
                    _delete_watchlist_symbol(db, symbol)
                    send_command_response(chat_id, f"🗑️ {symbol} eliminado.")
                    show_watchlist_menu(chat_id, db, page=1)
                except Exception as err:
                    logger.error(f"[TG][ERROR] delete {symbol}: {err}", exc_info=True)
                    send_command_response(chat_id, f"❌ Error eliminando {symbol}: {err}")
            elif action == "test":
                _trigger_watchlist_test(chat_id, symbol, db)
            return
        elif callback_data.startswith("analyze_"):
            symbol = callback_data.replace("analyze_", "")
            send_analyze_message(chat_id, f"/analyze {symbol}", db)
        elif callback_data.startswith("create_sl_tp_"):
            symbol = callback_data.replace("create_sl_tp_", "")
            handle_create_sl_tp_command(chat_id, f"/create_sl_tp {symbol}", db)
        elif callback_data.startswith("create_sl_"):
            symbol = callback_data.replace("create_sl_", "")
            handle_create_sl_command(chat_id, f"/create_sl {symbol}", db)
        elif callback_data.startswith("create_tp_"):
            symbol = callback_data.replace("create_tp_", "")
            handle_create_tp_command(chat_id, f"/create_tp {symbol}", db)
        elif callback_data.startswith("skip_sl_tp_"):
            symbol = callback_data.replace("skip_sl_tp_", "")
            handle_skip_sl_tp_reminder_command(chat_id, f"/skip_sl_tp_reminder {symbol}", db)
        elif callback_data == "menu:main":
            # Show main menu
            show_main_menu(chat_id, db)
        elif callback_data.startswith("cmd:"):
            # Handle command shortcuts from menu
            cmd = callback_data.replace("cmd:", "")
            if cmd == "status":
                send_status_message(chat_id, db)
            elif cmd == "portfolio":
                send_portfolio_message(chat_id, db)
            elif cmd == "signals":
                send_signals_message(chat_id, db)
            elif cmd == "balance":
                send_balance_message(chat_id)
            elif cmd == "watchlist":
                send_watchlist_message(chat_id, db)
            elif cmd == "open_orders":
                send_open_orders_message(chat_id, db)
            elif cmd == "expected_tp":
                send_expected_take_profit_message(chat_id, db)
            elif cmd == "executed_orders":
                send_executed_orders_message(chat_id, db)
            elif cmd == "version":
                send_version_message(chat_id)
            elif cmd == "alerts":
                send_alerts_list_message(chat_id, db)
            elif cmd == "help":
                send_help_message(chat_id)
        elif callback_data == "menu:portfolio":
            # Show portfolio sub-menu
            logger.info(f"[TG][MENU] Portfolio menu requested from chat_id={chat_id}, message_id={message_id}")
            result = show_portfolio_menu(chat_id, db, message_id)
            logger.info(f"[TG][MENU] Portfolio menu result: {result}")
        elif callback_data == "menu:open_orders":
            # Show open orders sub-menu
            show_open_orders_menu(chat_id, db, message_id)
        elif callback_data == "menu:expected_tp":
            # Show expected take profit sub-menu
            show_expected_tp_menu(chat_id, db, message_id)
        elif callback_data == "menu:executed_orders":
            # Show executed orders sub-menu
            show_executed_orders_menu(chat_id, db, message_id)
        elif callback_data == "menu:monitoring":
            # Show monitoring sub-menu
            show_monitoring_menu(chat_id, db, message_id)
        elif callback_data.startswith("monitoring:"):
            # Handle monitoring sub-sections
            section = callback_data.replace("monitoring:", "")
            if section == "system":
                send_system_monitoring_message(chat_id, db, message_id)
            elif section == "throttle":
                send_throttle_message(chat_id, db, message_id)
            elif section == "workflows":
                send_workflows_monitoring_message(chat_id, db, message_id)
            elif section == "blocked":
                send_blocked_messages_message(chat_id, db, message_id)
        elif callback_data.startswith("setting:"):
            # Handle settings menu callbacks (e.g., setting:min_price_change_pct:select_strategy)
            _handle_setting_callback(chat_id, callback_data, callback_query.get("message", {}).get("message_id"), db)
        elif callback_data.startswith("signal:"):
            _handle_signal_config_callback(chat_id, callback_data, message_id)
        else:
            logger.warning(f"[TG] Unknown callback_data: {callback_data}")
            send_command_response(chat_id, f"❓ Unknown command: {callback_data}")
        
        return
    
    # Handle regular message
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    
    chat_id = str(message["chat"]["id"])
    text = message.get("text", "")
    from_user = message.get("from", {})
    user_id = str(from_user.get("id", "")) if from_user else ""
    
    # Only authorized user - check both chat_id (for private chats) and user_id (for groups)
    # In groups, chat_id is the group ID, so we need to check user_id
    # Ensure AUTH_CHAT_ID is also a string for comparison
    auth_chat_id_str = str(AUTH_CHAT_ID) if AUTH_CHAT_ID else ""
    is_authorized = (chat_id == auth_chat_id_str) or (user_id == auth_chat_id_str)
    if not is_authorized:
        logger.warning(f"[TG][DENY] chat_id={chat_id}, user_id={user_id}, AUTH_CHAT_ID={AUTH_CHAT_ID} (str: {auth_chat_id_str}), command={text[:50]}")
        send_command_response(chat_id, "⛔ Not authorized")
        return
    else:
        logger.info(f"[TG][AUTH] ✅ Authorized chat_id={chat_id}, user_id={user_id}, AUTH_CHAT_ID={AUTH_CHAT_ID} for command={text[:50]}")
    
    # Parse command
    text = text.strip()
    
    # Handle commands with @botname in groups (e.g., "/start@Hilovivolocal_bot")
    # Strip the @botname part to get the actual command
    if "@" in text and text.startswith("/"):
        # Extract command part before @
        text = text.split("@")[0].strip()
        logger.debug(f"[TG] Stripped @botname from command, new text: {text}")
    
    # DEDUPLICATION: Prevent duplicate text commands when multiple instances (local/AWS) process same command
    # Use update_id for most reliable deduplication (already checked above, but add command-level check as backup)
    # This prevents the same /start command from being processed by both local and AWS instances
    if text and text.startswith("/"):
        # Primary deduplication: update_id (already handled above)
        # Secondary deduplication: command + chat_id + timestamp (backup for edge cases)
        command_key = f"{chat_id}:{text}"
        now = time.time()
        if command_key in PROCESSED_TEXT_COMMANDS:
            last_processed = PROCESSED_TEXT_COMMANDS[command_key]
            if now - last_processed < TEXT_COMMAND_TTL:
                logger.debug(f"[TG] Skipping duplicate text command {text} for chat {chat_id} (processed {now - last_processed:.2f}s ago)")
                return
        # Mark this command as processed
        PROCESSED_TEXT_COMMANDS[command_key] = now
        # Clean up old entries (keep only last 500)
        if len(PROCESSED_TEXT_COMMANDS) > 500:
            cutoff_time = now - TEXT_COMMAND_TTL
            PROCESSED_TEXT_COMMANDS = {k: v for k, v in PROCESSED_TEXT_COMMANDS.items() if v > cutoff_time}

    # If waiting for a manual input, process it first
    if PENDING_VALUE_INPUTS.get(chat_id) and db:
        if _handle_pending_value_message(chat_id, text, db):
            return
    
    # Handle custom keyboard button presses
    if text == "🚀 Start" or text == "Start":
        text = "/start"
    elif text == "📊 Status" or text == "Status":
        text = "/status"
    elif text == "💰 Portfolio" or text == "Portfolio":
        text = "/portfolio"
    elif text == "📈 Signals" or text == "Signals":
        text = "/signals"
    elif text == "📋 Watchlist" or text == "Watchlist":
        text = "/watchlist"
    elif text == "⚙️ Menu" or text == "Menu":
        text = "/menu"
    elif text == "❓ Help" or text == "Help":
        text = "/help"
    
    # Check if user is entering a value for a pending strategy setting
    # Try to parse as number - if successful, check if there's a pending strategy selection
    try:
        value = float(text)
        # Check if this chat has a pending strategy selection (stored in a simple dict)
        # For now, we'll use a simple approach: if it's a number and not a command, 
        # we'll need to track pending selections. For simplicity, we'll require using buttons.
        # But we can add a note in the prompt that manual entry is supported via buttons only.
    except ValueError:
        pass  # Not a number, continue with normal command parsing
    
    if text.startswith("/start"):
        logger.info(f"[TG][CMD] Processing /start command from chat_id={chat_id}")
        try:
            # Show main menu with inline buttons (single message, no duplication)
            logger.info(f"[TG][CMD][START] Showing main menu to chat_id={chat_id}")
            menu_result = show_main_menu(chat_id, db)
            logger.info(f"[TG][CMD][START] Main menu result: {menu_result}")
            
            if menu_result:
                logger.info(f"[TG][CMD][START] ✅ /start command processed successfully for chat_id={chat_id}")
            else:
                logger.error(f"[TG][CMD][START] ❌ Failed to send main menu to chat_id={chat_id}")
        except Exception as e:
            logger.error(f"[TG][ERROR][START] ❌ Error processing /start command: {e}", exc_info=True)
    elif text.startswith("/menu"):
        show_main_menu(chat_id, db)
    elif text.startswith("/help"):
        send_help_message(chat_id)
    elif text.startswith("/status"):
        send_status_message(chat_id, db)
    elif text.startswith("/portfolio"):
        send_portfolio_message(chat_id, db)
    elif text.startswith("/signals"):
        send_signals_message(chat_id, db)
    elif text.startswith("/balance"):
        send_balance_message(chat_id)
    elif text.startswith("/watchlist"):
        send_watchlist_message(chat_id, db)
    elif text.startswith("/alerts"):
        send_alerts_list_message(chat_id, db)
    elif text.startswith("/analyze"):
        send_analyze_message(chat_id, text, db)
    elif text.startswith("/add"):
        handle_add_coin_command(chat_id, text, db)
    elif text.startswith("/create_sl_tp"):
        handle_create_sl_tp_command(chat_id, text, db)
    elif text.startswith("/create_sl"):
        logger.info(f"[TG][CMD] Processing /create_sl command: {text}")
        handle_create_sl_command(chat_id, text, db)
    elif text.startswith("/create_tp"):
        logger.info(f"[TG][CMD] Processing /create_tp command: {text}")
        handle_create_tp_command(chat_id, text, db)
    elif text.startswith("/skip_sl_tp_reminder"):
        handle_skip_sl_tp_reminder_command(chat_id, text, db)
    elif text.startswith("/"):
        send_command_response(chat_id, "❓ Unknown command. Use /help")


def process_telegram_commands(db: Session = None) -> None:
    """Process pending Telegram commands using long polling for real-time processing"""
    global LAST_UPDATE_ID, _NO_UPDATE_COUNT
    
    # CRITICAL: Only process Telegram commands on AWS, not on local
    # This prevents duplicate processing when both local and AWS instances are running
    app_env = (os.getenv("APP_ENV") or "").strip().lower()
    if app_env != "aws":
        # Skip processing on local to avoid duplicate messages
        logger.debug(f"[TG] Skipping Telegram command processing on local (APP_ENV={app_env})")
        return
    
    # Ensure we have a DB session
    if not db:
        try:
            db = SessionLocal()
            db_created = True
        except Exception as e:
            logger.error(f"[TG] Cannot create DB session: {e}")
            return
    else:
        db_created = False
    
    try:
        # CRITICAL: Acquire PostgreSQL advisory lock (single poller enforcement)
        # If lock cannot be acquired, another poller is active - skip this cycle
        if not _acquire_poller_lock(db):
            logger.debug("[TG] Another poller is active, skipping this cycle")
            return
        
        try:
            # Load LAST_UPDATE_ID from DB on first call or if not loaded
            if LAST_UPDATE_ID == 0:
                _load_last_update_id(db)
            
            logger.info(f"[TG] process_telegram_commands called, LAST_UPDATE_ID={LAST_UPDATE_ID}")
            
            # Normal polling: use offset = LAST_UPDATE_ID + 1
            offset = LAST_UPDATE_ID + 1 if LAST_UPDATE_ID > 0 else None
            logger.info(f"[TG] Calling get_telegram_updates with offset={offset} (LAST_UPDATE_ID={LAST_UPDATE_ID})")
            
            # Get updates (lock is already held)
            updates = get_telegram_updates(offset=offset, db=db)
            
            update_count = len(updates) if updates else 0
            logger.info(f"[TG] get_telegram_updates returned {update_count} updates")
            
            if not updates:
                # No updates received - increment counter
                _NO_UPDATE_COUNT += 1
                
                # After N consecutive cycles (10) with no updates, probe without offset
                if _NO_UPDATE_COUNT >= 10:
                    logger.warning(f"[TG] No updates for {_NO_UPDATE_COUNT} consecutive cycles, probing without offset...")
                    probe_updates = _probe_updates_without_offset()
                    
                    if probe_updates:
                        # Found updates older than LAST_UPDATE_ID - adjust offset
                        max_probe_id = max(u.get("update_id", 0) for u in probe_updates)
                        if max_probe_id > 0 and max_probe_id < LAST_UPDATE_ID:
                            new_last_id = max_probe_id - 1
                            logger.warning(f"[TG] Probe found updates older than LAST_UPDATE_ID. Adjusting from {LAST_UPDATE_ID} to {new_last_id}")
                            _save_last_update_id(db, new_last_id)
                            LAST_UPDATE_ID = new_last_id
                            # Retry with corrected offset
                            offset = LAST_UPDATE_ID + 1 if LAST_UPDATE_ID > 0 else None
                            updates = get_telegram_updates(offset=offset, db=db)
                            if updates:
                                _NO_UPDATE_COUNT = 0
                                logger.info(f"[TG] Probe recovery successful, received {len(updates)} updates")
                    
                    # Reset counter after probe
                    _NO_UPDATE_COUNT = 0
                
                if not updates:
                    logger.info(f"[TG] No updates received (normal with long polling timeout), LAST_UPDATE_ID={LAST_UPDATE_ID}, offset={offset}")
                    return
            
            # Reset counter when we receive updates
            _NO_UPDATE_COUNT = 0
            
            logger.info(f"[TG] ⚡ Received {len(updates)} update(s) - processing immediately")
            
            for update in updates:
                update_id = update.get("update_id", 0)
                message = update.get("message") or update.get("edited_message")
                callback_query = update.get("callback_query")
                my_chat_member = update.get("my_chat_member")
                
                if callback_query:
                    callback_data = callback_query.get("data", "")
                    from_user = callback_query.get("from", {})
                    chat_id = from_user.get("id", "")
                    logger.info(f"[TG] ⚡ Processing callback_query: '{callback_data}' from chat_id={chat_id}, update_id={update_id}")
                elif message:
                    text = message.get("text", "")
                    chat_id = message.get("chat", {}).get("id", "")
                    logger.info(f"[TG] ⚡ Processing command: '{text}' from chat_id={chat_id}, update_id={update_id}")
                elif my_chat_member:
                    # Handle bot being added/removed from groups
                    chat = my_chat_member.get("chat", {})
                    chat_id = str(chat.get("id", ""))
                    new_status = my_chat_member.get("new_chat_member", {}).get("status", "")
                    old_status = my_chat_member.get("old_chat_member", {}).get("status", "")
                    logger.info(f"[TG] ⚡ Processing my_chat_member: chat_id={chat_id}, status: {old_status} -> {new_status}, update_id={update_id}")
                    # If bot was added to group, send welcome message
                    if new_status == "member" or new_status == "administrator":
                        logger.info(f"[TG] Bot added to group {chat_id}, sending welcome message")
                        send_welcome_message(chat_id)
                    # Update ID to skip this update
                    _save_last_update_id(db, update_id)
                    LAST_UPDATE_ID = update_id
                    continue
                else:
                    logger.debug(f"[TG] Update {update_id} has no message, callback_query, or my_chat_member (might be other type)")
                    # Update ID anyway to skip this update
                    _save_last_update_id(db, update_id)
                    LAST_UPDATE_ID = update_id
                    continue
                
                # Process update immediately
                try:
                    logger.info(f"[TG] Calling handle_telegram_update for update_id={update_id}")
                    handle_telegram_update(update, db)
                    logger.info(f"[TG] Successfully processed update_id={update_id}")
                except Exception as handle_error:
                    logger.error(f"[TG] Error handling update {update_id}: {handle_error}", exc_info=True)
                
                # Update last processed ID in DB
                _save_last_update_id(db, update_id)
                LAST_UPDATE_ID = update_id
                logger.info(f"[TG] Updated LAST_UPDATE_ID to {LAST_UPDATE_ID}")
        
        finally:
            # Always release poller lock after processing cycle
            # CRITICAL: Release lock even if there was an error
            try:
                _release_poller_lock(db)
                logger.debug("[TG] Poller lock released in finally block")
            except Exception as release_err:
                logger.error(f"[TG] Error releasing poller lock: {release_err}")
            
    except Exception as e:
        logger.error(f"[TG] Error processing commands: {e}", exc_info=True)
        # Ensure lock is released on error
        _release_poller_lock(db)
    finally:
        if db_created and db:
            db.close()


def _handle_setting_callback(chat_id: str, callback_data: str, message_id: Optional[int], db: Session) -> None:
    """Handle trading settings callbacks for min_price_change_pct by strategy"""
    try:
        if not db:
            send_command_response(chat_id, "❌ Database not available.")
            return
        
        parts = callback_data.split(":")
        if len(parts) < 2:
            logger.warning(f"[TG] Invalid setting callback format: {callback_data}")
            return
        
        setting_key = parts[1]
        
        # For min_price_change_pct, handle strategy selection
        if setting_key == "min_price_change_pct":
            if len(parts) >= 3:
                action = parts[2]
                if action == "select_strategy":
                    _show_setting_strategy_selection(chat_id, setting_key, message_id, db)
                    return
                elif action.startswith("strategy:"):
                    strategy_key = action.replace("strategy:", "")
                    _show_setting_strategy_input_prompt(chat_id, setting_key, strategy_key, message_id, db)
                    return
                elif action.startswith("set_strategy:"):
                    if len(parts) >= 5:
                        strategy_key = parts[3]
                        value = parts[4]
                        _apply_setting_value_to_strategy(chat_id, setting_key, strategy_key, value, message_id, db)
                        return
            
            # Initial menu: show strategy selection
            _show_setting_strategy_selection(chat_id, setting_key, message_id, db)
        else:
            send_command_response(chat_id, f"❌ Setting '{setting_key}' not supported yet.")
    
    except Exception as e:
        logger.error(f"[TG][ERROR] Error handling setting callback {callback_data}: {e}", exc_info=True)
        send_command_response(chat_id, f"❌ Error processing setting: {str(e)}")


def _show_setting_strategy_selection(chat_id: str, setting_key: str, message_id: Optional[int], db: Session) -> None:
    """Show strategy selection menu for min_price_change_pct"""
    try:
        from app.services.config_loader import load_config
        from app.models.watchlist import WatchlistItem
        
        # Load trading config to get presets
        config = load_config()
        coins_config = config.get("coins", {})
        
        # Get all watchlist items to find risk modes
        items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False,
            WatchlistItem.symbol.isnot(None)
        ).all()
        
        # Build strategy list from coins
        strategy_set = set()
        for item in items:
            if not item.symbol:
                continue
            
            # Get preset from config or default to 'swing'
            coin_config = coins_config.get(item.symbol, {})
            preset = coin_config.get("preset", "swing")
            
            # Handle preset formats like "swing-conservative" or just "swing"
            if "-" in preset:
                # Already includes risk mode
                strategy_set.add(preset)
            else:
                # Get risk mode from watchlist item
                risk_mode = item.sl_tp_mode or "conservative"
                strategy_name = f"{preset}-{risk_mode}"
                strategy_set.add(strategy_name)
        
        # Convert to sorted list
        strategies = sorted(list(strategy_set))
        
        if not strategies:
            send_command_response(chat_id, "ℹ️ No strategies found. Add coins to watchlist first.")
            return
        
        # Build keyboard with strategy buttons (2 per row)
        rows: List[List[Dict[str, str]]] = []
        for i in range(0, len(strategies), 2):
            row = []
            for strategy in strategies[i:i+2]:
                # Get current value for this strategy
                current_value = _get_strategy_current_value(db, strategy, setting_key)
                display_text = strategy.replace("-", " ").title()
                if current_value and current_value != "N/A":
                    display_text += f" ({current_value})"
                row.append({
                    "text": display_text,
                    "callback_data": f"setting:{setting_key}:strategy:{strategy}"
                })
            rows.append(row)
        
        # Add back button
        rows.append([
            {"text": "🔙 Back", "callback_data": "menu:main"},
        ])
        
        text = f"📊 <b>Select Strategy - Min Price Change %</b>\n\nChoose a strategy to configure:"
        keyboard = _build_keyboard(rows)
        
        logger.info(f"[TG] Showing strategy selection menu with {len(strategies)} strategies")
        result = _send_menu_message(chat_id, text, keyboard)
        if not result:
            logger.error(f"[TG][ERROR] Failed to send strategy selection menu to {chat_id}")
            send_command_response(chat_id, "❌ Error showing strategy selection. Please try again.")
    
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing strategy selection: {e}", exc_info=True)
        send_command_response(chat_id, f"❌ Error: {str(e)}")


def _get_strategy_current_value(db: Session, strategy_key: str, setting_key: str) -> str:
    """Get current value display for a strategy"""
    try:
        from app.services.config_loader import load_config
        from app.models.watchlist import WatchlistItem
        
        config = load_config()
        coins_config = config.get("coins", {})
        
        # Parse strategy key (e.g., "swing-conservative" or "swing")
        if "-" in strategy_key:
            preset, risk_mode = strategy_key.split("-", 1)
        else:
            preset = strategy_key
            risk_mode = None
        
        # Find all coins using this strategy
        matching_items = []
        for item in db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False,
            WatchlistItem.symbol.isnot(None)
        ).all():
            coin_config = coins_config.get(item.symbol, {})
            coin_preset = coin_config.get("preset", "swing")
            
            # Handle preset formats
            if "-" in coin_preset:
                coin_preset_base, coin_risk = coin_preset.split("-", 1)
                if coin_preset_base == preset and coin_risk == risk_mode:
                    matching_items.append(item)
            else:
                coin_risk = item.sl_tp_mode or "conservative"
                if coin_preset == preset:
                    if risk_mode is None or coin_risk == risk_mode:
                        matching_items.append(item)
        
        if not matching_items:
            return "N/A"
        
        # Get the most common value (check if attribute exists)
        values = []
        for item in matching_items:
            if hasattr(item, 'min_price_change_pct') and item.min_price_change_pct is not None:
                values.append(item.min_price_change_pct)
        
        if not values:
            return "N/A (default: 1.0%)"
        
        # Find most common value
        value_counts: Dict[float, int] = {}
        for v in values:
            value_counts[v] = value_counts.get(v, 0) + 1
        
        most_common = max(value_counts.items(), key=lambda x: x[1])[0]
        return f"{most_common}%"
    
    except Exception as e:
        logger.error(f"[TG] Error getting strategy value: {e}")
        return "N/A"


def _show_setting_strategy_input_prompt(chat_id: str, setting_key: str, strategy_key: str, message_id: Optional[int], db: Session) -> None:
    """Show input prompt for a strategy value"""
    try:
        current_value = _get_strategy_current_value(db, strategy_key, setting_key)
        
        # Format strategy name for display
        if "-" in strategy_key:
            preset, risk_mode = strategy_key.split("-", 1)
            strategy_display = f"{preset.replace('-', ' ').title()} - {risk_mode.title()}"
        else:
            strategy_display = strategy_key.replace("-", " ").title()
        
        text = f"⚙️ <b>Min Price Change %</b>\n\n"
        text += f"📊 Strategy: <b>{strategy_display}</b>\n"
        text += f"📌 Current: <b>{current_value}</b>\n\n"
        text += f"Enter minimum price change percentage required before creating a new order or sending an alert (e.g., 1, 2, 3)\n"
        
        # Build keyboard with quick buttons
        rows = []
        quick_percentages = [0.5, 1, 2, 3, 5]
        for i in range(0, len(quick_percentages), 3):
            row = []
            for pct in quick_percentages[i:i+3]:
                row.append({"text": f"{pct}%", "callback_data": f"setting:{setting_key}:set_strategy:{strategy_key}:{pct}"})
            rows.append(row)
        
        rows.append([
            {"text": "🔙 Back", "callback_data": f"setting:{setting_key}:select_strategy"}
        ])
        keyboard = _build_keyboard(rows)
        text += f"\n💡 Or send a message with the value (e.g., 1, 2, 3)"
        
        _send_menu_message(chat_id, text, keyboard)
    
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing strategy input prompt: {e}", exc_info=True)
        send_command_response(chat_id, f"❌ Error: {str(e)}")


def _apply_setting_value_to_strategy(chat_id: str, setting_key: str, strategy_key: str, value: str, message_id: Optional[int], db: Session) -> None:
    """Apply a setting value to all coins using a specific strategy"""
    try:
        from app.services.config_loader import load_config
        from app.models.watchlist import WatchlistItem
        
        if setting_key != "min_price_change_pct":
            send_command_response(chat_id, f"❌ This setting can only be applied by strategy: {setting_key}")
            return
        
        config = load_config()
        coins_config = config.get("coins", {})
        
        # Parse strategy key (e.g., "swing-conservative" or "swing")
        if "-" in strategy_key:
            preset, risk_mode = strategy_key.split("-", 1)
        else:
            preset = strategy_key
            risk_mode = None
        
        # Find all coins using this strategy
        matching_items = []
        for item in db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False,
            WatchlistItem.symbol.isnot(None)
        ).all():
            coin_config = coins_config.get(item.symbol, {})
            coin_preset = coin_config.get("preset", "swing")
            
            # Handle preset formats
            if "-" in coin_preset:
                coin_preset_base, coin_risk = coin_preset.split("-", 1)
                if coin_preset_base == preset and coin_risk == risk_mode:
                    matching_items.append(item)
            else:
                coin_risk = item.sl_tp_mode or "conservative"
                if coin_preset == preset:
                    if risk_mode is None or coin_risk == risk_mode:
                        matching_items.append(item)
        
        if not matching_items:
            send_command_response(chat_id, f"ℹ️ No coins found using strategy: {strategy_key}")
            return
        
        new_value = float(value)
        updated_count = 0
        
        try:
            for item in matching_items:
                # Check if attribute exists (for backward compatibility)
                if hasattr(item, 'min_price_change_pct'):
                    item.min_price_change_pct = new_value
                    updated_count += 1
                else:
                    logger.warning(f"[TG] WatchlistItem {item.symbol} does not have min_price_change_pct attribute. Migration may be needed.")
                    # Try to set it via direct attribute assignment anyway (in case it's a SQLAlchemy column)
                    try:
                        setattr(item, 'min_price_change_pct', new_value)
                        updated_count += 1
                    except Exception as attr_err:
                        logger.error(f"[TG] Cannot set min_price_change_pct for {item.symbol}: {attr_err}")
            
            db.commit()
            
            # Refresh all items
            for item in matching_items:
                db.refresh(item)
            
            # Format strategy name for display
            if "-" in strategy_key:
                preset_display, risk_display = strategy_key.split("-", 1)
                strategy_display = f"{preset_display.replace('-', ' ').title()} - {risk_display.title()}"
            else:
                strategy_display = strategy_key.replace("-", " ").title()
            
            text = f"✅ <b>Setting Updated</b>\n\n"
            text += f"📊 Strategy: <b>{strategy_display}</b>\n"
            text += f"✅ New Value: <b>{new_value}%</b>\n"
            text += f"📈 Updated: <b>{updated_count} coin(s)</b>\n\n"
            text += f"✅ Successfully updated all coins using this strategy!"
            
            # List updated coins
            coin_symbols = [item.symbol for item in matching_items[:10]]
            if len(matching_items) > 10:
                text += f"\n\n📋 Coins updated (showing first 10):\n"
                text += "\n".join([f"• {s}" for s in coin_symbols])
                text += f"\n... and {len(matching_items) - 10} more"
            else:
                text += f"\n\n📋 Coins updated:\n"
                text += "\n".join([f"• {s}" for s in coin_symbols])
            
            keyboard = _build_keyboard([
                [{"text": "🔙 Back to Strategy Selection", "callback_data": f"setting:{setting_key}:select_strategy"}],
                [{"text": "🏠 Main Menu", "callback_data": "menu:main"}],
            ])
            
            _send_menu_message(chat_id, text, keyboard)
            logger.info(f"[TG] Updated {setting_key} for strategy {strategy_key}: {updated_count} coins → {new_value}")
            
        except Exception as e:
            db.rollback()
            logger.error(f"[TG][ERROR] Error updating strategy setting: {e}", exc_info=True)
            send_command_response(chat_id, f"❌ Error updating setting: {str(e)}")
    
    except Exception as e:
        logger.error(f"[TG][ERROR] Error applying strategy setting value: {e}", exc_info=True)
        send_command_response(chat_id, f"❌ Error: {str(e)}")


# ---------------------------------------------------------------------------
# Signal configurator helpers (mirror dashboard Strategy Presets panel)
# ---------------------------------------------------------------------------

def _normalize_risk_label(risk_mode: Optional[str]) -> str:
    if not risk_mode:
        return "Conservative"
    normalized = risk_mode.strip().lower()
    if normalized.startswith("agg"):
        return "Aggressive"
    if normalized.startswith("con"):
        return "Conservative"
    return risk_mode.strip().title()


def _resolve_preset_key(cfg: Dict[str, Any], preset_name: str) -> str:
    preset_key = (preset_name or "").strip().lower()
    for existing in cfg.get("presets", {}).keys():
        if existing.lower() == preset_key:
            return existing
    raise ValueError(f"Preset '{preset_name}' no existe en trading_config")


def _default_rule_template(preset_key: str, preset_data: Dict[str, Any]) -> Dict[str, Any]:
    buy_default = preset_data.get("RSI_BUY") or preset_data.get("rsi_buy") or 40
    sell_default = preset_data.get("RSI_SELL") or preset_data.get("rsi_sell") or 70
    min_pct = (
        preset_data.get("minPriceChangePct")
        or preset_data.get("ALERT_MIN_PRICE_CHANGE_PCT")
        or preset_data.get("alert_min_price_change_pct")
        or 1.0
    )
    cooldown = (
        preset_data.get("alertCooldownMinutes")
        or preset_data.get("ALERT_COOLDOWN_MINUTES")
        or preset_data.get("alert_cooldown_minutes")
        or 5.0
    )
    ma_checks = preset_data.get("maChecks") or {
        "ema10": True,
        "ma50": preset_key in {"swing", "intraday"},
        "ma200": preset_key == "swing",
    }
    sl_cfg = preset_data.get("sl") or {"atrMult": 1.5}
    tp_cfg = preset_data.get("tp") or {"rr": 1.5}
    volume_ratio = preset_data.get("volumeMinRatio") or 0.5
    notes = preset_data.get("notes") or ""
    return {
        "rsi": {"buyBelow": int(buy_default), "sellAbove": int(sell_default)},
        "maChecks": {
            "ema10": bool(ma_checks.get("ema10", True)),
            "ma50": bool(ma_checks.get("ma50", False)),
            "ma200": bool(ma_checks.get("ma200", False)),
        },
        "volumeMinRatio": float(volume_ratio),
        "minPriceChangePct": float(min_pct),
        "alertCooldownMinutes": float(cooldown),
        "sl": sl_cfg,
        "tp": tp_cfg,
        "notes": notes,
    }


def _normalize_signal_config() -> Dict[str, Any]:
    from app.services.config_loader import load_config, save_config

    cfg = load_config()
    changed = False
    presets = cfg.setdefault("presets", {})
    for key, data in list(presets.items()):
        if "rules" not in data or not isinstance(data["rules"], dict):
            template = _default_rule_template(key, data)
            data["rules"] = {
                "Conservative": deepcopy(template),
                "Aggressive": deepcopy(template),
            }
            changed = True
        else:
            for risk in ("Conservative", "Aggressive"):
                if risk not in data["rules"]:
                    data["rules"][risk] = deepcopy(_default_rule_template(key, data))
                    changed = True
    if changed:
        save_config(cfg)
    return cfg


def _get_signal_rules(cfg: Dict[str, Any], preset: str, risk_mode: str) -> Tuple[Dict[str, Any], Dict[str, Any], str]:
    preset_key = _resolve_preset_key(cfg, preset)
    preset_cfg = cfg.get("presets", {}).get(preset_key, {})
    rules_by_risk = preset_cfg.setdefault("rules", {})
    risk_label = _normalize_risk_label(risk_mode)
    if risk_label not in rules_by_risk:
        rules_by_risk[risk_label] = deepcopy(_default_rule_template(preset_key, preset_cfg))
        from app.services.config_loader import save_config

        save_config(cfg)
    return rules_by_risk[risk_label], preset_cfg, risk_label


def _save_signal_config(cfg: Dict[str, Any]) -> None:
    from app.services.config_loader import save_config

    save_config(cfg)


def _update_signal_rule_value(preset: str, risk_mode: str, rule_path: str, value: Any) -> None:
    cfg = _normalize_signal_config()
    rules, _preset_cfg, risk_label = _get_signal_rules(cfg, preset, risk_mode)
    target = rules
    parts = rule_path.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value
    _save_signal_config(cfg)


def _toggle_signal_ma_check(preset: str, risk_mode: str, field: str) -> bool:
    cfg = _normalize_signal_config()
    rules, _, _ = _get_signal_rules(cfg, preset, risk_mode)
    checks = rules.setdefault("maChecks", {})
    current = bool(checks.get(field, False))
    checks[field] = not current
    _save_signal_config(cfg)
    return checks[field]


def _switch_signal_sl_method(preset: str, risk_mode: str) -> str:
    cfg = _normalize_signal_config()
    rules, _, _ = _get_signal_rules(cfg, preset, risk_mode)
    sl_cfg = rules.get("sl") or {}
    if "atrMult" in sl_cfg:
        rules["sl"] = {"pct": 0.5}
        new_mode = "pct"
    else:
        rules["sl"] = {"atrMult": 1.5}
        new_mode = "atr"
    _save_signal_config(cfg)
    return new_mode


def _switch_signal_tp_method(preset: str, risk_mode: str) -> str:
    cfg = _normalize_signal_config()
    rules, _, _ = _get_signal_rules(cfg, preset, risk_mode)
    tp_cfg = rules.get("tp") or {}
    if "rr" in tp_cfg:
        rules["tp"] = {"pct": 2.0}
        new_mode = "pct"
    else:
        rules["tp"] = {"rr": 1.5}
        new_mode = "rr"
    _save_signal_config(cfg)
    return new_mode


def show_signal_config_menu(chat_id: str, message_id: Optional[int] = None) -> bool:
    """Display list of presets/risk combinations for editing."""
    try:
        cfg = _normalize_signal_config()
        presets = cfg.get("presets", {})
        if not presets:
            return send_command_response(chat_id, "❌ No hay presets configurados.")
        rows: List[List[Dict[str, str]]] = []
        for preset_key in sorted(presets.keys()):
            preset_label = preset_key.replace("_", " ").title()
            rows.append([
                {
                    "text": f"{preset_label} · Cons",
                    "callback_data": f"signal:detail:{preset_key}:Conservative",
                },
                {
                    "text": f"{preset_label} · Agg",
                    "callback_data": f"signal:detail:{preset_key}:Aggressive",
                },
            ])
        rows.append([{"text": "🏠 Main Menu", "callback_data": "menu:main"}])
        text = "📐 <b>Signal Configurator</b>\n\nSelecciona una estrategia para editar sus reglas."
        return _send_or_edit_menu(chat_id, text, _build_keyboard(rows), message_id)
    except Exception as exc:
        logger.error(f"[TG][ERROR] show_signal_config_menu failed: {exc}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error mostrando Signal Config: {exc}")


def _format_signal_detail_text(preset_label: str, risk_label: str, rules: Dict[str, Any]) -> str:
    rsi = rules.get("rsi", {})
    ma_checks = rules.get("maChecks", {})
    sl_cfg = rules.get("sl", {})
    tp_cfg = rules.get("tp", {})
    sl_mode = "ATR x{:.2f}".format(sl_cfg.get("atrMult")) if "atrMult" in sl_cfg else "{}%".format(sl_cfg.get("pct"))
    tp_mode = (
        "RR {:.2f}".format(tp_cfg.get("rr"))
        if "rr" in tp_cfg
        else "{}%".format(tp_cfg.get("pct"))
    )
    notes = rules.get("notes") or "—"
    return (
        f"⚙️ <b>{preset_label} · {risk_label}</b>\n\n"
        f"📈 RSI: Buy <b>{rsi.get('buyBelow')}</b> | Sell > <b>{rsi.get('sellAbove')}</b>\n"
        f"📊 MA Checks: EMA10={'ON' if ma_checks.get('ema10') else 'OFF'}, "
        f"MA50={'ON' if ma_checks.get('ma50') else 'OFF'}, "
        f"MA200={'ON' if ma_checks.get('ma200') else 'OFF'}\n"
        f"📦 Volume Ratio ≥ <b>{rules.get('volumeMinRatio')}</b>x\n"
        f"📉 Min Price Change: <b>{rules.get('minPriceChangePct')}%</b>\n"
        f"⏱ Cooldown: <b>{rules.get('alertCooldownMinutes')} min</b>\n"
        f"🛡️ SL: <b>{sl_mode}</b>\n"
        f"🎯 TP: <b>{tp_mode}</b>\n"
        f"📝 Notes: {notes}"
    )


def show_signal_config_detail(chat_id: str, preset: str, risk_mode: str, message_id: Optional[int] = None) -> bool:
    """Show editable details for a preset/risk combination."""
    try:
        cfg = _normalize_signal_config()
        rules, _, risk_label = _get_signal_rules(cfg, preset, risk_mode)
        preset_key = _resolve_preset_key(cfg, preset)
        preset_label = preset_key.replace("_", " ").title()
        text = _format_signal_detail_text(preset_label, risk_label, rules)
        sl_cfg = rules.get("sl", {})
        tp_cfg = rules.get("tp", {})
        sl_method = "ATR" if "atrMult" in sl_cfg else "Percent"
        tp_method = "RR" if "rr" in tp_cfg else "Percent"
        keyboard_rows = [
            [
                {"text": "RSI Buy", "callback_data": f"signal:edit:{preset_key}:{risk_label}:rsi_buy"},
                {"text": "RSI Sell", "callback_data": f"signal:edit:{preset_key}:{risk_label}:rsi_sell"},
            ],
            [
                {"text": f"EMA10 {'✅' if rules.get('maChecks', {}).get('ema10') else '❌'}", "callback_data": f"signal:toggle:{preset_key}:{risk_label}:ema10"},
                {"text": f"MA50 {'✅' if rules.get('maChecks', {}).get('ma50') else '❌'}", "callback_data": f"signal:toggle:{preset_key}:{risk_label}:ma50"},
                {"text": f"MA200 {'✅' if rules.get('maChecks', {}).get('ma200') else '❌'}", "callback_data": f"signal:toggle:{preset_key}:{risk_label}:ma200"},
            ],
            [
                {"text": "Volume Ratio", "callback_data": f"signal:edit:{preset_key}:{risk_label}:volume_ratio"},
                {"text": "Min % Change", "callback_data": f"signal:edit:{preset_key}:{risk_label}:min_pct"},
                {"text": "Cooldown", "callback_data": f"signal:edit:{preset_key}:{risk_label}:cooldown"},
            ],
            [
                {"text": f"SL Mode ({sl_method})", "callback_data": f"signal:slmethod:{preset_key}:{risk_label}"},
                {"text": "SL Value", "callback_data": f"signal:edit:{preset_key}:{risk_label}:sl_value"},
            ],
            [
                {"text": f"TP Mode ({tp_method})", "callback_data": f"signal:tpmethod:{preset_key}:{risk_label}"},
                {"text": "TP Value", "callback_data": f"signal:edit:{preset_key}:{risk_label}:tp_value"},
            ],
            [
                {"text": "✏️ Notes", "callback_data": f"signal:notes:{preset_key}:{risk_label}"},
            ],
            [
                {"text": "🔙 Estrategias", "callback_data": "signal:menu"},
                {"text": "🏠 Main", "callback_data": "menu:main"},
            ],
        ]
        return _send_or_edit_menu(chat_id, text, _build_keyboard(keyboard_rows), message_id)
    except Exception as exc:
        logger.error(f"[TG][ERROR] show_signal_config_detail failed: {exc}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error mostrando reglas: {exc}")


def _handle_signal_config_callback(chat_id: str, callback_data: str, message_id: Optional[int]) -> None:
    """Process inline button actions for the signal configurator."""
    try:
        parts = callback_data.split(":")
        if len(parts) < 2:
            send_command_response(chat_id, "❌ Acción inválida en configurador.")
            return
        action = parts[1]
        if action == "menu":
            show_signal_config_menu(chat_id, message_id=message_id)
            return
        if len(parts) < 4:
            send_command_response(chat_id, "❌ Parámetros insuficientes.")
            return
        preset = parts[2]
        risk_mode = parts[3]
        if action == "detail":
            show_signal_config_detail(chat_id, preset, risk_mode, message_id=message_id)
            return
        cfg = _normalize_signal_config()
        rules, _, risk_label = _get_signal_rules(cfg, preset, risk_mode)
        if action == "edit":
            if len(parts) < 5:
                send_command_response(chat_id, "❌ Campo no especificado.")
                return
            field = parts[4]
            label = ""
            rule_path = ""
            value_type = "float"
            min_value = None
            max_value = None
            if field == "rsi_buy":
                label = "RSI Buy Below"
                rule_path = "rsi.buyBelow"
                value_type = "int"
                min_value = 0
                max_value = 100
            elif field == "rsi_sell":
                label = "RSI Sell Above"
                rule_path = "rsi.sellAbove"
                value_type = "int"
                min_value = 0
                max_value = 100
            elif field == "volume_ratio":
                label = "Volume Ratio"
                rule_path = "volumeMinRatio"
                min_value = 0.1
            elif field == "min_pct":
                label = "Min Price Change %"
                rule_path = "minPriceChangePct"
                min_value = 0.1
            elif field == "cooldown":
                label = "Alert Cooldown (minutes)"
                rule_path = "alertCooldownMinutes"
                min_value = 0.0
            elif field == "sl_value":
                sl_cfg = rules.get("sl", {})
                if "atrMult" in sl_cfg:
                    label = "SL ATR Multiplier"
                    rule_path = "sl.atrMult"
                    min_value = 0.1
                else:
                    label = "SL Percentage"
                    rule_path = "sl.pct"
                    min_value = 0.1
            elif field == "tp_value":
                tp_cfg = rules.get("tp", {})
                if "rr" in tp_cfg:
                    label = "TP Risk/Reward"
                    rule_path = "tp.rr"
                    min_value = 0.1
                else:
                    label = "TP Percentage"
                    rule_path = "tp.pct"
                    min_value = 0.1
            else:
                send_command_response(chat_id, "❌ Campo no soportado.")
                return
            _prompt_value_input(
                chat_id,
                f"{label}\n\nEnvía el nuevo valor.",
                symbol=None,
                field=None,
                action="update_rule",
                value_type=value_type,
                min_value=min_value,
                max_value=max_value,
                extra={
                    "preset": preset,
                    "risk": risk_label,
                    "rule_path": rule_path,
                    "label": label,
                },
            )
        elif action == "toggle":
            if len(parts) < 5:
                send_command_response(chat_id, "❌ Campo no especificado.")
                return
            field = parts[4]
            new_value = _toggle_signal_ma_check(preset, risk_mode, field)
            send_command_response(chat_id, f"✅ {field.upper()} ahora está {'ON' if new_value else 'OFF'}")
            show_signal_config_detail(chat_id, preset, risk_mode)
        elif action == "slmethod":
            new_mode = _switch_signal_sl_method(preset, risk_mode)
            send_command_response(chat_id, f"🛡️ SL configurado a {new_mode.upper()}")
            show_signal_config_detail(chat_id, preset, risk_mode)
        elif action == "tpmethod":
            new_mode = _switch_signal_tp_method(preset, risk_mode)
            send_command_response(chat_id, f"🎯 TP configurado a {new_mode.upper()}")
            show_signal_config_detail(chat_id, preset, risk_mode)
        elif action == "notes":
            _prompt_value_input(
                chat_id,
                "📝 Escribe las notas para esta estrategia.",
                symbol=None,
                field=None,
                action="update_rule",
                value_type="string",
                extra={
                    "preset": preset,
                    "risk": risk_label,
                    "rule_path": "notes",
                    "label": "Notas",
                },
            )
        else:
            send_command_response(chat_id, "❌ Acción no soportada.")
    except Exception as exc:
        logger.error(f"[TG][ERROR] signal config callback failed: {exc}", exc_info=True)
        send_command_response(chat_id, f"❌ Error en configurador: {exc}")

