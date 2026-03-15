"""Telegram Command Handler
Handles incoming Telegram commands and responds with formatted messages
"""
import os
import logging
import math
import time
import tempfile
import sys
import json
from typing import Optional, Dict, List, Any, Tuple, cast
from datetime import datetime, timedelta
from copy import deepcopy
import pytz
from app.services.telegram_notifier import telegram_notifier
from app.core.runtime import is_aws_runtime
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, not_, or_
from sqlalchemy.sql import func
from app.models.watchlist import WatchlistItem
from app.models.telegram_state import TelegramState
from app.database import SessionLocal, engine
from app.utils.http_client import http_get, http_post, requests_exceptions
from app.utils.telegram_token_loader import get_telegram_token, get_telegram_token_dev, mask_token

logger = logging.getLogger(__name__)


def _to_float(v: Any) -> float:
    """Convert ORM Column or value to float for type checker and runtime."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


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
# Token loading: TELEGRAM_BOT_TOKEN → TELEGRAM_BOT_TOKEN_DEV → interactive popup (never logged or persisted)
_env_bot_token = get_telegram_token() or ""
_env_bot_token_dev = get_telegram_token_dev()
# TELEGRAM_AUTH_USER_ID: Comma or space-separated list of authorized user IDs and/or channel IDs
# If not set, falls back to TELEGRAM_CHAT_ID (for backward compatibility)
# For multiple channels (e.g. HILOVIVO3.0 + Hilovivo-alerts): "CHANNEL_ID_1,CHANNEL_ID_2"
_env_auth_user_ids = (os.getenv("TELEGRAM_AUTH_USER_ID") or "").strip()
# TELEGRAM_CHAT_ID_TRADING: HILOVIVO3.0 — alerts-only (signals, orders, reports). NOT used for commands.
_env_chat_id_trading = (os.getenv("TELEGRAM_CHAT_ID_TRADING") or "").strip()
# TELEGRAM_CHAT_ID: Primary channel ID; also used as single authorized chat when TELEGRAM_AUTH_USER_ID unset
AUTH_CHAT_ID = _env_chat_id or None
BOT_TOKEN = _env_bot_token or None
BOT_TOKEN_DEV = _env_bot_token_dev or None

# Parse authorized user IDs (support comma or space separated)
AUTHORIZED_USER_IDS = set()
if _env_auth_user_ids:
    # Split by comma or space, strip whitespace
    for user_id in _env_auth_user_ids.replace(",", " ").split():
        user_id = user_id.strip()
        if user_id:
            AUTHORIZED_USER_IDS.add(user_id)
            logger.info(f"[TG][AUTH] Added authorized user ID: {user_id}")
elif AUTH_CHAT_ID:
    # Fallback: if no TELEGRAM_AUTH_USER_ID is set, use TELEGRAM_CHAT_ID as authorized chat
    # This allows backward compatibility but note: TELEGRAM_CHAT_ID is typically a channel ID
    AUTHORIZED_USER_IDS.add(str(AUTH_CHAT_ID))
    logger.info(f"[TG][AUTH] Using TELEGRAM_CHAT_ID as authorized chat (backward compatibility): {AUTH_CHAT_ID}")
if AUTH_CHAT_ID and str(AUTH_CHAT_ID) not in AUTHORIZED_USER_IDS:
    # Always allow AUTH_CHAT_ID (TELEGRAM_CHAT_ID) even when TELEGRAM_AUTH_USER_ID is set
    # Enables both primary channel and additional channels in TELEGRAM_AUTH_USER_ID
    AUTHORIZED_USER_IDS.add(str(AUTH_CHAT_ID))
# HILOVIVO3.0 (TELEGRAM_CHAT_ID_TRADING) is alerts-only — do NOT add to command auth.
# Commands must go to ATP Control (TELEGRAM_CHAT_ID or TELEGRAM_AUTH_USER_ID).

TELEGRAM_ENABLED = bool(BOT_TOKEN and (AUTH_CHAT_ID or AUTHORIZED_USER_IDS))
# Set to True when startup diagnostics get 401 (token invalid); disables polling/commands without crashing
_telegram_startup_401: bool = False

if not TELEGRAM_ENABLED:
    logger.warning("Telegram disabled: missing env vars - Telegram commands inactive")

# Startup: log command-intake config for operator visibility (no secrets)
# ATP Control = TELEGRAM_CHAT_ID or TELEGRAM_AUTH_USER_ID (private group / direct chat). HILOVIVO3.0 = alerts-only.
# Token is never logged in full; only masked.
logger.info(
    "[TG][CONFIG] command_intake: bot_token=%s telegram_enabled=%s control_chat_id=%s "
    "alerts_chat_id=%s authorized_count=%s",
    mask_token(BOT_TOKEN) if BOT_TOKEN else "MISSING",
    TELEGRAM_ENABLED,
    AUTH_CHAT_ID or "none",
    _env_chat_id_trading or "none",
    len(AUTHORIZED_USER_IDS),
)

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


def _get_effective_bot_token() -> Optional[str]:
    """Return the bot token to use for sending. Matches polling token (DEV on local, PROD on AWS)."""
    if not is_aws_runtime() and BOT_TOKEN_DEV:
        return BOT_TOKEN_DEV
    return BOT_TOKEN


def _is_authorized(chat_id: str, user_id: str) -> bool:
    """
    Check if a user/chat is authorized to use bot commands.
    
    Authorization rules:
    1. If chat_id matches AUTH_CHAT_ID (channel/group ID), allow
    2. If user_id is in AUTHORIZED_USER_IDS, allow
    3. If chat_id is in AUTHORIZED_USER_IDS (for private chats), allow
    
    Args:
        chat_id: Telegram chat ID (can be user ID for private chats, or channel/group ID)
        user_id: Telegram user ID (from message.from.id)
    
    Returns:
        True if authorized, False otherwise
    """
    if not AUTH_CHAT_ID and not AUTHORIZED_USER_IDS:
        # No authorization configured - allow all (for development)
        return True
    
    chat_id_str = str(chat_id) if chat_id else ""
    user_id_str = str(user_id) if user_id else ""
    auth_chat_id_str = str(AUTH_CHAT_ID) if AUTH_CHAT_ID else ""
    
    # Check if chat_id matches channel/group ID
    if auth_chat_id_str and chat_id_str == auth_chat_id_str:
        return True
    
    # Check if user_id is in authorized user IDs
    if user_id_str and user_id_str in AUTHORIZED_USER_IDS:
        return True
    
    # Check if chat_id is in authorized user IDs (for private chats)
    if chat_id_str and chat_id_str in AUTHORIZED_USER_IDS:
        return True
    
    logger.info(
        "[TG][AUTH] Unauthorized command blocked: chat_id=%s user_id=%s authorized_ids=%s",
        chat_id_str or "N/A",
        user_id_str or "N/A",
        ",".join(sorted(AUTHORIZED_USER_IDS)) if AUTHORIZED_USER_IDS else "none",
    )
    return False


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
            LAST_UPDATE_ID = int(getattr(state, "last_update_id", 0))
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
            setattr(state, "last_update_id", update_id)
            setattr(state, "updated_at", datetime.now(pytz.UTC))
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
    On 401 (token invalid): logs one line only (no URL/token), disables Telegram gracefully, does not crash.
    """
    global _telegram_startup_401
    diagnostics_enabled = os.getenv("TELEGRAM_DIAGNOSTICS", "0").strip() == "1"
    
    if not TELEGRAM_ENABLED or not BOT_TOKEN:
        logger.warning("[TG] Startup diagnostics skipped: Telegram not enabled")
        return
    
    log_prefix = "[TG_DIAG]" if diagnostics_enabled else "[TG]"
    try:
        # 1. Call getMe
        if diagnostics_enabled:
            logger.info(f"{log_prefix} Running startup diagnostics (TELEGRAM_DIAGNOSTICS=1)...")
        else:
            logger.info(f"{log_prefix} Running startup diagnostics...")
        response = http_get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5, calling_module="telegram_commands")
        if response.status_code == 401:
            _telegram_startup_401 = True
            logger.warning("[TG] Startup diagnostics failed: unauthorized (token invalid) — disabling Telegram commands")
            return
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
        response = http_get(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo", timeout=5, calling_module="telegram_commands")
        if response.status_code == 401:
            _telegram_startup_401 = True
            logger.warning("[TG] Startup diagnostics failed: unauthorized (token invalid) — disabling Telegram commands")
            return
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
                response = http_post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", json={"drop_pending_updates": True}, timeout=5
                , calling_module="telegram_commands")
                if response.status_code == 401:
                    _telegram_startup_401 = True
                    logger.warning("[TG] Startup diagnostics failed: unauthorized (token invalid) — disabling Telegram commands")
                    return
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
                response = http_get(url, params=params, timeout=5, calling_module="telegram_commands")
                if response.status_code == 401:
                    _telegram_startup_401 = True
                    logger.warning("[TG] Startup diagnostics failed: unauthorized (token invalid) — disabling Telegram commands")
                    return
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
            
    except requests_exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 401:
            _telegram_startup_401 = True
            logger.warning("[TG] Startup diagnostics failed: unauthorized (token invalid) — disabling Telegram commands")
            return
        logger.error(f"{log_prefix} Startup diagnostics failed: {e}", exc_info=False)
    except Exception as e:
        logger.error(f"{log_prefix} Startup diagnostics failed: {e}", exc_info=True)


def _probe_updates_without_offset() -> List[Dict]:
    """Probe Telegram for updates without offset to detect missed updates."""
    if _telegram_startup_401 or not TELEGRAM_ENABLED or not BOT_TOKEN:
        return []
    
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {"limit": 50}  # Get up to 50 updates
        response = http_get(url, params=params, timeout=5, calling_module="telegram_commands")
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


def _calculate_portfolio_pnl(db: Session) -> Tuple[float, float]:
    """
    Calculate realized and unrealized PnL from executed orders and open positions.
    
    Returns:
        Tuple[realized_pnl, unrealized_pnl]
    """
    try:
        from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
        from app.models.market_price import MarketPrice
        
        # Calculate realized PnL from executed orders (FILLED BUY/SELL pairs)
        # Track positions per symbol for accurate matching
        realized_pnl = 0.0
        
        # Get all FILLED orders ordered by execution time, grouped by symbol
        filled_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.status == OrderStatusEnum.FILLED
        ).order_by(
            ExchangeOrder.symbol.asc(),
            ExchangeOrder.exchange_update_time.asc(),
            ExchangeOrder.created_at.asc()
        ).all()
        
        # Group orders by symbol for per-symbol FIFO matching
        orders_by_symbol: Dict[str, List[ExchangeOrder]] = {}
        for order in filled_orders:
            symbol = (order.symbol or "").upper()
            if symbol:
                orders_by_symbol.setdefault(symbol, []).append(order)
        
        # Process each symbol separately
        for symbol, symbol_orders in orders_by_symbol.items():
            # FIFO matching: Match BUY orders with SELL orders per symbol
            buy_queue: List[Tuple[float, float]] = []  # List of (quantity, avg_price) tuples
            
            for order in symbol_orders:
                if getattr(order, "order_role", None) in ["STOP_LOSS", "TAKE_PROFIT"]:
                    continue
                
                qty = _to_float(getattr(order, "cumulative_quantity", None) or getattr(order, "quantity", None))
                price = _to_float(getattr(order, "avg_price", None) or getattr(order, "price", None))
                
                if qty <= 0 or price <= 0:
                    continue
                
                if getattr(order, "side", None) == OrderSideEnum.BUY:
                    # Add to buy queue
                    buy_queue.append((qty, price))
                elif getattr(order, "side", None) == OrderSideEnum.SELL:
                    # Match with earliest BUY orders (FIFO)
                    remaining_sell_qty = qty
                    while remaining_sell_qty > 0 and buy_queue:
                        buy_qty, buy_price = buy_queue[0]
                        
                        if buy_qty <= remaining_sell_qty:
                            # This BUY is fully matched
                            pnl = (price - buy_price) * buy_qty
                            realized_pnl += pnl
                            remaining_sell_qty -= buy_qty
                            buy_queue.pop(0)
                        else:
                            # Partial match
                            pnl = (price - buy_price) * remaining_sell_qty
                            realized_pnl += pnl
                            buy_queue[0] = (buy_qty - remaining_sell_qty, buy_price)
                            remaining_sell_qty = 0
        
        # Calculate unrealized PnL from open positions (remaining buy_queue per symbol)
        unrealized_pnl = 0.0
        
        # Get current prices for all symbols (use Python values for type checker)
        market_prices = db.query(MarketPrice).all()
        price_map: Dict[str, float] = {
            str(getattr(mp, "symbol", "") or "").upper(): _to_float(getattr(mp, "price", None))
            for mp in market_prices
        }
        
        open_positions_by_symbol: Dict[str, List[Tuple[float, float]]] = {}
        
        for symbol, symbol_orders in orders_by_symbol.items():
            symbol_buy_queue: List[Tuple[float, float]] = []
            
            for order in symbol_orders:
                if getattr(order, "order_role", None) in ["STOP_LOSS", "TAKE_PROFIT"]:
                    continue
                
                qty = _to_float(getattr(order, "cumulative_quantity", None) or getattr(order, "quantity", None))
                price = _to_float(getattr(order, "avg_price", None) or getattr(order, "price", None))
                
                if qty <= 0 or price <= 0:
                    continue
                
                if getattr(order, "side", None) == OrderSideEnum.BUY:
                    symbol_buy_queue.append((qty, price))
                elif getattr(order, "side", None) == OrderSideEnum.SELL:
                    remaining_sell_qty = qty
                    while remaining_sell_qty > 0 and symbol_buy_queue:
                        buy_qty, _ = symbol_buy_queue[0]
                        if buy_qty <= remaining_sell_qty:
                            remaining_sell_qty -= buy_qty
                            symbol_buy_queue.pop(0)
                        else:
                            symbol_buy_queue[0] = (buy_qty - remaining_sell_qty, symbol_buy_queue[0][1])
                            remaining_sell_qty = 0
            
            if symbol_buy_queue:
                open_positions_by_symbol[symbol] = symbol_buy_queue
        
        # Calculate unrealized PnL for each symbol's open positions
        for symbol, positions in open_positions_by_symbol.items():
            # Try to find current price for this symbol
            current_price = None
            
            # Check symbol directly
            if symbol in price_map:
                current_price = price_map[symbol]
            else:
                # Try variants (e.g., BTC_USDT, BTC_USD, BTC)
                symbol_variants = [
                    symbol,
                    symbol.replace("_USDT", ""),
                    symbol.replace("_USD", ""),
                ]
                for variant in symbol_variants:
                    if variant in price_map:
                        current_price = price_map[variant]
                        break
            
            if current_price and current_price > 0:
                # Calculate average entry price and total quantity for this symbol
                total_qty = sum(qty for qty, _ in positions)
                if total_qty > 0:
                    # Weighted average entry price
                    total_cost = sum(qty * price for qty, price in positions)
                    avg_entry_price = total_cost / total_qty
                    
                    # Calculate unrealized PnL
                    position_pnl = (current_price - avg_entry_price) * total_qty
                    unrealized_pnl += position_pnl
        
        logger.debug(f"[PNL] Calculated: realized=${realized_pnl:.2f}, unrealized=${unrealized_pnl:.2f}")
        return realized_pnl, unrealized_pnl
        
    except Exception as e:
        logger.warning(f"[PNL] Error calculating PnL: {e}", exc_info=True)
        return 0.0, 0.0


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
        f"🔔 Alert: <b>{'ENABLED' if getattr(item, 'alert_enabled', False) else 'DISABLED'}</b>\n"
        f"🟢 Buy Alert: <b>{buy_alert}</b> | 🔻 Sell Alert: <b>{sell_alert}</b>\n"
        f"🤖 Trade: <b>{'ENABLED' if getattr(item, 'trade_enabled', False) else 'DISABLED'}</b>\n"
        f"⚡ Margin: <b>{'ON' if getattr(item, 'trade_on_margin', False) else 'OFF'}</b>\n"
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


def _delete_watchlist_symbol(db: Optional[Session], symbol: str) -> None:
    """Soft delete symbol if column exists, fallback to hard delete."""
    if db is None:
        raise ValueError("Database session required")
    item = _get_watchlist_item(db, symbol)
    if not item:
        raise ValueError(f"{symbol} no existe")
    if hasattr(item, "is_deleted"):
        setattr(item, "is_deleted", True)
        setattr(item, "alert_enabled", False)
        setattr(item, "trade_enabled", False)
        setattr(item, "trade_on_margin", False)
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
    # Never consume commands — let them reach the command router
    if text.strip().startswith("/"):
        return False
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
            send_command_response(chat_id, f"✅ {str(getattr(new_item, 'symbol', '') or '')} agregado con Alert=NO / Trade=NO.")
            show_coin_menu(chat_id, str(getattr(new_item, "symbol", "") or ""), db)
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
    """Send a message with inline keyboard and remove persistent keyboard if present."""
    if not TELEGRAM_ENABLED:
        logger.debug("Telegram disabled: skipping menu message")
        return False
    try:
        # Remove persistent keyboard first (if it exists) to avoid showing both keyboards
        # This prevents the duplication issue where both inline buttons and persistent keyboard show
        try:
            remove_payload = {
                "chat_id": chat_id,
                "text": " ",  # Minimal text required by Telegram API
                "reply_markup": {"remove_keyboard": True}
            }
            token = _get_effective_bot_token()
            if token:
                remove_response = http_post(
                    f"https://api.telegram.org/bot{token}/sendMessage", json=remove_payload, timeout=5,
                    calling_module="telegram_commands")
                if remove_response.status_code == 200:
                    remove_result = remove_response.json()
                    if remove_result.get("ok"):
                        # Delete the removal message immediately to keep chat clean
                        delete_msg_id = remove_result.get('result', {}).get('message_id')
                        try:
                            http_post(
                                f"https://api.telegram.org/bot{token}/deleteMessage",
                                json={"chat_id": chat_id, "message_id": delete_msg_id},
                                timeout=5, calling_module="telegram_commands")
                        except Exception:
                            pass  # Ignore delete errors
        except Exception as e:
            # Ignore errors - persistent keyboard might not exist, which is fine
            logger.debug(f"[TG] Could not remove persistent keyboard (may not exist): {e}")
        
        # Small delay to ensure keyboard removal is processed
        time.sleep(0.1)
        
        # Now send the message with inline keyboard
        token = _get_effective_bot_token()
        if not token:
            logger.warning("[TG] No bot token for _send_menu_message")
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        }
        logger.info(f"[TG] Sending menu message to chat_id={chat_id}, text_preview={text[:50]}..., keyboard_type={list(keyboard.keys())}")
        logger.debug(f"[TG] Full keyboard structure: {json.dumps(keyboard, indent=2)}")
        response = http_post(url, json=payload, timeout=10, calling_module="telegram_commands")
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
    except requests_exceptions.HTTPError as e:
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
    token = _get_effective_bot_token()
    if not token:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        }
        response = http_post(url, json=payload, timeout=10, calling_module="telegram_commands")
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
            {"command": "investigate", "description": "Investigar problema (auto-ruta a agente)"},
            {"command": "agent", "description": "Forzar agente: /agent sentinel|ledger <problema>"},
            {"command": "runtime-check", "description": "Verificar dependencias de runtime (pydantic, etc.)"},
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
            {"command": "skip_sl_tp_reminder", "description": "No preguntar más sobre SL/TP"},
            {"command": "panic", "description": "🛑 EMERGENCIA: Detener todo el trading (Trade=NO para todas)"},
            {"command": "kill", "description": "🛑 Kill switch: on/off/status - Global trading kill switch"},
            {"command": "agent", "description": "Agent console: activity, approvals, failures"},
        ]
        
        payload = {
            "commands": commands
        }
        
        response = http_post(url, json=payload, timeout=10, calling_module="telegram_commands")
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
    
    RUNTIME GUARD: 
    - AWS: Uses TELEGRAM_BOT_TOKEN (production token)
    - LOCAL: Only allows polling if TELEGRAM_BOT_TOKEN_DEV is set (uses dev token)
    - LOCAL without DEV token: Returns empty to avoid 409 conflicts with AWS
    
    NOTE: Lock acquisition is handled by the caller (process_telegram_commands).
    This function assumes the lock is already held.
    """
    if _telegram_startup_401:
        return []
    # RUNTIME GUARD: Local runtime requires DEV token to avoid 409 conflicts
    if not is_aws_runtime():
        # LOCAL runtime: Only allow polling with DEV token
        if not BOT_TOKEN_DEV:
            logger.warning(
                "[TG] LOCAL runtime detected but TELEGRAM_BOT_TOKEN_DEV not set. "
                "Skipping getUpdates to avoid 409 conflicts with AWS production. "
                "Set TELEGRAM_BOT_TOKEN_DEV to enable local polling with a separate dev bot."
            )
            return []
        # Use DEV token for local polling
        token_to_use = BOT_TOKEN_DEV
        logger.debug(f"[TG_LOCAL_DEBUG] Using DEV token for getUpdates in LOCAL runtime")
    else:
        # AWS runtime: Use production token
        if not BOT_TOKEN:
            logger.warning("[TG] AWS runtime but TELEGRAM_BOT_TOKEN not set")
            return []
        token_to_use = BOT_TOKEN
    
    if not token_to_use:
        return []
    
    try:
        url = f"https://api.telegram.org/bot{token_to_use}/getUpdates"
        params = {}
        if offset is not None:
            params["offset"] = offset
        # Include message, channel_post, and my_chat_member updates
        # channel_post: required for commands in channels (e.g. HILOVIVO3.0) — channel posts use channel_post, not message
        # my_chat_member: needed for bot being added to groups
        params["allowed_updates"] = [
            "message", "edited_message",
            "channel_post", "edited_channel_post",
            "my_chat_member", "callback_query",
        ]
        
        # Use long polling: Telegram will wait up to 30 seconds for new messages
        # This allows real-time command processing
        # Allow timeout override for quick checks
        # NOTE: Using shorter timeout (10s) to release lock more frequently and allow other pollers
        params["timeout"] = timeout_override if timeout_override is not None else 10
        
        # Increase timeout to account for network delay
        request_timeout = (timeout_override + 5) if timeout_override else 35
        response = http_get(url, params=params, timeout=request_timeout, calling_module="telegram_commands")
        response.raise_for_status()
        
        data = response.json()
        if data.get("ok"):
            return data.get("result", [])
        return []
    except requests_exceptions.Timeout:
        # Timeout is expected when no new messages - return empty list
        return []
    except requests_exceptions.HTTPError as http_err:
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


TELEGRAM_MAX_MESSAGE_LENGTH = 4096  # Telegram API limit


def send_command_response(chat_id: str, message: str) -> bool:
    """Send response message to Telegram. Truncates to 4096 chars. Always tries fallback on HTML error."""
    if not TELEGRAM_ENABLED:
        logger.debug("Telegram disabled: skipping command response")
        return False
    token = _get_effective_bot_token()
    if not token:
        logger.warning("[TG] No bot token available for send_command_response")
        return False
    # Telegram limit 4096; truncate with note if over
    if len(message) > TELEGRAM_MAX_MESSAGE_LENGTH:
        message = message[: TELEGRAM_MAX_MESSAGE_LENGTH - 50] + "\n\n… [truncated]"
        logger.warning("[TG][REPLY] Message truncated to %s chars", TELEGRAM_MAX_MESSAGE_LENGTH)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"  # Use HTML instead of Markdown (more reliable)
        }
        response = http_post(url, json=payload, timeout=10, calling_module="telegram_commands")
        
        if response.status_code != 200:
            error_data = response.json() if response.content else {}
            logger.error(
                "[TG][ERROR] sendMessage failed: status=%s chat_id=%s error=%s",
                response.status_code, chat_id, error_data,
            )
            # Try without parse_mode (HTML parse errors often return 400)
            try:
                payload_no_parse = {
                    "chat_id": chat_id,
                    "text": message[:TELEGRAM_MAX_MESSAGE_LENGTH],
                }
                response2 = http_post(url, json=payload_no_parse, timeout=10, calling_module="telegram_commands")
                response2.raise_for_status()
                logger.info("[TG][REPLY] chat_id=%s success=True (fallback, no parse_mode)", chat_id)
                return True
            except Exception as e2:
                logger.error("[TG][ERROR] Fallback send failed: %s", e2)
                return False
        
        response.raise_for_status()
        logger.info("[TG][REPLY] chat_id=%s success=True", chat_id)
        return True
    except Exception as e:
        logger.error("[TG][REPLY] chat_id=%s success=False error=%s", chat_id, e)
        resp = getattr(e, "response", None)
        if resp is not None:
            try:
                error_data = resp.json()
                logger.error("[TG][ERROR] Error details: %s", error_data)
            except Exception:
                logger.error("[TG][ERROR] Error response: %s", getattr(resp, "text", "")[:200])
        # Last resort: try plain text
        try:
            payload_plain = {"chat_id": chat_id, "text": message[:TELEGRAM_MAX_MESSAGE_LENGTH]}
            http_post(url, json=payload_plain, timeout=10, calling_module="telegram_commands")
            logger.info("[TG][REPLY] chat_id=%s success=True (exception fallback)", chat_id)
            return True
        except Exception as e3:
            logger.error("[TG][ERROR] Exception fallback also failed: %s", e3)
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
        response = http_post(url, json=payload, timeout=10, calling_module="telegram_commands")
        response.raise_for_status()
        logger.info(f"[TG] Custom keyboard set up for chat_id={chat_id}")
        return True
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to setup custom keyboard: {e}", exc_info=True)
        return False


def send_welcome_message(chat_id: str, db: Optional[Session] = None) -> bool:
    """Send welcome message - shows main menu (same as /start)"""
    if not TELEGRAM_ENABLED:
        return False
    try:
        # Just show the main menu (same as /start command)
        # This avoids duplication and provides consistent experience
        logger.info(f"[TG] Sending welcome message (main menu) to chat_id={chat_id}")
        return show_main_menu(chat_id, db)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to send welcome message: {e}", exc_info=True)
        return False


def send_audit_snapshot(chat_id: str, db: Optional[Session] = None) -> bool:
    """Send audit snapshot with system health and status"""
    if db is None:
        send_command_response(chat_id, "❌ Database not available")
        return False
    try:
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        from app.models.watchlist import WatchlistItem
        from app.services.watchlist_selector import deduplicate_watchlist_items
        import time
        
        lines = ["🔍 <b>Audit Snapshot</b>\n"]
        
        # Service health
        backend_ok = False
        try:
            response = http_get(f"{API_BASE_URL.rstrip('/')}/api/ping_fast", timeout=5, calling_module="telegram_commands")
            backend_ok = response.status_code == 200
        except:
            pass
        
        lines.append(f"📊 <b>Service Health:</b>")
        lines.append(f"  Backend: {'✅ OK' if backend_ok else '❌ FAILED'}")
        lines.append("")
        
        # Watchlist deduplication status
        if db:
            try:
                all_items = db.query(WatchlistItem).filter(WatchlistItem.is_deleted == False).all()
                canonical_items = deduplicate_watchlist_items(all_items)
                duplicates = len(all_items) - len(canonical_items)
                unique_symbols = len(set(item.symbol.upper() for item in canonical_items))
                
                lines.append(f"📋 <b>Watchlist:</b>")
                lines.append(f"  Symbols: {unique_symbols}")
                lines.append(f"  Duplicates: {'⚠️ ' + str(duplicates) if duplicates > 0 else '✅ 0'}")
                lines.append("")
            except Exception as wl_err:
                logger.warning(f"[AUDIT] Error checking watchlist: {wl_err}")
                lines.append("📋 <b>Watchlist:</b> ⚠️ Error checking")
                lines.append("")
        
        # Active alerts count
        if db:
            try:
                buy_alerts = db.query(WatchlistItem).filter(
                    WatchlistItem.is_deleted == False,
                    WatchlistItem.buy_alert_enabled == True
                ).count()
                sell_alerts = db.query(WatchlistItem).filter(
                    WatchlistItem.is_deleted == False,
                    WatchlistItem.sell_alert_enabled == True
                ).count()
                
                lines.append(f"🔔 <b>Active Alerts:</b>")
                lines.append(f"  BUY: {buy_alerts}")
                lines.append(f"  SELL: {sell_alerts}")
                lines.append("")
            except Exception as alert_err:
                logger.warning(f"[AUDIT] Error counting alerts: {alert_err}")
        
        # Open orders count
        if db:
            try:
                open_orders = db.query(ExchangeOrder).filter(
                    ExchangeOrder.status.in_([
                        OrderStatusEnum.NEW,
                        OrderStatusEnum.ACTIVE,
                        OrderStatusEnum.PARTIALLY_FILLED
                    ])
                ).count()
                
                lines.append(f"📦 <b>Open Orders:</b> {open_orders}")
                if open_orders > 3:
                    lines.append("  ⚠️ Warning: More than 3 open orders")
                lines.append("")
            except Exception as order_err:
                logger.warning(f"[AUDIT] Error counting orders: {order_err}")
        
        # Watchlist load time
        if backend_ok:
            try:
                start_time = time.time()
                response = http_get(f"{API_BASE_URL.rstrip('/')}/api/dashboard/state", timeout=10, calling_module="telegram_commands")
                elapsed_ms = int((time.time() - start_time) * 1000)
                
                lines.append(f"⏱️  <b>Watchlist Load:</b> {elapsed_ms}ms")
                if elapsed_ms > 2000:
                    lines.append("  ⚠️ Warning: Load time exceeds 2 seconds")
                lines.append("")
            except Exception as load_err:
                logger.warning(f"[AUDIT] Error measuring load time: {load_err}")
        
        # Reports status
        if backend_ok:
            try:
                response = http_get(f"{API_BASE_URL.rstrip('/')}/api/reports/dashboard-data-integrity/latest", timeout=5, calling_module="telegram_commands")
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict) and data.get("status") == "success":
                        report_data = data.get("report", {})
                        inconsistencies = report_data.get("inconsistencies", [])
                        lines.append(f"📊 <b>Reports:</b> ✅ OK ({len(inconsistencies)} inconsistencies)")
                    else:
                        lines.append("📊 <b>Reports:</b> ⚠️ No report available")
                else:
                    lines.append("📊 <b>Reports:</b> ⚠️ Endpoint not available")
            except Exception as report_err:
                logger.debug(f"[AUDIT] Reports check failed (non-critical): {report_err}")
                lines.append("📊 <b>Reports:</b> ⚠️ Could not check")
        
        message = "\n".join(lines)
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[AUDIT] Error generating snapshot: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error generating audit snapshot: {str(e)}")


def send_help_message(chat_id: str) -> bool:
    """Send help message with command descriptions"""
    try:
        from app.services.agent_telegram_commands import get_agent_help_content
        agent_section = get_agent_help_content()
    except Exception:
        agent_section = ""
    message = """📚 <b>Command Help</b>

<b>ATP Control</b> — You are in the ATP command console. Commands work here.
HILOVIVO3.0 = alerts-only. Claw = OpenClaw-native only.

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
/audit or /snapshot - Show system audit snapshot (health, watchlist, alerts, orders)
/create_sl_tp [symbol] - Create SL/TP orders for positions missing protection
/create_sl [symbol] - Create only SL order for a position
/create_tp [symbol] - Create only TP order for a position
/skip_sl_tp_reminder [symbol] - Don't ask about SL/TP for these positions anymore
""" + (agent_section if agent_section else "") + """
<b>Note:</b> Only authorized users can use these commands."""
    return send_command_response(chat_id, message)


def show_main_menu(chat_id: str, db: Optional[Session] = None) -> bool:
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
    if db is None:
        return False
    try:
        # Authorization check - use helper function
        # Note: For menu display, we need user_id but it's not available here
        # So we check chat_id only (works for private chats where chat_id == user_id)
        if not _is_authorized(chat_id, chat_id):
            logger.warning(f"[TG][DENY] show_main_menu: chat_id={chat_id} not authorized")
            send_command_response(chat_id, "⛔ Not authorized")
            return False
        
        text = "📋 <b>Main Menu</b>\n\nSelect a section:"
        keyboard = _build_keyboard([
            [{"text": "💼 Portfolio", "callback_data": "menu:portfolio"}],
            [{"text": "📊 Watchlist", "callback_data": "menu:watchlist"}],
            [{"text": "📋 Open Orders", "callback_data": "menu:open_orders"}],
            [{"text": "🎯 Expected Take Profit", "callback_data": "menu:expected_tp"}],
            [{"text": "✅ Executed Orders", "callback_data": "menu:executed_orders"}],
            [{"text": "🔍 Monitoring", "callback_data": "menu:monitoring"}],
            [{"text": "🛑 Kill Switch", "callback_data": "menu:kill_switch"}],
            [{"text": "🤖 Agent Console", "callback_data": "menu:agent"}],
            [{"text": "🛡️ Check SL/TP", "callback_data": "cmd:check_sl_tp"}],
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


def show_watchlist_menu(chat_id: str, db: Optional[Session] = None, page: int = 1, message_id: Optional[int] = None) -> bool:
    """Show paginated watchlist with per-symbol buttons."""
    if db is None:
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


def show_coin_menu(chat_id: str, symbol: str, db: Optional[Session] = None, message_id: Optional[int] = None) -> bool:
    """Show detailed controls for a specific symbol."""
    if db is None:
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
_TOGGLE_CACHE: Dict[str, float] = {}
_TOGGLE_CACHE_TTL = 2.0  # 2 seconds - ignore duplicate toggles within this window

def _handle_watchlist_toggle(chat_id: str, symbol: str, field: str, db: Optional[Session], message_id: Optional[int]) -> None:
    """Generic toggle handler for alert/trade/margin/risk flags."""
    if db is None:
        send_command_response(chat_id, "❌ Database not available.")
        return
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
            cutoff_time = now - _TOGGLE_CACHE_TTL
            to_drop = [k for k, v in _TOGGLE_CACHE.items() if v <= cutoff_time]
            for k in to_drop:
                del _TOGGLE_CACHE[k]
        
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


def _trigger_watchlist_test(chat_id: str, symbol: str, db: Optional[Session]) -> None:
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
            response = http_post(url, json=payload, timeout=30, calling_module="telegram_commands")
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

def send_status_message(chat_id: str, db: Optional[Session] = None) -> bool:
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
                    trade_yes_symbols = [str(getattr(coin, "symbol", "N/A")) for coin in active_trade_coins]
                    logger.debug(f"[TG][STATUS] Found {tracked_coins_with_trade} coins with Trade=YES: {', '.join(trade_yes_symbols)}")
                else:
                    logger.debug("[TG][STATUS] No coins found with Trade=YES")
                
                # Use dictionaries to deduplicate by symbol (keep most recent entry)
                auto_trading_dict = {}
                trade_amounts_dict = {}
                
                # Sort by created_at descending to keep most recent entry for each symbol
                min_datetime = datetime(1970, 1, 1)

                def _coin_created_at(c: Any) -> datetime:
                    ct = getattr(c, "created_at", None)
                    return ct if isinstance(ct, datetime) else min_datetime

                sorted_coins = sorted(
                    active_trade_coins,
                    key=_coin_created_at,
                    reverse=True,
                )
                
                for coin in sorted_coins:
                    symbol = str(getattr(coin, "symbol", None) or "N/A")
                    # Only add if we haven't seen this symbol before (deduplication)
                    if symbol not in auto_trading_dict:
                        margin = "✅" if bool(getattr(coin, "trade_on_margin", False)) else "❌"
                        auto_trading_dict[symbol] = f"{symbol} (Margin: {margin})"
                    
                    # Only add trade amount if we haven't seen this symbol before
                    if symbol not in trade_amounts_dict:
                        amount = _to_float(getattr(coin, "trade_amount_usd", None))
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
                    
                    if last_item and getattr(last_item, "created_at", None):
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


def send_portfolio_message(chat_id: str, db: Optional[Session] = None) -> bool:
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
            realized_pnl, potential_pnl = _calculate_portfolio_pnl(db)
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
                    response = http_get(
                        f"{API_BASE_URL.rstrip('/')}/api/orders/tp-sl-values", timeout=10
                    , calling_module="telegram_commands")
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


def send_signals_message(chat_id: str, db: Optional[Session] = None) -> bool:
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
                signal_price = _to_float(getattr(signal, "entry_price", None) or getattr(signal, "current_price", None))
                
                # Get market data for this symbol (has all technical indicators)
                market_data = db.query(MarketData).filter(MarketData.symbol == symbol).first()
                
                # Get current price from multiple sources
                current_price = 0
                
                # 1. Try MarketData (most reliable source for current price)
                md_price = _to_float(getattr(market_data, "price", None)) if market_data is not None else 0
                if market_data is not None and md_price > 0:
                    current_price = md_price
                
                # 2. Try watchlist as backup
                watchlist_item = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
                wl_price = _to_float(getattr(watchlist_item, "price", None)) if watchlist_item is not None else 0
                if current_price == 0 and watchlist_item is not None and wl_price > 0:
                    current_price = wl_price
                
                # 2. If not in watchlist or no price, try fetching from API
                if current_price == 0:
                    try:
                        # Try Crypto.com API (get-tickers returns all tickers)
                        ticker_url = "https://api.crypto.com/exchange/v1/public/get-tickers"
                        ticker_response = http_get(ticker_url, timeout=10, calling_module="telegram_commands")
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
                
                # Calculate percentage change (ensure scalars for comparison)
                signal_price_f = float(signal_price) if isinstance(signal_price, (int, float)) else _to_float(signal_price)
                current_price_f = float(current_price) if isinstance(current_price, (int, float)) else _to_float(current_price)
                price_change_pct = 0
                change_emoji = ""
                if signal_price_f > 0 and current_price_f > 0:
                    price_change_pct = ((current_price_f - signal_price_f) / signal_price_f) * 100
                    if price_change_pct > 0:
                        change_emoji = "🟢"  # Green for profit
                    elif price_change_pct < 0:
                        change_emoji = "🔴"  # Red for loss
                    else:
                        change_emoji = "⚪"  # Neutral
                
                # Format prices (use scalar values)
                if signal_price_f >= 100:
                    signal_price_str = f"${signal_price_f:,.2f}"
                elif signal_price_f > 0:
                    signal_price_str = f"${signal_price_f:,.4f}"
                else:
                    signal_price_str = "N/A"
                
                if current_price_f >= 100:
                    current_price_str = f"${current_price_f:,.2f}"
                elif current_price_f > 0:
                    current_price_str = f"${current_price_f:,.4f}"
                else:
                    current_price_str = "N/A"
                
                # Get technical parameters from signal, or fallback to market_data
                rsi_val = getattr(signal, "rsi", None) or (getattr(market_data, "rsi", None) if market_data is not None else None)
                ma50 = getattr(signal, "ma50", None) or (getattr(market_data, "ma50", None) if market_data is not None else None)
                ema10 = getattr(signal, "ema10", None) or (getattr(market_data, "ema10", None) if market_data is not None else None)
                atr = getattr(signal, "atr", None) or (getattr(market_data, "atr", None) if market_data is not None else None)
                volume_24h = getattr(signal, "volume_24h", None) or (getattr(market_data, "volume_24h", None) if market_data is not None else None)
                volume_ratio = getattr(signal, "volume_ratio", None) or (getattr(market_data, "volume_ratio", None) if market_data is not None else None)
                
                params = []
                rsi = rsi_val
                if rsi is not None:
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
                created_at = getattr(signal, "created_at", None)
                last_update_at = getattr(signal, "last_update_at", None)
                if isinstance(created_at, datetime):
                    ts = created_at.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S WIB")
                elif isinstance(last_update_at, datetime):
                    ts = last_update_at.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S WIB")
                else:
                    ts = "N/A"
                
                # Get order information
                order_info = ""
                exchange_order_id = getattr(signal, "exchange_order_id", None)
                if exchange_order_id:
                    # Try to find order in database
                    order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.exchange_order_id == exchange_order_id
                    ).first()
                    
                    if order:
                        order_info = f"\n📦 *Order:* {str(getattr(order, 'exchange_order_id', ''))[:12]}..."
                        _status = getattr(order, "status", None)
                        order_info += f"\n   Status: {_status.value if _status is not None and hasattr(_status, 'value') else _status}"
                        order_price_val = _to_float(getattr(order, "price", None))
                        if order_price_val:
                            order_price = f"${order_price_val:,.2f}" if order_price_val >= 100 else f"${order_price_val:,.4f}"
                            order_info += f" | Price: {order_price}"
                    else:
                        status_attr = getattr(signal, "status", None)
                        order_info = f"\n📦 *Order:* {str(exchange_order_id)[:12]}... (Status: {status_attr.value if status_attr and hasattr(status_attr, 'value') else 'PENDING'})"
                else:
                    # No order placed - show reason
                    status_attr = getattr(signal, "status", None)
                    status_val = status_attr.value if status_attr and hasattr(status_attr, "value") else "PENDING"
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
{'   Change: ' + f'{price_change_pct:+.2f}%' if signal_price_f > 0 and current_price_f > 0 else ''}
📊 {params_str}{order_info}"""
        
        logger.info(f"[TG][CMD] /signals")
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build signals: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building signals: {str(e)}")


def send_balance_message(chat_id: str, db: Optional[Session] = None) -> bool:
    """Send balance information"""
    try:
        if db is None:
            send_command_response(chat_id, "❌ Database not available")
            return False
        
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
            send_command_response(chat_id, message)
            return True
        else:
            # Calculate total USD value
            total_usd = 0
            balance_items = []
            
            for bal in balances:
                asset = str(getattr(bal, "asset", "") or "")
                total = _to_float(getattr(bal, "total", None))
                usd_value = _to_float(getattr(bal, "usd_value", None))
                
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
            ok = send_command_response(chat_id, message)
            return bool(ok) if ok is not None else True
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build balance: {e}", exc_info=True)
        send_command_response(chat_id, f"❌ Error building balance: {str(e)}")
        return False


def send_watchlist_message(chat_id: str, db: Optional[Session] = None) -> bool:
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
        
        trade_enabled_coins = [c for c in coins if bool(getattr(c, "trade_enabled", False))]
        disabled_coins = [c for c in coins if not bool(getattr(c, "trade_enabled", False))]
        
        def _format_entry(coin: WatchlistItem) -> str:
            symbol = (str(getattr(coin, "symbol", None) or "N/A")).upper()
            last_price = _to_float(getattr(coin, "price", None))
            buy_target = getattr(coin, "buy_target", None)
            preset = coins_config.get(symbol, {}).get("preset", "swing")
            if "-" not in preset:
                preset = f"{preset}-{(getattr(coin, 'sl_tp_mode', None) or 'conservative')}"
            price_str = (
                f"${last_price:,.2f}" if last_price >= 1
                else (f"${last_price:,.4f}" if last_price > 0 else "N/A")
            )
            buy_target_f = _to_float(buy_target) if buy_target is not None else 0
            target_str = (
                f"${buy_target_f:,.2f}" if buy_target_f >= 1
                else (f"${buy_target_f:,.4f}" if buy_target_f > 0 else "N/A")
            )
            amount_val = _to_float(getattr(coin, "trade_amount_usd", None))
            amount_str = f"${amount_val:,.2f}" if amount_val else "N/A"
            alert_icon = "🔔" if bool(getattr(coin, "alert_enabled", False)) else "🔕"
            trade_icon = "🤖" if bool(getattr(coin, "trade_enabled", False)) else "⛔"
            margin_icon = "⚡" if bool(getattr(coin, "trade_on_margin", False)) else "💤"
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
        send_command_response(chat_id, f"❌ Error building watchlist: {str(e)}")
        return False


def send_open_orders_message(chat_id: str, db: Optional[Session] = None) -> bool:
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
                symbol = str(getattr(order, "symbol", None) or "N/A")
                side_attr = getattr(order, "side", None)
                side = side_attr.value if side_attr and hasattr(side_attr, "value") else "N/A"
                status_attr = getattr(order, "status", None)
                status = status_attr.value if status_attr and hasattr(status_attr, "value") else "N/A"
                quantity = _to_float(getattr(order, "quantity", None))
                price = _to_float(getattr(order, "price", None))
                order_type = str(getattr(order, "order_type", None) or "LIMIT")
                
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
                order_role = getattr(order, "order_role", None)
                order_role_str = str(order_role) if order_role is not None else ""
                if order_type == "STOP_LIMIT" or (order_role is not None and "STOP" in order_role_str):
                    type_emoji = "🛑"
                elif order_type == "TAKE_PROFIT_LIMIT" or (order_role is not None and "TAKE_PROFIT" in order_role_str):
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


def send_check_sl_tp_message(chat_id: str, db: Optional[Session] = None) -> bool:
    """Check and display open orders/positions without SL/TP protection"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        from app.services.sl_tp_checker import sl_tp_checker_service
        
        logger.info(f"[TG][CMD] Checking for positions without SL/TP...")
        
        # Check positions for missing SL/TP
        result = sl_tp_checker_service.check_positions_for_sl_tp(db)
        
        positions_missing = result.get('positions_missing_sl_tp', [])
        total_positions = result.get('total_positions', 0)
        
        if not positions_missing:
            message = f"""🛡️ <b>SL/TP Check</b>

✅ All positions are protected!

Total positions checked: {total_positions}
All positions have both SL and TP orders."""
        else:
            message = f"""🛡️ <b>SL/TP Check</b>

⚠️ <b>{len(positions_missing)} position(s) missing protection:</b>

"""
            for pos in positions_missing:
                symbol = pos.get('symbol', 'N/A')
                balance = pos.get('balance', 0)
                has_sl = pos.get('has_sl', False)
                has_tp = pos.get('has_tp', False)
                sl_price = pos.get('sl_price')
                tp_price = pos.get('tp_price')
                
                # Format balance
                if balance >= 1:
                    balance_str = f"{balance:,.4f}"
                elif balance >= 0.000001:
                    balance_str = f"{balance:,.6f}"
                else:
                    balance_str = f"{balance:.8f}"
                
                # Status indicators
                sl_status = "✅" if has_sl else "❌"
                tp_status = "✅" if has_tp else "❌"
                
                missing = []
                if not has_sl:
                    missing.append("SL")
                if not has_tp:
                    missing.append("TP")
                
                message += f"""🔸 <b>{symbol}</b>
  Balance: {balance_str}
  SL: {sl_status} | TP: {tp_status}
  Missing: {', '.join(missing) if missing else 'None'}
"""
                if sl_price:
                    message += f"  SL Price: ${sl_price:,.4f}\n"
                if tp_price:
                    message += f"  TP Price: ${tp_price:,.4f}\n"
                message += "\n"
            
            message += f"\nTotal positions: {total_positions}"
            message += f"\nProtected: {total_positions - len(positions_missing)}"
            message += f"\nUnprotected: {len(positions_missing)}"
            
            # Add buttons to create SL/TP for each position
            keyboard_rows = []
            for pos in positions_missing[:5]:  # Limit to 5 buttons
                symbol = pos.get('symbol', '')
                if symbol:
                    keyboard_rows.append([
                        {"text": f"🛡️ Create SL/TP {symbol}", "callback_data": f"create_sl_tp_{symbol}"}
                    ])
            
            if keyboard_rows:
                keyboard_rows.append([{"text": "🏠 Main Menu", "callback_data": "menu:main"}])
                keyboard = _build_keyboard(keyboard_rows)
                return _send_menu_message(chat_id, message, keyboard)
        
        logger.info(f"[TG][CMD] /check_sl_tp - Found {len(positions_missing)} positions missing SL/TP")
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to check SL/TP: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error checking SL/TP: {str(e)}")


def send_executed_orders_message(chat_id: str, db: Optional[Session] = None) -> bool:
    """Send executed orders list"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
        from datetime import timezone
        
        # Get executed orders (FILLED status) - show at least last 5 orders
        # Use COALESCE to handle NULL exchange_create_time (fallback to created_at or updated_at)
        from sqlalchemy import func
        
        # Filter out test/simulated orders:
        # Only exclude orders with exchange_order_id starting with "dry_" (dry_run orders)
        # Note: Some real orders may have NULL timestamps, so we don't filter on that
        
        # Base filter: FILLED status, exclude dry_run orders only
        base_filter = and_(
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ~ExchangeOrder.exchange_order_id.like("dry_%")  # Exclude dry_run orders (use ~ for NOT)
        )
        
        # Always get the last 5 orders regardless of time
        # This ensures we show at least 5 orders even if some are older than 24h
        # Use updated_at as final fallback since it has server_default and always has a value
        # NULLS LAST ensures orders with NULL timestamps appear after those with valid timestamps
        from sqlalchemy import nullslast
        executed_orders = db.query(ExchangeOrder).filter(
            base_filter
        ).order_by(
            nullslast(func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at, ExchangeOrder.updated_at).desc())
        ).limit(5).all()
        
        # Check how many of these are from last 24h to set the filter label
        yesterday = datetime.now(timezone.utc) - timedelta(hours=24)
        orders_in_24h = []
        for o in executed_orders:
            order_time = getattr(o, "exchange_create_time", None) or getattr(o, "created_at", None) or getattr(o, "updated_at", None)
            if isinstance(order_time, datetime) and order_time >= yesterday:
                orders_in_24h.append(o)
        
        if len(orders_in_24h) >= 5:
            time_filter = "Last 24h"
        elif len(executed_orders) > 0:
            time_filter = "Last 5 orders"
        else:
            time_filter = "Last 24h"
        
        if not executed_orders:
            message = f"""✅ <b>Executed Orders ({time_filter})</b>

No executed orders found."""
        else:
            # Calculate total P&L
            total_pnl = 0
            
            message = f"""✅ <b>Executed Orders ({time_filter})</b>

📊 <b>Total: {len(executed_orders)} order(s)</b>"""
            
            for order in executed_orders:
                symbol = str(getattr(order, "symbol", None) or "N/A")
                side_attr = getattr(order, "side", None)
                side = side_attr.value if side_attr and hasattr(side_attr, "value") else "N/A"
                quantity = _to_float(getattr(order, "quantity", None))
                price = _to_float(getattr(order, "price", None))
                
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
                
                # Format timestamp - use COALESCE logic (exchange_create_time, created_at, updated_at)
                time_str = "N/A"
                try:
                    ts = getattr(order, "exchange_create_time", None) or getattr(order, "created_at", None) or getattr(order, "updated_at", None)
                    if ts is not None:
                        if isinstance(ts, datetime):
                            ts_utc = ts
                        elif isinstance(ts, (int, float)):
                            ts_val = float(ts)
                            ts_utc = datetime.fromtimestamp(ts_val / 1000 if ts_val > 1e10 else ts_val, tz=timezone.utc)
                        else:
                            ts_utc = ts
                        
                        # Ensure timezone aware
                        if ts_utc.tzinfo is None:
                            ts_utc = ts_utc.replace(tzinfo=timezone.utc)
                        
                        tz = pytz.timezone("Asia/Makassar")  # Bali time
                        ts_local = ts_utc.astimezone(tz)
                        time_str = ts_local.strftime("%Y-%m-%d %H:%M")
                except Exception as e:
                    logger.debug(f"[TG] Error formatting timestamp for order {order.exchange_order_id}: {e}")
                    time_str = "N/A"
                
                # Determine order type
                order_type_str = "MARKET"
                order_type_attr = getattr(order, "order_type", None)
                if order_type_attr is not None:
                    order_type_upper = str(order_type_attr).upper()
                    if "MARKET" in order_type_upper:
                        order_type_str = "MARKET"
                    elif "LIMIT" in order_type_upper:
                        order_type_str = "LIMIT"
                    elif "STOP" in order_type_upper:
                        order_type_str = "STOP"
                
                # Check if it's TP/SL order
                is_tp_sl = False
                tp_sl_type = ""
                order_role_attr = getattr(order, "order_role", None)
                if order_role_attr is not None:
                    role_upper = str(order_role_attr).upper()
                    if "TAKE_PROFIT" in role_upper:
                        is_tp_sl = True
                        tp_sl_type = "TP"
                        order_type_str = "TP"
                    elif "STOP_LOSS" in role_upper:
                        is_tp_sl = True
                        tp_sl_type = "SL"
                        order_type_str = "SL"
                
                # Calculate profit/loss for TP/SL orders
                pnl_str = ""
                if is_tp_sl:
                    try:
                        # Find entry order (parent order) - try parent_order_id first, then oco_group_id
                        entry_order = None
                        parent_order_id = getattr(order, "parent_order_id", None)
                        if parent_order_id:
                            entry_order = db.query(ExchangeOrder).filter(
                                ExchangeOrder.exchange_order_id == parent_order_id
                            ).first()
                        
                        oco_group_id = getattr(order, "oco_group_id", None)
                        if not entry_order and oco_group_id is not None:
                            # Find the PARENT order in the same OCO group
                            entry_order = db.query(ExchangeOrder).filter(
                                ExchangeOrder.oco_group_id == oco_group_id,
                                ExchangeOrder.order_role == "PARENT",
                                ExchangeOrder.symbol == symbol
                            ).first()
                        
                        # If still not found, try to find the most recent BUY order for this symbol (for SELL TP/SL)
                        # or most recent SELL order (for BUY TP/SL in short positions)
                        if not entry_order:
                            if side == "SELL":
                                # TP/SL SELL - find most recent BUY order for this symbol
                                entry_order = db.query(ExchangeOrder).filter(
                                    ExchangeOrder.symbol == symbol,
                                    ExchangeOrder.side == OrderSideEnum.BUY,
                                    ExchangeOrder.status == OrderStatusEnum.FILLED,
                                    ExchangeOrder.order_role != "STOP_LOSS",
                                    ExchangeOrder.order_role != "TAKE_PROFIT"
                                ).order_by(func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at, ExchangeOrder.updated_at).desc()).first()
                            elif side == "BUY":
                                # TP/SL BUY (for short positions) - find most recent SELL order
                                entry_order = db.query(ExchangeOrder).filter(
                                    ExchangeOrder.symbol == symbol,
                                    ExchangeOrder.side == OrderSideEnum.SELL,
                                    ExchangeOrder.status == OrderStatusEnum.FILLED,
                                    ExchangeOrder.order_role != "STOP_LOSS",
                                    ExchangeOrder.order_role != "TAKE_PROFIT"
                                ).order_by(func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at, ExchangeOrder.updated_at).desc()).first()
                        
                        if entry_order:
                            entry_price = _to_float(getattr(entry_order, "avg_price", None) or getattr(entry_order, "price", None))
                            exit_price = _to_float(getattr(order, "avg_price", None) or getattr(order, "price", None))
                            
                            if entry_price > 0 and exit_price > 0 and quantity > 0:
                                _entry_side = getattr(entry_order, "side", None)
                                is_entry_buy = _entry_side is not None and _entry_side == OrderSideEnum.BUY
                                is_entry_sell = _entry_side is not None and _entry_side == OrderSideEnum.SELL
                                if side == "SELL" and is_entry_buy:
                                    pnl = (exit_price - entry_price) * quantity
                                    pnl_pct = ((exit_price - entry_price) / entry_price) * 100
                                elif side == "BUY" and is_entry_sell:
                                    # TP/SL BUY order closing a SELL position (short)
                                    pnl = (entry_price - exit_price) * quantity
                                    pnl_pct = ((entry_price - exit_price) / entry_price) * 100
                                else:
                                    # Same side - might be error, skip P&L
                                    pnl = 0
                                    pnl_pct = 0
                                
                                if pnl != 0:
                                    pnl_emoji = "📈" if pnl > 0 else "📉"
                                    pnl_str = f"\n  {pnl_emoji} P&L: ${pnl:,.2f} ({pnl_pct:+.2f}%)"
                    except Exception as e:
                        logger.debug(f"[TG] Error calculating P&L for order {order.exchange_order_id}: {e}")
                
                side_emoji = "🟢" if side == "BUY" else "🔴"
                order_type_emoji = "🎯" if is_tp_sl else "📊"
                
                message += f"""

{side_emoji} <b>{symbol}</b> {side} | {order_type_emoji} {order_type_str}
  Qty: {quantity_str} | Price: {price_str}
  Value: {value_str}
  Date: {time_str}{pnl_str}"""
            
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


def send_expected_take_profit_message(chat_id: str, db: Optional[Session] = None) -> bool:
    """Send expected take profit summary for all open positions - Reference Specification Section 6"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Call API endpoint to get expected take profit summary
        try:
            response = http_get(
                f"{API_BASE_URL.rstrip('/')}/api/dashboard/expected-take-profit", timeout=10
            , calling_module="telegram_commands")
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


def show_portfolio_menu(chat_id: str, db: Optional[Session] = None, message_id: Optional[int] = None) -> bool:
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


def show_open_orders_menu(chat_id: str, db: Optional[Session] = None, message_id: Optional[int] = None) -> bool:
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


def show_expected_tp_menu(chat_id: str, db: Optional[Session] = None, message_id: Optional[int] = None) -> bool:
    """Show expected take profit sub-menu with options"""
    try:
        # Authorization check - use helper function
        if not _is_authorized(chat_id, chat_id):
            logger.warning(f"[TG][DENY] show_expected_tp_menu: chat_id={chat_id} not authorized")
            send_command_response(chat_id, "⛔ Not authorized")
            return False
        
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


def show_executed_orders_menu(chat_id: str, db: Optional[Session] = None, message_id: Optional[int] = None) -> bool:
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


def show_monitoring_menu(chat_id: str, db: Optional[Session] = None, message_id: Optional[int] = None) -> bool:
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


def show_kill_switch_menu(chat_id: str, db: Optional[Session] = None, message_id: Optional[int] = None) -> bool:
    """Show kill switch sub-menu with status and controls"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Get current kill switch status
        from app.utils.trading_guardrails import _get_telegram_kill_switch_status
        from app.utils.live_trading import get_live_trading_status
        
        try:
            kill_switch_on = _get_telegram_kill_switch_status(db)
            live_enabled = get_live_trading_status(db)
            
            status_emoji = "🔴" if kill_switch_on else "🟢"
            live_emoji = "🟢" if live_enabled else "🔴"
            
            text = f"🛑 <b>Kill Switch</b>\n\n"
            text += f"{status_emoji} <b>Kill Switch:</b> {'ON' if kill_switch_on else 'OFF'}\n"
            text += f"{live_emoji} <b>Live Trading:</b> {'ON' if live_enabled else 'OFF'}\n\n"
            
            if kill_switch_on:
                text += "⛔ <b>TRADING IS DISABLED</b>\n"
                text += "No orders will be placed.\n\n"
            elif not live_enabled:
                text += "⛔ <b>TRADING IS DISABLED</b>\n"
                text += "Live toggle is OFF.\n\n"
            else:
                text += "✅ Trading is enabled\n"
                text += "(subject to Trade Yes per symbol)\n\n"
        except Exception as e:
            logger.warning(f"[TG][KILL] Error getting status: {e}")
            text = "🛑 <b>Kill Switch</b>\n\n"
            text += "⚠️ Could not retrieve current status.\n\n"
        
        text += "Select an action:"
        
        keyboard = _build_keyboard([
            [{"text": "🔴 Turn ON (Disable Trading)", "callback_data": "kill:on"}],
            [{"text": "🟢 Turn OFF (Enable Trading)", "callback_data": "kill:off"}],
            [{"text": "📊 Show Status", "callback_data": "kill:status"}],
            [{"text": "🔙 Back to Menu", "callback_data": "menu:main"}],
        ])
        
        return _send_or_edit_menu(chat_id, text, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing kill switch menu: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error showing kill switch menu: {str(e)}")


def _format_scheduler_health_for_console() -> str:
    """Build a short scheduler health block from recent agent activity (last cycle, last auto-exec, last approval request, last failure, pending count)."""
    try:
        from app.services.agent_activity_log import get_recent_agent_events
        events = get_recent_agent_events(limit=200)
    except Exception:
        return "📊 <b>Scheduler</b>: —"
    last_cycle = None
    last_auto = None
    last_approval = None
    last_failed = None
    for ev in events:
        t = str(ev.get("event_type") or "")
        if t.startswith("scheduler_") and last_cycle is None:
            last_cycle = ev
        if t == "scheduler_auto_executed" and last_auto is None:
            last_auto = ev
        if t == "scheduler_approval_requested" and last_approval is None:
            last_approval = ev
        if t == "scheduler_cycle_failed" and last_failed is None:
            last_failed = ev
    def _ts(ev: Optional[dict]) -> str:
        if not ev:
            return "—"
        ts = str(ev.get("timestamp") or "")[:19].replace("T", " ")
        title = str(ev.get("task_title") or "").strip()[:50]
        if title:
            return f"{ts} ({title}…)" if len(str(ev.get("task_title") or "")) > 50 else f"{ts} ({title})"
        return ts
    pending_n = 0
    try:
        from app.services.agent_telegram_approval import get_pending_approvals
        pending_n = len(get_pending_approvals() or [])
    except Exception:
        pass
    lines = [
        "📊 <b>Scheduler</b>",
        f"Last cycle: {_ts(last_cycle)}",
        f"Last auto-exec: {_ts(last_auto)}",
        f"Last approval request: {_ts(last_approval)}",
        f"Last failure: {_ts(last_failed)}",
        f"Pending approvals: {pending_n}",
    ]
    return "\n".join(lines)


def show_agent_console(chat_id: str, message_id: Optional[int] = None) -> bool:
    """Show a compact agent console with scheduler health, recent activity, approvals, and failures."""
    try:
        if not _is_authorized(chat_id, chat_id):
            logger.warning(f"[TG][DENY] show_agent_console: chat_id={chat_id} not authorized")
            send_command_response(chat_id, "⛔ Not authorized")
            return False

        scheduler_block = _format_scheduler_health_for_console()
        text = f"🤖 <b>Agent Console</b>\n\n{scheduler_block}\n\nSelect a view:"
        keyboard = _build_keyboard([
            [{"text": "🔍 Investigate", "callback_data": "cmd:investigate"}, {"text": "🔧 Runtime Check", "callback_data": "cmd:runtime-check"}],
            [{"text": "🕘 Recent Activity", "callback_data": "agent:recent"}],
            [{"text": "⏳ Pending Approvals", "callback_data": "agent:pending"}],
            [{"text": "⚠️ Last Failures", "callback_data": "agent:failures"}],
            [
                {"text": "🔄 Refresh", "callback_data": "agent:main"},
                {"text": "🏠 Main Menu", "callback_data": "menu:main"},
            ],
        ])
        return _send_or_edit_menu(chat_id, text, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing agent console: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error showing agent console: {str(e)}")


def send_recent_agent_activity(chat_id: str, limit: int = 5) -> bool:
    """Send a compact recent activity summary from the agent activity log."""
    try:
        if not _is_authorized(chat_id, chat_id):
            logger.warning(f"[TG][DENY] send_recent_agent_activity: chat_id={chat_id} not authorized")
            return send_command_response(chat_id, "⛔ Not authorized")

        from app.services.agent_activity_log import get_recent_agent_events

        events = get_recent_agent_events(limit=limit)
        if not events:
            return send_command_response(chat_id, "🤖 <b>Recent Agent Activity</b>\n\nNo recent agent activity.")

        lines = ["🤖 <b>Recent Agent Activity</b>", ""]
        for event in events[:limit]:
            timestamp = str(event.get("timestamp") or "")[:19].replace("T", " ")
            event_type = str(event.get("event_type") or "unknown")
            task_title = str(event.get("task_title") or "(no title)")
            lines.append(f"• <code>{timestamp}</code> | <b>{event_type}</b> | {task_title[:120]}")
        return send_command_response(chat_id, "\n".join(lines))
    except Exception as e:
        logger.error(f"[TG][ERROR] Error sending recent agent activity: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error reading agent activity: {str(e)}")


def send_pending_agent_approvals(chat_id: str, message_id: Optional[int] = None) -> bool:
    """Send (or edit to) pending approval list with a clickable row per item (agent_detail:<task_id>)."""
    try:
        if not _is_authorized(chat_id, chat_id):
            logger.warning(f"[TG][DENY] send_pending_agent_approvals: chat_id={chat_id} not authorized")
            return send_command_response(chat_id, "⛔ Not authorized")

        from app.services.agent_telegram_approval import get_pending_approvals

        approvals = get_pending_approvals()
        if not approvals:
            text = "⏳ <b>Pending Agent Approvals</b>\n\nNo pending approvals."
            keyboard = _build_keyboard([[{"text": "🔙 Back to Console", "callback_data": "agent:main"}]])
            return _send_or_edit_menu(chat_id, text, keyboard, message_id)

        lines = ["⏳ <b>Pending Agent Approvals</b>", ""]
        rows = []
        for item in approvals:
            task_id = str(item.get("task_id") or "")
            short_id = f"{task_id[:8]}..." if len(task_id) > 8 else task_id
            title = str(item.get("task_title") or "(no title)")
            type_label = str(item.get("task_type_label") or "Task")
            requested_at = str(item.get("requested_at") or "")[:19].replace("T", " ")
            lines.append(f"• <b>{type_label}</b> · {title[:70]}{'…' if len(title) > 70 else ''}\n  <code>{short_id}</code> {requested_at}")
            if task_id and len(f"agent_detail:{task_id}") <= 64:
                rows.append([{"text": f"📋 View {short_id}", "callback_data": f"agent_detail:{task_id}"}])
        rows.append([{"text": "🔙 Back to Console", "callback_data": "agent:main"}])
        text = "\n".join(lines)
        keyboard = _build_keyboard(rows)
        return _send_or_edit_menu(chat_id, text, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Error sending pending agent approvals: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error reading pending approvals: {str(e)}")


def send_approval_request_detail(chat_id: str, task_id: str, message_id: Optional[int] = None) -> bool:
    """Fetch approval detail and send (or edit to) a Telegram-friendly detail view with Approve / Deny / Back to Pending."""
    try:
        if not _is_authorized(chat_id, chat_id):
            logger.warning(f"[TG][DENY] send_approval_request_detail: chat_id={chat_id} not authorized")
            return send_command_response(chat_id, "⛔ Not authorized")

        from app.services.agent_telegram_approval import (
            get_approval_request_detail,
            PREFIX_APPROVE,
            PREFIX_DENY,
            PREFIX_EXECUTE,
        )

        detail = get_approval_request_detail(task_id)
        if not detail:
            text = f"❌ Approval request not found for task <code>{task_id[:20]}...</code>."
            keyboard = _build_keyboard([[{"text": "🔙 Back to Pending", "callback_data": "agent_back_pending"}]])
            return _send_or_edit_menu(chat_id, text, keyboard, message_id)

        task_title = detail.get("task_title") or "(no title)"
        status = detail.get("status") or "pending"
        requested_at = str(detail.get("requested_at") or "")[:19].replace("T", " ")
        approved_by = str(detail.get("approved_by") or "-")
        decision_at = str(detail.get("decision_at") or "-")[:19].replace("T", " ") if detail.get("decision_at") else "-"
        summary = (detail.get("approval_summary") or "").strip() or "-"
        project = str(detail.get("project") or "-")
        task_type = str(detail.get("type") or "-")
        priority = str(detail.get("priority") or "-")
        source = str(detail.get("source") or "-")
        selection_reason = (detail.get("selection_reason") or "").strip() or "-"
        what_will_happen = (detail.get("what_will_happen") or "").strip() or "The agent will run the selected callback for this task."
        task_type_label = (detail.get("task_type_label") or "").strip() or "Agent task"
        repo_area = detail.get("repo_area") or {}
        area_name = str(repo_area.get("area_name") or "").strip() or "-"
        execution_status = (detail.get("execution_status") or "not_started").lower()
        execution_started_at = str(detail.get("execution_started_at") or "")[:19].replace("T", " ") if detail.get("execution_started_at") else "-"
        executed_at = str(detail.get("executed_at") or "")[:19].replace("T", " ") if detail.get("executed_at") else "-"

        lines = [
            "🔐 <b>Approval request detail</b>",
            "",
            f"<b>📌 If you approve</b>\n{what_will_happen}",
            "",
            f"<b>Task:</b> {task_title[:300]}",
            f"<b>Type:</b> {task_type_label}",
            f"<b>Status:</b> {status}",
            f"<b>Execution:</b> {execution_status}",
            f"<b>Requested:</b> {requested_at}",
            f"<b>Project:</b> {project} · <b>Priority:</b> {priority}",
            f"<b>Area:</b> {area_name}",
            "",
            "<b>Full summary</b>",
            "<pre>" + (summary[:1500].replace("<", "&lt;") if summary else "-") + "</pre>",
        ]
        if status == "pending":
            lines.append("")
            lines.append("Approved by: - | Decision at: -")
        else:
            lines.append("")
            lines.append(f"Approved by: {approved_by} | Decision at: {decision_at}")
        if execution_status and execution_status != "not_started":
            lines.append("")
            lines.append(f"Execution started: {execution_started_at} | Executed at: {executed_at}")

        text = "\n".join(lines)
        if len(text) > 4090:
            text = text[:4087] + "..."

        if (status or "").lower() == "pending":
            keyboard = _build_keyboard([
                [
                    {"text": "✅ Approve", "callback_data": f"{PREFIX_APPROVE}{task_id}"},
                    {"text": "❌ Deny", "callback_data": f"{PREFIX_DENY}{task_id}"},
                ],
                [{"text": "🔙 Back to Pending", "callback_data": "agent_back_pending"}],
            ])
        elif (status or "").lower() == "approved":
            if execution_status == "running":
                keyboard = _build_keyboard([[{"text": "🔙 Back to Pending", "callback_data": "agent_back_pending"}]])
            elif execution_status == "completed":
                keyboard = _build_keyboard([[{"text": "🔙 Back to Pending", "callback_data": "agent_back_pending"}]])
            elif execution_status == "failed":
                keyboard = _build_keyboard([
                    [{"text": "🔄 Retry Execute", "callback_data": f"{PREFIX_EXECUTE}{task_id}"}],
                    [{"text": "🔙 Back to Pending", "callback_data": "agent_back_pending"}],
                ])
            else:
                keyboard = _build_keyboard([
                    [{"text": "▶️ Execute Now", "callback_data": f"{PREFIX_EXECUTE}{task_id}"}],
                    [{"text": "🔙 Back to Pending", "callback_data": "agent_back_pending"}],
                ])
        else:
            keyboard = _build_keyboard([[{"text": "🔙 Back to Pending", "callback_data": "agent_back_pending"}]])

        return _send_or_edit_menu(chat_id, text, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Error sending approval request detail: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error loading approval detail: {str(e)}")


def _format_execution_result_message(result: dict) -> str:
    """Format execute_prepared_task_from_telegram_decision result for Telegram."""
    if not result:
        return "⚠️ No result returned."
    executed = bool(result.get("executed"))
    reason = str(result.get("reason") or "").strip()
    exec_result = result.get("execution_result") or {}
    task_title = str(exec_result.get("task_title") or "").strip() or "(no title)"
    final_status = str(exec_result.get("final_status") or "").strip()
    success = exec_result.get("success") if isinstance(exec_result.get("success"), bool) else None
    execution_started = bool(result.get("execution_started"))
    state_before = result.get("execution_state_before") or {}
    state_after = result.get("execution_state_after") or {}
    status_before = str(state_before.get("execution_status") or "—")
    status_after = str(state_after.get("execution_status") or "—")

    lines = [
        "▶️ <b>Execution result</b>",
        "",
        f"<b>Task:</b> {task_title[:200]}",
        f"<b>State before:</b> {status_before}",
        f"<b>Execution started:</b> {'Yes' if execution_started else 'No'}",
        f"<b>Ran:</b> {'Yes' if executed else 'No'}",
        f"<b>State after:</b> {status_after}",
        f"<b>Reason:</b> {reason[:300]}",
    ]
    if final_status:
        lines.append(f"<b>Final status:</b> {final_status}")
    if success is not None:
        lines.append(f"<b>Success:</b> {'Yes' if success else 'No'}")
    return "\n".join(lines)


def send_recent_agent_failures(chat_id: str, limit: int = 5) -> bool:
    """Send recent failure-like activity events for fast Telegram triage."""
    try:
        if not _is_authorized(chat_id, chat_id):
            logger.warning(f"[TG][DENY] send_recent_agent_failures: chat_id={chat_id} not authorized")
            return send_command_response(chat_id, "⛔ Not authorized")

        from app.services.agent_activity_log import get_recent_agent_events

        events = get_recent_agent_events(limit=max(limit * 6, 30))
        failures = [
            event for event in events
            if str(event.get("event_type") or "") in {"execution_failed", "validation_failed", "execution_skipped"}
        ][:limit]

        if not failures:
            return send_command_response(chat_id, "⚠️ <b>Recent Agent Failures</b>\n\nNo recent failures.")

        lines = ["⚠️ <b>Recent Agent Failures</b>", ""]
        for event in failures:
            timestamp = str(event.get("timestamp") or "")[:19].replace("T", " ")
            event_type = str(event.get("event_type") or "unknown")
            task_title = str(event.get("task_title") or "(no title)")
            lines.append(f"• <code>{timestamp}</code> | <b>{event_type}</b> | {task_title[:120]}")
        return send_command_response(chat_id, "\n".join(lines))
    except Exception as e:
        logger.error(f"[TG][ERROR] Error sending recent agent failures: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error reading recent failures: {str(e)}")


def send_system_monitoring_message(chat_id: str, db: Optional[Session] = None, message_id: Optional[int] = None) -> bool:
    """Send system monitoring information - Reference Specification Section 8.1"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Get system health - try direct call first (more reliable), fallback to HTTP
        health_data = {}
        try:
            # Try direct call to health service (we're in the same process)
            from app.services.system_health import get_system_health
            if not db:
                logger.warning(f"[TG][MONITORING] No DB session available for health check")
            health_data = get_system_health(db)
            logger.info(f"[TG][MONITORING] Health data retrieved directly: global_status={health_data.get('global_status')}, components={list(health_data.keys())}")
            logger.debug(f"[TG][MONITORING] Full health data: {json.dumps(health_data, indent=2, default=str)}")
        except Exception as direct_err:
            logger.warning(f"[TG][MONITORING] Direct health call failed: {direct_err}, trying HTTP fallback", exc_info=True)
            try:
                # Fallback to HTTP call
                health_url = f"{API_BASE_URL.rstrip('/')}/api/health/system"
                logger.info(f"[TG][MONITORING] Attempting HTTP health check: {health_url}")
                response = http_get(
                    health_url,
                    timeout=10,
                    calling_module="telegram_commands"
                )
                if response.status_code == 200:
                    health_data = response.json()
                    logger.info(f"[TG][MONITORING] Health API HTTP response: global_status={health_data.get('global_status')}, components={list(health_data.keys())}")
                    logger.debug(f"[TG][MONITORING] Full HTTP health data: {json.dumps(health_data, indent=2, default=str)}")
                else:
                    logger.warning(f"[TG][MONITORING] Health API returned status {response.status_code}, response: {response.text[:200]}")
                    health_data = {}
            except Exception as http_err:
                logger.error(f"[TG][MONITORING] Both direct and HTTP health calls failed. Direct: {direct_err}, HTTP: {http_err}", exc_info=True)
                health_data = {}
        
        # Build message from health data
        message = "🖥️ <b>System Monitoring</b>\n\n"
        
        # If health data is empty, show error and basic info
        if not health_data:
            message += "⚠️ <b>Health check unavailable</b>\n\n"
            message += "❌ <b>Backend:</b> unknown\n"
            message += "❌ <b>Database:</b> " + ("connected" if db else "unknown") + "\n"
            message += "❌ <b>Exchange API:</b> unknown\n"
            message += "🔴 <b>Trading Bot:</b> unknown\n"
            # Still show mode using proper utility function
            from app.utils.live_trading import get_live_trading_status
            try:
                live_trading = get_live_trading_status(db)
            except Exception as e:
                logger.warning(f"[TG][MONITORING] Error getting live trading status: {e}")
                # Fallback to environment variable
                import os
                live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
            mode_emoji = "🟢" if live_trading else "🔴"
            mode_text = "LIVE" if live_trading else "DRY RUN"
            message += f"{mode_emoji} <b>Mode:</b> {mode_text}\n"
            message += "\n⚠️ Could not retrieve health data. Check logs for details.\n"
        else:
            # Map health data structure to display format
            # Health endpoint returns: market_data, market_updater, signal_monitor, telegram, trade_system
            
            # Backend status (use global_status as overall backend health)
            global_status = health_data.get("global_status", "unknown")
            backend_emoji = "✅" if global_status == "PASS" else "⚠️" if global_status == "WARN" else "❌"
            backend_status_text = "healthy" if global_status == "PASS" else "unhealthy" if global_status == "FAIL" else "warning"
            message += f"{backend_emoji} <b>Backend:</b> {backend_status_text}\n"
            
            # Database status (check if we can query - if db session exists, assume connected)
            # Note: We don't have explicit DB health in the endpoint, so infer from context
            db_status = "connected" if db else "unknown"
            db_emoji = "✅" if db_status == "connected" else "❌"
            message += f"{db_emoji} <b>Database:</b> {db_status}\n"
            
            # Exchange API status (map from market_data status)
            market_data = health_data.get("market_data", {})
            exchange_status_raw = market_data.get("status", "unknown")
            exchange_status = "connected" if exchange_status_raw == "PASS" else "disconnected" if exchange_status_raw == "FAIL" else "unknown"
            exchange_emoji = "✅" if exchange_status == "connected" else "❌"
            message += f"{exchange_emoji} <b>Exchange API:</b> {exchange_status}\n"
            
            # Trading bot status (map from signal_monitor status)
            signal_monitor = health_data.get("signal_monitor", {})
            bot_status_raw = signal_monitor.get("status", "unknown")
            is_running = signal_monitor.get("is_running", False)
            bot_status = "running" if bot_status_raw == "PASS" and is_running else "stopped" if bot_status_raw == "FAIL" else "unknown"
            bot_emoji = "🟢" if bot_status == "running" else "🔴"
            message += f"{bot_emoji} <b>Trading Bot:</b> {bot_status}\n"
            
            # Live trading mode - use proper utility function that checks DB first, then env
            from app.utils.live_trading import get_live_trading_status
            try:
                live_trading = get_live_trading_status(db)
            except Exception as e:
                logger.warning(f"[TG][MONITORING] Error getting live trading status: {e}")
                # Fallback to environment variable
                import os
                live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
            mode_emoji = "🟢" if live_trading else "🔴"
            mode_text = "LIVE" if live_trading else "DRY RUN"
            message += f"{mode_emoji} <b>Mode:</b> {mode_text}\n"
        
        # Additional health details
        if health_data:
            timestamp = health_data.get("timestamp", "")
            if timestamp:
                # Parse and format timestamp
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    formatted_time = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                    message += f"\n🕐 <b>Last Check:</b> {formatted_time}\n"
                except:
                    message += f"\n🕐 <b>Last Check:</b> {timestamp}\n"
            
            # Show component statuses if available
            components = []
            if market_data.get("status") != "PASS":
                components.append(f"Market Data: {market_data.get('status', 'unknown')}")
            signal_status = signal_monitor.get("status", "unknown")
            if signal_status != "PASS":
                components.append(f"Signal Monitor: {signal_status}")
            telegram_status = health_data.get("telegram", {}).get("status", "unknown")
            if telegram_status != "PASS":
                components.append(f"Telegram: {telegram_status}")
            
            if components:
                message += f"\n⚠️ <b>Issues:</b> {', '.join(components)}\n"
        
        keyboard = _build_keyboard([
            [{"text": "🔄 Refresh", "callback_data": "monitoring:system"}],
            [{"text": "🔙 Back to Monitoring", "callback_data": "menu:monitoring"}],
        ])
        
        return _send_or_edit_menu(chat_id, message, keyboard, message_id)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build system monitoring: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building system monitoring: {str(e)}")


def send_throttle_message(chat_id: str, db: Optional[Session] = None, message_id: Optional[int] = None) -> bool:
    """Send throttle information (recent Telegram messages) - Reference Specification Section 8.2"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Get recent Telegram messages from API
        try:
            response = http_get(
                f"{API_BASE_URL.rstrip('/')}/api/monitoring/telegram-messages",
                params={"limit": 20},
                timeout=10,
                calling_module="telegram_commands"
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


def send_workflows_monitoring_message(chat_id: str, db: Optional[Session] = None, message_id: Optional[int] = None) -> bool:
    """Send workflow monitoring information - Reference Specification Section 8.3"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Get workflow status from API
        try:
            response = http_get(
                f"{API_BASE_URL.rstrip('/')}/api/monitoring/workflows",
                timeout=10,
                calling_module="telegram_commands"
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


def send_blocked_messages_message(chat_id: str, db: Optional[Session] = None, message_id: Optional[int] = None) -> bool:
    """Send blocked Telegram messages - Reference Specification Section 8.4"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Get blocked messages from API (filter for blocked=True)
        try:
            response = http_get(
                f"{API_BASE_URL.rstrip('/')}/api/monitoring/telegram-messages",
                params={"blocked": True, "limit": 20},
                timeout=10,
                calling_module="telegram_commands"
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
                # Use 'message' field (not 'content') as returned by the API
                msg_content = msg.get("message", "")
                # Truncate long messages
                content = msg_content[:100] + "..." if len(msg_content) > 100 else msg_content
                # Use 'throttle_reason' or 'message' for reason
                reason = msg.get("throttle_reason") or msg.get("reason") or "Unknown"
                symbol = msg.get("symbol", "N/A")
                
                message += f"🚫 <b>{symbol}</b> - {timestamp}\n"
                message += f"   Reason: {reason}\n"
                message += f"   {content}\n\n"
        
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


def send_alerts_list_message(chat_id: str, db: Optional[Session] = None) -> bool:
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
                _sym = getattr(coin, "symbol", None)
                symbol = str(_sym) if _sym is not None else "N/A"
                last_price = _to_float(getattr(coin, "price", None))
                buy_target_raw = getattr(coin, "buy_target", None)
                buy_target = _to_float(buy_target_raw) if buy_target_raw is not None else 0.0
                _te = getattr(coin, "trade_enabled", None)
                trade_status = "✅ Trade" if (_te is True) else "❌ Trade"
                _tm = getattr(coin, "trade_on_margin", None)
                margin_status = "✅ Margin" if (_tm is True) else "❌ Margin"
                
                if last_price > 0:
                    if last_price >= 100:
                        price_str = f"${last_price:,.2f}"
                    else:
                        price_str = f"${last_price:,.4f}"
                else:
                    price_str = "N/A"
                
                if buy_target > 0:
                    if buy_target >= 100:
                        target_str = f"${buy_target:,.2f}"
                    else:
                        target_str = f"${buy_target:,.4f}"
                else:
                    target_str = "N/A"
                
                amount_str = ""
                _amt = getattr(coin, "trade_amount_usd", None)
                if _amt is not None and _to_float(_amt) > 0:
                    amount_str = f" | Amount: ${_to_float(_amt):,.2f}"
                
                message += f"""

• *{symbol}*
  {trade_status} | {margin_status}
  Price: {price_str} | Target: {target_str}{amount_str}"""
        
        logger.info(f"[TG][CMD] /alerts")
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build alerts list: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error building alerts list: {str(e)}")


def send_analyze_message(chat_id: str, text: str, db: Optional[Session] = None) -> bool:
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
                sym = str(getattr(coin, "symbol", "") or "")
                row.append({
                    "text": sym,
                    "callback_data": f"analyze_{sym}"
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
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                    "reply_markup": reply_markup
                }
                response = http_post(url, json=payload, timeout=10, calling_module="telegram_commands")
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
        
        last_price_f = _to_float(getattr(coin, "price", None))
        buy_target_f = _to_float(getattr(coin, "buy_target", None))
        res_up_f = _to_float(getattr(coin, "res_up", None))
        res_down_f = _to_float(getattr(coin, "res_down", None))
        rsi = getattr(coin, "rsi", None)
        rsi_str = str(rsi) if rsi is not None else "N/A"
        
        status = str(getattr(coin, "order_status", None) or "PENDING")
        _te = getattr(coin, "trade_enabled", None)
        trade_status = "✅ Trade: YES" if _te is True else "❌ Trade: NO"
        _ae = getattr(coin, "alert_enabled", None)
        alert_status = "🔔 Alert: YES" if _ae is True else "❌ Alert: NO"
        _tm = getattr(coin, "trade_on_margin", None)
        margin_status = "✅ Margin: YES" if _tm is True else "❌ Margin: NO"
        
        price_str = f"${last_price_f:,.2f}" if last_price_f >= 100 else (f"${last_price_f:,.4f}" if last_price_f > 0 else "N/A")
        target_str = f"${buy_target_f:,.2f}" if buy_target_f >= 100 else (f"${buy_target_f:,.4f}" if buy_target_f > 0 else "N/A")
        res_up_str = f"${res_up_f:,.2f}" if res_up_f >= 100 else (f"${res_up_f:,.4f}" if res_up_f > 0 else "N/A")
        res_down_str = f"${res_down_f:,.2f}" if res_down_f >= 100 else (f"${res_down_f:,.4f}" if res_down_f > 0 else "N/A")
        
        amount_val = _to_float(getattr(coin, "trade_amount_usd", None))
        amount_info = f"\n• *Trade Amount:* ${amount_val:,.2f}" if amount_val else ""
        
        has_data = (last_price_f > 0) or (rsi_str != "N/A" and rsi_str != "None")
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
• *RSI:* {rsi_str}{amount_info}
• *Status:* {status}{data_warning}"""
        
        logger.info(f"[TG][CMD] /analyze {symbol}")
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build analysis: {e}")
        return send_command_response(chat_id, f"❌ Error building analysis: {str(e)}")


def handle_create_sl_tp_command(chat_id: str, text: str, db: Optional[Session] = None) -> bool:
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


def handle_create_sl_command(chat_id: str, text: str, db: Optional[Session] = None) -> bool:
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


def handle_create_tp_command(chat_id: str, text: str, db: Optional[Session] = None) -> bool:
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


def handle_add_coin_command(chat_id: str, text: str, db: Optional[Session] = None) -> bool:
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


def handle_skip_sl_tp_reminder_command(chat_id: str, text: str, db: Optional[Session] = None) -> bool:
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


def handle_panic_command(chat_id: str, text: str, db: Optional[Session] = None) -> bool:
    """Handle /panic command - Stop all trading by setting all trade_enabled to False"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Get all watchlist items with trade_enabled=True
        active_items = db.query(WatchlistItem).filter(
            WatchlistItem.trade_enabled == True,
            WatchlistItem.is_deleted == False
        ).all()
        
        if not active_items:
            message = "🟢 <b>PANIC BUTTON</b>\n\n"
            message += "✅ All trading is already disabled.\n"
            message += "💡 No coins have Trade=YES."
        else:
            # Update all items to set trade_enabled=False
            updated_count = 0
            for item in active_items:
                setattr(item, "trade_enabled", False)
                updated_count += 1
            
            db.commit()
            
            message = "🔴 <b>PANIC BUTTON ACTIVATED</b>\n\n"
            message += f"⛔ <b>ALL TRADING STOPPED</b>\n\n"
            message += f"📊 Updated: <b>{updated_count}</b> coins\n"
            message += f"💡 All Trade flags set to <b>NO</b>\n\n"
            message += "⚠️ No new orders will be created.\n"
            message += "💡 Use /watchlist to verify changes."
            
            logger.warning(f"[TG][PANIC] Panic button activated by chat_id={chat_id}, disabled trading for {updated_count} coins")
        
        logger.info(f"[TG][CMD] /panic executed by chat_id={chat_id}")
        return send_command_response(chat_id, message)
        
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to execute panic command: {e}", exc_info=True)
        if db:
            db.rollback()
        return send_command_response(chat_id, f"❌ Error executing panic command: {str(e)}")


def handle_kill_command(chat_id: str, text: str, db: Optional[Session] = None) -> bool:
    """Handle /kill command - Control global trading kill switch
    
    Commands:
    - /kill on     -> Enable kill switch (disable all trading)
    - /kill off    -> Disable kill switch (allow trading if other conditions met)
    - /kill status -> Show current status of Live toggle and Kill switch
    """
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        from app.models.trading_settings import TradingSettings
        from app.utils.live_trading import get_live_trading_status
        from app.utils.trading_guardrails import _get_telegram_kill_switch_status
        from sqlalchemy.sql import func
        
        # Parse command
        parts = text.strip().split()
        action = parts[1].lower() if len(parts) > 1 else "status"
        
        if action == "on":
            # Set kill switch ON (disable trading)
            try:
                db.rollback()  # Start fresh
                setting = db.query(TradingSettings).filter(
                    TradingSettings.setting_key == "TRADING_KILL_SWITCH"
                ).first()
                
                if setting:
                    setattr(setting, "setting_value", "true")
                    setattr(setting, "updated_at", datetime.now(pytz.UTC))
                else:
                    setting = TradingSettings(
                        setting_key="TRADING_KILL_SWITCH",
                        setting_value="true",
                        description="Global Telegram kill switch to disable all trading"
                    )
                    db.add(setting)
                
                db.commit()
                logger.warning(f"[TG][KILL] Kill switch enabled by chat_id={chat_id}")
                
                message = "🔴 <b>KILL SWITCH ACTIVATED</b>\n\n"
                message += "⛔ <b>ALL TRADING DISABLED</b>\n\n"
                message += "⚠️ No orders will be placed until kill switch is turned OFF.\n"
                message += "💡 Use /kill off to re-enable trading."
                
                return send_command_response(chat_id, message)
            except Exception as e:
                logger.error(f"[TG][ERROR] Failed to enable kill switch: {e}", exc_info=True)
                db.rollback()
                return send_command_response(chat_id, f"❌ Error enabling kill switch: {str(e)}")
        
        elif action == "off":
            # Set kill switch OFF (allow trading if other conditions met)
            try:
                db.rollback()  # Start fresh
                setting = db.query(TradingSettings).filter(
                    TradingSettings.setting_key == "TRADING_KILL_SWITCH"
                ).first()
                
                if setting:
                    setattr(setting, "setting_value", "false")
                    setattr(setting, "updated_at", datetime.now(pytz.UTC))
                    db.commit()
                else:
                    # Setting doesn't exist, which means kill switch is OFF (default)
                    db.rollback()
                
                logger.info(f"[TG][KILL] Kill switch disabled by chat_id={chat_id}")
                
                message = "🟢 <b>KILL SWITCH DEACTIVATED</b>\n\n"
                message += "✅ Trading is now allowed (subject to other conditions).\n"
                message += "💡 Use /kill status to check current status."
                
                return send_command_response(chat_id, message)
            except Exception as e:
                logger.error(f"[TG][ERROR] Failed to disable kill switch: {e}", exc_info=True)
                db.rollback()
                return send_command_response(chat_id, f"❌ Error disabling kill switch: {str(e)}")
        
        elif action == "status":
            # Show current status
            try:
                live_enabled = get_live_trading_status(db)
                kill_switch_on = _get_telegram_kill_switch_status(db)
                
                message = "📊 <b>TRADING STATUS</b>\n\n"
                message += f"🔴 Live Toggle: <b>{'ON' if live_enabled else 'OFF'}</b>\n"
                message += f"🛑 Kill Switch: <b>{'ON' if kill_switch_on else 'OFF'}</b>\n\n"
                
                if kill_switch_on:
                    message += "⛔ <b>TRADING IS DISABLED</b> (Kill switch is ON)\n"
                elif not live_enabled:
                    message += "⛔ <b>TRADING IS DISABLED</b> (Live toggle is OFF)\n"
                else:
                    message += "✅ Trading is enabled (subject to Trade Yes per symbol)\n"
                
                message += "\n💡 Commands:\n"
                message += "  /kill on    - Enable kill switch\n"
                message += "  /kill off   - Disable kill switch\n"
                message += "  /kill status - Show this status"
                
                return send_command_response(chat_id, message)
            except Exception as e:
                logger.error(f"[TG][ERROR] Failed to get kill switch status: {e}", exc_info=True)
                return send_command_response(chat_id, f"❌ Error getting status: {str(e)}")
        
        else:
            # Invalid action
            message = "❓ <b>Invalid /kill command</b>\n\n"
            message += "Usage:\n"
            message += "  /kill on     - Enable kill switch\n"
            message += "  /kill off    - Disable kill switch\n"
            message += "  /kill status - Show current status"
            return send_command_response(chat_id, message)
            
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to execute kill command: {e}", exc_info=True)
        if db:
            db.rollback()
        return send_command_response(chat_id, f"❌ Error executing kill command: {str(e)}")


def handle_telegram_update(update: Dict, db: Optional[Session] = None) -> None:
    """Handle a single Telegram update (messages and callback queries)"""
    global PROCESSED_TEXT_COMMANDS, PROCESSED_CALLBACK_DATA, PROCESSED_CALLBACK_IDS
    update_id = update.get("update_id", 0)
    
    # Determine update type and extract key info for logging
    update_type = "unknown"
    callback_query = update.get("callback_query")
    message = (
        update.get("message")
        or update.get("edited_message")
        or update.get("channel_post")
        or update.get("edited_channel_post")
    )
    
    if callback_query:
        update_type = "callback_query"
        callback_data = callback_query.get("data", "")
        from_user = callback_query.get("from", {})
        username = from_user.get("username", "N/A")
        user_id = str(from_user.get("id", ""))
        msg = callback_query.get("message", {})
        chat = msg.get("chat", {}) if msg else {}
        chat_id = str(chat.get("id", ""))
        logger.info(f"[TG][HANDLER] update_id={update_id}, type={update_type}, callback_data='{callback_data}', username={username}, user_id={user_id}, chat_id={chat_id}")
    elif message:
        update_type = "channel_post" if (update.get("channel_post") or update.get("edited_channel_post")) else "message"
        text = message.get("text", "")
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        chat_type = chat.get("type", "unknown")
        from_user = message.get("from", {}) or {}
        username = from_user.get("username", "N/A") if from_user else "N/A"
        user_id = str(from_user.get("id", "")) if from_user else ""
        logger.info(f"[TG][HANDLER] update_id={update_id}, type={update_type}, chat_type={chat_type}, text='{text[:50]}', username={username}, user_id={user_id}, chat_id={chat_id}")
    else:
        logger.info(f"[TG][HANDLER] update_id={update_id}, type={update_type} (no message, channel_post, or callback_query)")
    
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
        # (e.g., when both Hilovivo-alerts and Hilovivo-alerts-local receive the same callback)
        if callback_data and callback_data != "noop":
            now = time.time()
            if callback_data in PROCESSED_CALLBACK_DATA:
                last_processed = PROCESSED_CALLBACK_DATA[callback_data]
                if now - last_processed < CALLBACK_DATA_TTL:
                    logger.debug(f"[TG] Skipping duplicate callback_data={callback_data} (processed {now - last_processed:.2f}s ago)")
                    # Still answer the callback to remove loading state
                    if callback_query_id:
                        try:
                            token = _get_effective_bot_token()
                            if token:
                                url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
                                http_post(url, json={"callback_query_id": callback_query_id}, timeout=5, calling_module="telegram_commands")
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
        username = from_user.get("username", "N/A")
        message_id = message.get("message_id")
        logger.info(f"[TG][CALLBACK] Processing callback_data='{callback_data}' from chat_id={chat_id}, user_id={user_id}, username={username}, message_id={message_id}")
        
        # Only authorized chat (group/channel) or user - use helper function
        if not _is_authorized(chat_id, user_id):
            logger.warning(f"[TG][DENY] callback_query from chat_id={chat_id}, user_id={user_id}, AUTH_CHAT_ID={AUTH_CHAT_ID}, AUTHORIZED_USER_IDS={AUTHORIZED_USER_IDS}")
            # Send error message to user
            try:
                send_command_response(chat_id, "⛔ Not authorized")
            except:
                pass
            return
        
        # Mark this callback as processed BEFORE processing to prevent race conditions
        if callback_query_id:
            PROCESSED_CALLBACK_IDS.add(callback_query_id)
            # Clean up old callback IDs (keep only last 1000 to prevent memory leak)
            if len(PROCESSED_CALLBACK_IDS) > 1000:
                # Remove oldest 500 entries (simple cleanup)
                old_ids = list(PROCESSED_CALLBACK_IDS)[:500]
                PROCESSED_CALLBACK_IDS.difference_update(old_ids)
            
            # Answer callback query to remove loading state (CRITICAL: Must happen immediately)
            try:
                token = _get_effective_bot_token()
                if token:
                    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
                    ack_response = http_post(url, json={"callback_query_id": callback_query_id}, timeout=5, calling_module="telegram_commands")
                    if ack_response.status_code == 200:
                        ack_result = ack_response.json()
                        if ack_result.get("ok"):
                            logger.info(f"[TG][CALLBACK] ✅ ACK sent successfully for callback_query_id={callback_query_id}, callback_data='{callback_data}'")
                        else:
                            logger.warning(f"[TG][CALLBACK] ⚠️ ACK response not OK: {ack_result}")
                    else:
                        logger.warning(f"[TG][CALLBACK] ⚠️ ACK HTTP error: status={ack_response.status_code}")
            except Exception as ack_err:
                logger.error(f"[TG][CALLBACK] ❌ Failed to ACK callback_query_id={callback_query_id}: {ack_err}", exc_info=True)
        
        # Process callback data
        logger.info(f"[TG][CALLBACK] Processing callback_query: callback_data='{callback_data}' from chat_id={chat_id}, user_id={user_id}, username={username}")
        
        # Send loading feedback for menu and cmd actions (except noop)
        if callback_data != "noop":
            loading_text = None
            if callback_data.startswith("menu:"):
                menu_action = callback_data.replace("menu:", "")
                loading_messages = {
                    "portfolio": "💼 Loading Portfolio...",
                    "watchlist": "📊 Loading Watchlist...",
                    "open_orders": "📋 Loading Open Orders...",
                    "expected_tp": "🎯 Loading Expected Take Profit...",
                    "executed_orders": "✅ Loading Executed Orders...",
                    "monitoring": "🔍 Loading Monitoring...",
                    "kill_switch": "🛑 Loading Kill Switch...",
                    "main": "📋 Loading Main Menu...",
                }
                loading_text = loading_messages.get(menu_action, "⏳ Loading...")
            elif callback_data.startswith("cmd:"):
                cmd_action = callback_data.replace("cmd:", "")
                loading_messages = {
                    "check_sl_tp": "🛡️ Checking SL/TP...",
                    "version": "📝 Loading Version History...",
                    "portfolio": "💼 Loading Portfolio...",
                    "open_orders": "📋 Loading Open Orders...",
                    "expected_tp": "🎯 Loading Expected Take Profit...",
                    "executed_orders": "✅ Loading Executed Orders...",
                }
                loading_text = loading_messages.get(cmd_action, "⏳ Processing...")
            
            if loading_text:
                try:
                    # Send a quick loading message (will be followed by actual response)
                    send_command_response(chat_id, loading_text)
                    logger.info(f"[TG][CALLBACK] Sent loading feedback: '{loading_text}' for callback_data='{callback_data}'")
                except Exception as e:
                    logger.debug(f"[TG][CALLBACK] Could not send loading message: {e}")
        
        if callback_data == "noop":
            return
        elif callback_data == "atp_run_full_fix" or (callback_data or "").strip().startswith("atp_run_full_fix"):
            # Manual "Run full fix now" from ATP health alert: write trigger file; health script runs full_fix_market_data.sh on next run
            # Accept "atp_run_full_fix" even with trailing space/timestamp (e.g. "atp_run_full_fix 10:35")
            trigger_path = os.environ.get("ATP_TRIGGER_FULL_FIX_PATH", "/app/logs/trigger_full_fix")
            try:
                os.makedirs(os.path.dirname(trigger_path), exist_ok=True)
                with open(trigger_path, "w") as f:
                    f.write(f"{time.time()}\n")
                send_command_response(
                    chat_id,
                    "✅ Full fix triggered. It will run on the next health check (within ~5 min). You'll get ✅ recovered when health returns.",
                )
                logger.info(f"[TG][ATP] Wrote trigger file for full fix: {trigger_path}")
            except OSError as e:
                send_command_response(
                    chat_id,
                    f"⚠️ Could not write trigger file (run full fix manually on the server). Error: {e}",
                )
                logger.warning(f"[TG][ATP] Failed to write trigger file {trigger_path}: {e}")
            return
        elif callback_data == "menu:watchlist":
            logger.info(f"[TG][MENU] ✅ Routing callback_data='menu:watchlist' to show_watchlist_menu, chat_id={chat_id}, message_id={message_id}")
            show_watchlist_menu(chat_id, db, page=1, message_id=message_id)
        elif callback_data == "menu:signal_config":
            show_signal_config_menu(chat_id, message_id=message_id)
        elif callback_data.startswith("watchlist:page:"):
            try:
                page = int(callback_data.split(":")[-1])
                logger.info(f"[TG][WATCHLIST] Navigating to page {page} for chat_id={chat_id}")
            except ValueError as e:
                logger.warning(f"[TG][WATCHLIST] Invalid page number in callback_data={callback_data}: {e}")
                page = 1
            try:
                result = show_watchlist_menu(chat_id, db, page=page, message_id=message_id)
                if not result:
                    logger.error(f"[TG][WATCHLIST] Failed to show watchlist menu page {page} for chat_id={chat_id}")
            except Exception as e:
                logger.error(f"[TG][WATCHLIST] Error showing watchlist menu page {page}: {e}", exc_info=True)
                send_command_response(chat_id, f"❌ Error navegando a página {page}: {str(e)}")
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
            logger.info(f"[TG][MENU] ✅ Routing callback_data='menu:main' to show_main_menu, chat_id={chat_id}")
            show_main_menu(chat_id, db)
        elif callback_data.startswith("cmd:"):
            # Handle command shortcuts from menu
            cmd = callback_data.replace("cmd:", "")
            logger.info(f"[TG][CMD] ✅ Routing callback_data='{callback_data}' (cmd='{cmd}') to handler, chat_id={chat_id}")
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
            elif cmd == "check_sl_tp":
                send_check_sl_tp_message(chat_id, db)
            elif cmd == "investigate":
                # Prompt for problem text; user can reply with /investigate <problem>
                send_command_response(
                    chat_id,
                    "🔍 <b>Investigate</b>\n\nType: <code>/investigate &lt;problem&gt;</code>\n\nExample: /investigate repeated BTC alerts"
                )
            elif cmd == "runtime-check":
                try:
                    import importlib.util
                    script_path = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "diag", "check_runtime_dependencies.py")
                    script_path = os.path.abspath(script_path)
                    if os.path.isfile(script_path):
                        spec = importlib.util.spec_from_file_location("check_runtime_dependencies", script_path)
                        if spec is not None and spec.loader is not None:
                            mod = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(mod)
                            out = mod.run_check()
                        else:
                            out = "Runtime dependency check\n\nFailed to load module spec"
                    else:
                        out = "Runtime dependency check\n\nScript not found"
                    send_command_response(chat_id, f"<pre>{out}</pre>")
                except Exception as e:
                    logger.exception("[TG][CMD] /runtime-check failed: %s", e)
                    send_command_response(chat_id, f"❌ Error: {e}")
            else:
                logger.warning(f"[TG][CMD] ⚠️ Unknown cmd='{cmd}' in callback_data='{callback_data}'")
        elif callback_data == "menu:portfolio":
            # Show portfolio sub-menu
            logger.info(f"[TG][MENU] ✅ Routing callback_data='menu:portfolio' to show_portfolio_menu, chat_id={chat_id}, message_id={message_id}")
            result = show_portfolio_menu(chat_id, db, message_id)
            logger.info(f"[TG][MENU] Portfolio menu result: {result}")
        elif callback_data == "menu:open_orders":
            # Show open orders sub-menu
            logger.info(f"[TG][MENU] ✅ Routing callback_data='menu:open_orders' to show_open_orders_menu, chat_id={chat_id}, message_id={message_id}")
            show_open_orders_menu(chat_id, db, message_id)
        elif callback_data == "menu:expected_tp":
            # Show expected take profit sub-menu
            logger.info(f"[TG][MENU] ✅ Routing callback_data='menu:expected_tp' to show_expected_tp_menu, chat_id={chat_id}, message_id={message_id}")
            show_expected_tp_menu(chat_id, db, message_id)
        elif callback_data == "menu:executed_orders":
            # Show executed orders sub-menu
            logger.info(f"[TG][MENU] ✅ Routing callback_data='menu:executed_orders' to show_executed_orders_menu, chat_id={chat_id}, message_id={message_id}")
            show_executed_orders_menu(chat_id, db, message_id)
        elif callback_data == "menu:monitoring":
            # Show monitoring sub-menu
            logger.info(f"[TG][MENU] ✅ Routing callback_data='menu:monitoring' to show_monitoring_menu, chat_id={chat_id}, message_id={message_id}")
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
        elif callback_data == "menu:kill_switch":
            # Show kill switch sub-menu
            logger.info(f"[TG][MENU] ✅ Routing callback_data='menu:kill_switch' to show_kill_switch_menu, chat_id={chat_id}, message_id={message_id}")
            show_kill_switch_menu(chat_id, db, message_id)
        elif callback_data == "menu:agent":
            logger.info(f"[TG][MENU] ✅ Routing callback_data='menu:agent' to show_agent_console, chat_id={chat_id}, message_id={message_id}")
            show_agent_console(chat_id, message_id)
        elif callback_data.startswith("kill:"):
            # Handle kill switch actions
            action = callback_data.replace("kill:", "")
            if action == "on":
                handle_kill_command(chat_id, "/kill on", db)
                # Refresh menu to show updated status
                show_kill_switch_menu(chat_id, db, message_id)
            elif action == "off":
                handle_kill_command(chat_id, "/kill off", db)
                # Refresh menu to show updated status
                show_kill_switch_menu(chat_id, db, message_id)
            elif action == "status":
                handle_kill_command(chat_id, "/kill status", db)
                # Refresh menu to show updated status
                show_kill_switch_menu(chat_id, db, message_id)
        elif callback_data == "agent:main":
            show_agent_console(chat_id, message_id)
        elif callback_data == "agent:recent":
            send_recent_agent_activity(chat_id)
        elif callback_data == "agent:pending":
            send_pending_agent_approvals(chat_id, message_id)
        elif callback_data.startswith("agent_detail:"):
            _task_id = callback_data.replace("agent_detail:", "", 1).strip()
            send_approval_request_detail(chat_id, _task_id, message_id)
        elif callback_data == "agent_back_pending":
            send_pending_agent_approvals(chat_id, message_id)
        elif callback_data.startswith("agent_execute:"):
            _task_id = callback_data.replace("agent_execute:", "", 1).strip()
            from app.services.agent_telegram_approval import (
                can_execute_approved_task,
                execute_prepared_task_from_telegram_decision,
            )
            check = can_execute_approved_task(_task_id)
            if not check.get("can_execute"):
                _reason = check.get("reason") or "cannot execute"
                _status = check.get("status") or "unknown"
                text = f"⚠️ <b>Cannot execute</b>\n\n<b>Reason:</b> {_reason}\n<b>Status:</b> {_status}"
                keyboard = _build_keyboard([
                    [{"text": "🔙 Back to Detail", "callback_data": f"agent_detail:{_task_id}"}],
                    [{"text": "🔙 Back to Pending", "callback_data": "agent_back_pending"}],
                ])
                _send_or_edit_menu(chat_id, text, keyboard, message_id)
            else:
                result = execute_prepared_task_from_telegram_decision(_task_id)
                msg = _format_execution_result_message(result)
                keyboard = _build_keyboard([
                    [{"text": "🔙 Back to Pending", "callback_data": "agent_back_pending"}],
                ])
                _send_or_edit_menu(chat_id, msg, keyboard, message_id)
        elif callback_data == "agent:failures":
            send_recent_agent_failures(chat_id)
        elif callback_data.startswith("setting:"):
            # Handle settings menu callbacks (e.g., setting:min_price_change_pct:select_strategy)
            _handle_setting_callback(chat_id, callback_data, callback_query.get("message", {}).get("message_id"), db)
        elif callback_data.startswith("signal:"):
            _handle_signal_config_callback(chat_id, callback_data, message_id)
        elif callback_data.startswith("agent_approve:") or callback_data.startswith("agent_deny:") or callback_data.startswith("agent_summary:"):
            if callback_data.startswith("agent_approve:"):
                _action = "approve"
            elif callback_data.startswith("agent_deny:"):
                _action = "deny"
            else:
                _action = "summary"
            logger.info(f"[TG][APPROVAL] Routing callback_data='{callback_data}' action={_action} chat_id={chat_id} user_id={user_id}")
            try:
                _handle_agent_approval_callback(chat_id, user_id, username, callback_data, _action, message_id=message_id)
            except Exception as approval_err:
                logger.error(f"[TG][APPROVAL] Error handling {_action} callback: {approval_err}", exc_info=True)
                send_command_response(chat_id, f"❌ Error processing {_action}: {str(approval_err)[:200]}")
        elif callback_data.startswith("patch_approve:") or callback_data.startswith("deploy_approve:") or callback_data.startswith("task_reject:") or callback_data.startswith("view_report:") or callback_data.startswith("smoke_check:") or callback_data.startswith("reinvestigate:") or callback_data.startswith("run_cursor_bridge:"):
            if callback_data.startswith("patch_approve:"):
                _action = "approve_patch"
            elif callback_data.startswith("run_cursor_bridge:"):
                _action = "run_cursor_bridge"
            elif callback_data.startswith("deploy_approve:"):
                _action = "approve_deploy"
            elif callback_data.startswith("task_reject:"):
                _action = "reject"
            elif callback_data.startswith("smoke_check:"):
                _action = "smoke_check"
            elif callback_data.startswith("reinvestigate:"):
                _action = "reinvestigate"
            else:
                _action = "view_report"
            logger.info(f"[TG][EXT_APPROVAL] Routing callback_data='{callback_data}' action={_action} chat_id={chat_id} user_id={user_id}")
            try:
                _handle_extended_approval_callback(chat_id, user_id, username, callback_data, _action, message_id=message_id)
            except Exception as ext_err:
                logger.error(f"[TG][EXT_APPROVAL] Error handling {_action} callback: {ext_err}", exc_info=True)
                send_command_response(chat_id, f"❌ Error processing {_action}: {str(ext_err)[:200]}")
        else:
            logger.warning(f"[TG] Unknown callback_data: {callback_data}")
            send_command_response(chat_id, f"❓ Unknown command: {callback_data}")
        
        return
    
    # Handle regular message (groups/supergroups) or channel_post (channels like HILOVIVO3.0)
    # Channels use channel_post, not message — without this, commands in channels are never received
    message = (
        update.get("message")
        or update.get("edited_message")
        or update.get("channel_post")
        or update.get("edited_channel_post")
    )
    if not message:
        return

    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    chat_type = chat.get("type", "unknown")  # private, group, supergroup, channel
    chat_title = chat.get("title", "") or ""
    text = message.get("text", "")
    from_user = message.get("from", {}) or {}
    user_id = str(from_user.get("id", "")) if from_user else ""
    update_id = update.get("update_id", 0)
    update_source = (
        "channel_post" if update.get("channel_post") or update.get("edited_channel_post") else "message"
    )

    logger.info(
        "[TG][INTAKE] update_id=%s update_source=%s chat_id=%s chat_type=%s chat_title=%s "
        "sender_user_id=%s text=%s",
        update_id, update_source, chat_id, chat_type, chat_title[:30] or "N/A",
        user_id or "N/A", (text or "")[:80],
    )
    logger.info("[TG][CHAT] chat_id=%s chat_type=%s chat_title=%s — incoming command source", chat_id, chat_type, chat_title[:40] or "N/A")

    # Only authorized user/chat - use helper function
    auth_ok = _is_authorized(chat_id, user_id)
    logger.info(
        "[TG][AUTH] update_id=%s chat_id=%s chat_type=%s decision=%s authorized_ids=%s",
        update_id, chat_id, chat_type, "ALLOW" if auth_ok else "DENY",
        ",".join(sorted(AUTHORIZED_USER_IDS))[:80] if AUTHORIZED_USER_IDS else "none",
    )
    if not auth_ok:
        if _env_chat_id_trading and chat_id == str(_env_chat_id_trading):
            deny_msg = "HILOVIVO3.0 is alerts-only. Use ATP Control (private group or direct chat) for commands."
        else:
            deny_msg = "⛔ Not authorized"
        reply_ok = send_command_response(chat_id, deny_msg)
        logger.info(
            "[TG][REPLY] update_id=%s chat_id=%s chat_type=%s handler=deny reply_success=%s",
            update_id, chat_id, chat_type, reply_ok,
        )
        return
    
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
                logger.info(
                    "[TG][CMD] handler=dedup_skip update_id=%s chat_id=%s command=%s age_sec=%.2f — sending ack anyway",
                    update_id, chat_id, text[:40], now - last_processed,
                )
                send_command_response(chat_id, "⏳ Command already processed. Wait a moment and try again.")
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
    
    # Command dispatch — always send a reply (handler or fallback on exception)
    # Guard: empty or non-command text
    if not text or not text.strip():
        logger.info("[TG][CMD] handler=empty_text update_id=%s chat_id=%s — no text, sending ack", update_id, chat_id)
        send_command_response(chat_id, "📋 Send a command (e.g. /help)")
        return
    if not text.startswith("/"):
        logger.info("[TG][CMD] handler=non_command update_id=%s chat_id=%s text=%s", update_id, chat_id, text[:30])
        send_command_response(chat_id, "❓ Send a command (e.g. /help)")
        return

    try:
        if text.startswith("/start"):
            logger.info("[TG][CMD] handler=start update_id=%s chat_id=%s", update_id, chat_id)
            try:
                # CRITICAL: /start should ALWAYS show main menu, not any other menu
                logger.info(f"[TG][CMD][START] Showing main menu to chat_id={chat_id} (forcing main menu)")
                menu_result = show_main_menu(chat_id, db)
                logger.info(f"[TG][CMD][START] Main menu result: {menu_result}")
                if menu_result:
                    logger.info(f"[TG][CMD][START] ✅ /start command processed successfully for chat_id={chat_id}")
                else:
                    logger.error(f"[TG][CMD][START] ❌ Failed to send main menu to chat_id={chat_id}")
                    send_command_response(chat_id, "📋 <b>Main Menu</b>\n\nUse /menu to see the full menu with all sections.")
            except Exception as e:
                logger.error(f"[TG][ERROR][START] ❌ Error processing /start command: {e}", exc_info=True)
                send_command_response(chat_id, f"❌ Error processing /start: {str(e)}")
        elif text.startswith("/menu"):
            show_main_menu(chat_id, db)
        elif text.startswith("/investigate"):
            logger.info("[TG][CMD] handler=investigate update_id=%s chat_id=%s", update_id, chat_id)
            try:
                from app.core.runtime_identity import get_runtime_identity, format_runtime_identity_short
                identity = get_runtime_identity()
                logger.info(
                    "telegram_command_received command=investigate chat_id=%s handler=agent_telegram_commands runtime=%s",
                    chat_id,
                    format_runtime_identity_short(identity),
                )
                from app.services.agent_telegram_commands import handle_investigate_command
                ok = handle_investigate_command(chat_id, text, send_command_response)
                logger.info("[TG][REPLY] handler=investigate update_id=%s chat_id=%s success=%s", update_id, chat_id, ok)
            except Exception as e:
                logger.exception("[TG][CMD] /investigate failed: %s", e)
                ok = send_command_response(chat_id, f"❌ Error: {str(e)[:200]}")
                logger.info("[TG][REPLY] handler=investigate update_id=%s chat_id=%s success=%s (after error)", update_id, chat_id, ok)
        elif text.startswith("/runtime-check"):
            logger.info("[TG][CMD] handler=runtime-check update_id=%s chat_id=%s", update_id, chat_id)
            try:
                import importlib.util
                script_path = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "diag", "check_runtime_dependencies.py")
                script_path = os.path.abspath(script_path)
                if os.path.isfile(script_path):
                    spec = importlib.util.spec_from_file_location("check_runtime_dependencies", script_path)
                    if spec is not None and spec.loader is not None:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                        out = mod.run_check()
                    else:
                        out = "Runtime dependency check\n\nFailed to load module spec"
                else:
                    out = "Runtime dependency check\n\nScript not found (path: %s)" % script_path
                ok = send_command_response(chat_id, f"<pre>{out}</pre>")
                logger.info("[TG][REPLY] handler=runtime-check update_id=%s chat_id=%s success=%s", update_id, chat_id, ok)
            except Exception as e:
                logger.exception("[TG][CMD] /runtime-check failed: %s", e)
                ok = send_command_response(chat_id, f"❌ Error: {e}")
                logger.info("[TG][REPLY] handler=runtime-check update_id=%s chat_id=%s success=%s (after error)", update_id, chat_id, ok)
        elif text.startswith("/agent "):
            logger.info("[TG][CMD] handler=agent update_id=%s chat_id=%s", update_id, chat_id)
            try:
                from app.services.agent_telegram_commands import handle_agent_command
                ok = handle_agent_command(chat_id, text, send_command_response)
                logger.info("[TG][REPLY] handler=agent update_id=%s chat_id=%s success=%s", update_id, chat_id, ok)
            except Exception as e:
                logger.exception("[TG][CMD] /agent failed: %s", e)
                ok = send_command_response(chat_id, f"❌ Error: {e}")
                logger.info("[TG][REPLY] handler=agent update_id=%s chat_id=%s success=%s (after error)", update_id, chat_id, ok)
        elif text.startswith("/help"):
            logger.info("[TG][CMD] handler=help update_id=%s chat_id=%s", update_id, chat_id)
            ok = send_help_message(chat_id)
            logger.info("[TG][REPLY] handler=help update_id=%s chat_id=%s success=%s", update_id, chat_id, ok)
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
        elif text.startswith("/audit") or text.startswith("/snapshot"):
            send_audit_snapshot(chat_id, db)
        elif text.startswith("/add"):
            handle_add_coin_command(chat_id, text, db)
        elif text.startswith("/create_sl_tp"):
            handle_create_sl_tp_command(chat_id, text, db)
        elif text.startswith("/create_sl"):
            handle_create_sl_command(chat_id, text, db)
        elif text.startswith("/create_tp"):
            handle_create_tp_command(chat_id, text, db)
        elif text.startswith("/skip_sl_tp_reminder"):
            handle_skip_sl_tp_reminder_command(chat_id, text, db)
        elif text.startswith("/panic"):
            handle_panic_command(chat_id, text, db)
        elif text.startswith("/kill"):
            handle_kill_command(chat_id, text, db)
        elif text.startswith("/agent"):
            show_agent_console(chat_id)
        elif text.startswith("/"):
            logger.info("[TG][CMD] handler=unknown update_id=%s chat_id=%s command=%s", update_id, chat_id, text[:50])
            ok = send_command_response(chat_id, "❓ Unknown command. Use /help")
            logger.info("[TG][REPLY] handler=unknown update_id=%s chat_id=%s success=%s", update_id, chat_id, ok)
        else:
            logger.info("[TG][CMD] handler=fallback update_id=%s chat_id=%s text=%s", update_id, chat_id, (text or "")[:50])
            send_command_response(chat_id, "❓ No response. Use /help for commands.")
    except Exception as e:
        logger.exception("[TG][CMD] Unhandled exception update_id=%s chat_id=%s: %s", update_id, chat_id, e)
        send_command_response(chat_id, f"❌ Error: {str(e)[:200]}")


def process_telegram_commands(db: Optional[Session] = None) -> None:
    """Process pending Telegram commands using long polling for real-time processing"""
    global LAST_UPDATE_ID, _NO_UPDATE_COUNT
    
    # RUNTIME GUARD: Local runtime requires DEV token to avoid 409 conflicts
    if not is_aws_runtime():
        # LOCAL runtime: Only allow processing if DEV token is set
        if not BOT_TOKEN_DEV:
            logger.debug(
                "[TG] Skipping Telegram command processing on LOCAL runtime "
                "(TELEGRAM_BOT_TOKEN_DEV not set to avoid 409 conflicts with AWS)"
            )
            return
        # LOCAL with DEV token: Allow processing (uses separate dev bot)
        logger.debug("[TG] LOCAL runtime with DEV token - processing commands with dev bot")
    else:
        # AWS runtime: Use production token (existing behavior)
        if not BOT_TOKEN:
            logger.warning("[TG] AWS runtime but TELEGRAM_BOT_TOKEN not set")
            return
    
    # Ensure we have a DB session
    if not db:
        session_factory = SessionLocal
        if session_factory is None:
            logger.error("[TG] SessionLocal not available")
            return
        try:
            db = session_factory()
            db_created = True
        except Exception as e:
            logger.error(f"[TG] Cannot create DB session: {e}")
            return
    else:
        db_created = False

    if db is None:
        return

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
            _last_id = int(LAST_UPDATE_ID) if LAST_UPDATE_ID else 0
            offset = (_last_id + 1) if _last_id > 0 else None
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
                message = (
                    update.get("message")
                    or update.get("edited_message")
                    or update.get("channel_post")
                    or update.get("edited_channel_post")
                )
                callback_query = update.get("callback_query")
                my_chat_member = update.get("my_chat_member")
                
                if callback_query:
                    callback_data = callback_query.get("data", "")
                    from_user = callback_query.get("from", {})
                    username = from_user.get("username", "N/A")
                    user_id = str(from_user.get("id", ""))
                    # Get chat_id from message, not from user
                    msg = callback_query.get("message", {})
                    chat = msg.get("chat", {}) if msg else {}
                    chat_id = str(chat.get("id", ""))
                    logger.info(f"[TG] ⚡ Processing callback_query: callback_data='{callback_data}' from chat_id={chat_id}, user_id={user_id}, username={username}, update_id={update_id}")
                elif message:
                    text = message.get("text", "")
                    chat = message.get("chat", {})
                    chat_id = chat.get("id", "")
                    chat_type = chat.get("type", "unknown")
                    update_src = "channel_post" if (update.get("channel_post") or update.get("edited_channel_post")) else "message"
                    logger.info(
                        "[TG] ⚡ Processing %s: '%s' from chat_id=%s chat_type=%s update_id=%s",
                        update_src, (text or "")[:60], chat_id, chat_type, update_id,
                    )
                elif my_chat_member:
                    # Handle bot being added/removed from groups
                    chat = my_chat_member.get("chat", {})
                    chat_id = str(chat.get("id", ""))
                    new_status = my_chat_member.get("new_chat_member", {}).get("status", "")
                    old_status = my_chat_member.get("old_chat_member", {}).get("status", "")
                    logger.info(f"[TG] ⚡ Processing my_chat_member: chat_id={chat_id}, status: {old_status} -> {new_status}, update_id={update_id}")
                    # If bot was added to group, send welcome message (main menu)
                    if new_status == "member" or new_status == "administrator":
                        logger.info(f"[TG] Bot added to group {chat_id}, sending welcome message")
                        send_welcome_message(chat_id, db)
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


def _edit_approval_card(chat_id: str, message_id: Optional[int], result_text: str, task_id: str, *, extra_rows: Optional[list] = None) -> None:
    """Edit the original approval card to show the decision result, replacing the Approve/Deny buttons."""
    rows = [[{"text": "🔙 Back to Pending", "callback_data": "agent_back_pending"}]]
    if extra_rows:
        rows = extra_rows + rows
    keyboard = _build_keyboard(rows)
    if message_id:
        if not _edit_menu_message(chat_id, message_id, result_text, keyboard):
            send_command_response(chat_id, result_text)
    else:
        send_command_response(chat_id, result_text)


def _handle_agent_approval_callback(
    chat_id: str,
    user_id: str,
    username: str,
    callback_data: str,
    action: str,
    message_id: Optional[int] = None,
) -> None:
    """Handle agent approval flow: agent_approve:<task_id>, agent_deny:<task_id>, agent_summary:<task_id>."""
    logger.info(f"[TG][APPROVAL] _handle_agent_approval_callback: action={action}, callback_data={callback_data[:60]}, chat_id={chat_id}, user_id={user_id}, message_id={message_id}")
    try:
        from app.services.agent_telegram_approval import (
            get_approval_summary_text,
            execute_prepared_task_from_telegram_decision,
            record_approval,
            record_denial,
            PREFIX_APPROVE,
            PREFIX_DENY,
            PREFIX_SUMMARY,
        )
    except ImportError as imp_err:
        logger.error(f"[TG][APPROVAL] Failed to import agent_telegram_approval: {imp_err}", exc_info=True)
        send_command_response(chat_id, "❌ Approval module unavailable. Check server logs.")
        return

    task_id = ""
    if callback_data.startswith(PREFIX_APPROVE):
        task_id = callback_data[len(PREFIX_APPROVE):].strip()
    elif callback_data.startswith(PREFIX_DENY):
        task_id = callback_data[len(PREFIX_DENY):].strip()
    elif callback_data.startswith(PREFIX_SUMMARY):
        task_id = callback_data[len(PREFIX_SUMMARY):].strip()
    if not task_id:
        logger.warning(f"[TG][APPROVAL] Missing task_id in callback_data={callback_data}")
        send_command_response(chat_id, "❌ Invalid approval callback (missing task_id).")
        return

    logger.info(f"[TG][APPROVAL] task_id={task_id}, action={action}")

    if action == "summary":
        summary_text = get_approval_summary_text(task_id)
        send_command_response(chat_id, f"📄 <b>Approval summary</b>\n\n<pre>{summary_text[:3500]}</pre>")
        return

    who = username or user_id or "unknown"

    if action == "approve":
        if not record_approval(task_id, user_id, who):
            logger.warning(f"[TG][APPROVAL] record_approval returned False for task_id={task_id}")
            _edit_approval_card(chat_id, message_id, "⚠️ Already approved/denied or not found.", task_id)
            return
        logger.info(f"[TG][APPROVAL] Approved task_id={task_id} by {who}, starting execution...")
        _edit_approval_card(chat_id, message_id, f"✅ <b>Approved</b> by {who}\nStarting execution…", task_id)

        # If task is already in investigation-complete, advancing to ready-for-patch and running
        # the patch continuation avoids re-running the full executor (which would send approval again).
        try:
            from app.services.notion_task_reader import get_notion_task_by_id
            from app.services.notion_tasks import update_notion_task_status, TASK_STATUS_INVESTIGATION_COMPLETE
            from app.services.agent_task_executor import advance_ready_for_patch_task
            task = get_notion_task_by_id(task_id)
            current_status = (task or {}).get("status") or ""
            is_inv_complete = (
                isinstance(current_status, str)
                and (
                    current_status.strip().lower() == TASK_STATUS_INVESTIGATION_COMPLETE.lower()
                    or ("investigation" in current_status.lower() and "complete" in current_status.lower())
                )
            )
            if is_inv_complete:
                ok = update_notion_task_status(task_id, "ready-for-patch")
                if ok:
                    r = advance_ready_for_patch_task(task_id)
                    status = r.get("final_status") or r.get("stage") or "ready-for-patch"
                    logger.info(f"[TG][APPROVAL] Advanced from investigation-complete task_id={task_id}, result={r.get('ok')}, status={status}")
                    _edit_approval_card(chat_id, message_id, f"✅ <b>Approved</b> by {who}\nAdvanced to patch. Status: <b>{status}</b>", task_id)
                else:
                    _edit_approval_card(chat_id, message_id, f"✅ <b>Approved</b> by {who}\nNotion status update failed.", task_id)
                return
        except Exception as adv_err:
            logger.debug(f"[TG][APPROVAL] advance from investigation-complete failed, falling back to full execution: {adv_err}")

        run_result = execute_prepared_task_from_telegram_decision(task_id)
        if run_result.get("executed"):
            exec_result = run_result.get("execution_result") or {}
            status = exec_result.get("final_status", "unknown")
            logger.info(f"[TG][APPROVAL] Execution completed for task_id={task_id}, status={status}")
            _edit_approval_card(chat_id, message_id, f"✅ <b>Approved</b> by {who}\nExecution status: <b>{status}</b>", task_id)
        else:
            reason = run_result.get("reason", "Execution not run.")
            logger.info(f"[TG][APPROVAL] Approved but not executed: task_id={task_id}, reason={reason}")
            _edit_approval_card(chat_id, message_id, f"✅ <b>Approved</b> by {who}\n{reason}", task_id)
        return

    if action == "deny":
        if not record_denial(task_id, user_id, who):
            logger.warning(f"[TG][APPROVAL] record_denial returned False for task_id={task_id}")
            _edit_approval_card(chat_id, message_id, "⚠️ Already approved/denied or not found.", task_id)
            return
        logger.info(f"[TG][APPROVAL] Denied task_id={task_id} by {who}")
        _edit_approval_card(chat_id, message_id, f"❌ <b>Denied</b> by {who}\nExecution will not run.", task_id)


def _check_deploy_test_gate(task_id: str) -> tuple[bool, str]:
    """Check whether a task's test status allows deploy approval.

    Reads the ``Test Status`` metadata from Notion.  Returns
    ``(allowed, reason)`` where *allowed* is True only when the test
    status clearly indicates ``passed``.

    Legacy tasks (status in the legacy lifecycle set) bypass the gate
    so existing flows are not disrupted.
    """
    try:
        from app.services.notion_task_reader import get_notion_task_by_id
        task = get_notion_task_by_id(task_id)
    except Exception as exc:
        logger.warning("[DEPLOY_GATE] failed to read task page task_id=%s: %s", task_id, exc)
        return False, "unable to read task metadata from Notion"

    if task is None:
        return False, "task not found in Notion"

    current_status = (task.get("status") or "").strip().lower()

    legacy_statuses = {"planned", "in-progress", "testing", "deployed"}
    if current_status in legacy_statuses:
        return True, f"legacy lifecycle (status={current_status}) — gate bypassed"

    test_status_raw = (task.get("test_status") or "").strip()
    if not test_status_raw:
        if current_status == "awaiting-deploy-approval":
            logger.info(
                "[DEPLOY_GATE] Test Status property empty/missing but task is in "
                "awaiting-deploy-approval — trusting orchestrator test gate "
                "task_id=%s", task_id,
            )
            return True, (
                "Test gate: task status (awaiting-deploy-approval). "
                "Add a 'Test Status' property to the AI Task System DB to persist test results."
            )
        return False, "Test Status is empty — tests must pass before deploy"

    test_status_lower = test_status_raw.lower()

    if test_status_lower.startswith("passed"):
        return True, f"tests passed ({test_status_raw[:80]})"

    if test_status_lower.startswith("failed"):
        return False, f"tests failed ({test_status_raw[:80]})"

    if test_status_lower.startswith("partial"):
        return False, f"tests partial ({test_status_raw[:80]})"

    if test_status_lower.startswith("not-run") or test_status_lower.startswith("not run"):
        return False, f"tests not run ({test_status_raw[:80]})"

    if "passed" in test_status_lower:
        return True, f"tests passed ({test_status_raw[:80]})"

    return False, f"unrecognised test status: {test_status_raw[:80]}"


def _handle_extended_approval_callback(
    chat_id: str,
    user_id: str,
    username: str,
    callback_data: str,
    action: str,
    message_id: Optional[int] = None,
) -> None:
    """Handle extended lifecycle approval actions: approve_patch, approve_deploy, reject, view_report."""
    logger.info(
        "[TG][EXT_APPROVAL] action=%s callback_data=%s chat_id=%s user_id=%s message_id=%s",
        action, callback_data[:60], chat_id, user_id, message_id,
    )
    try:
        from app.services.agent_telegram_approval import (
            PREFIX_APPROVE_PATCH,
            PREFIX_APPROVE_DEPLOY,
            PREFIX_REJECT,
            PREFIX_VIEW_REPORT,
            PREFIX_SMOKE_CHECK,
            PREFIX_REINVESTIGATE,
            PREFIX_RUN_CURSOR_BRIDGE,
            get_openclaw_report_for_task,
        )
    except ImportError as imp_err:
        logger.error("[TG][EXT_APPROVAL] import failed: %s", imp_err, exc_info=True)
        send_command_response(chat_id, "❌ Extended approval module unavailable.")
        return

    # Extract task_id from callback_data
    task_id = ""
    for prefix in (PREFIX_APPROVE_PATCH, PREFIX_APPROVE_DEPLOY, PREFIX_REJECT, PREFIX_VIEW_REPORT, PREFIX_SMOKE_CHECK, PREFIX_REINVESTIGATE, PREFIX_RUN_CURSOR_BRIDGE):
        if callback_data.startswith(prefix):
            task_id = callback_data[len(prefix):].strip()
            break
    if not task_id:
        logger.warning("[TG][EXT_APPROVAL] missing task_id in callback_data=%s", callback_data)
        send_command_response(chat_id, "❌ Invalid callback (missing task_id).")
        return

    who = username or user_id or "unknown"

    if action == "view_report":
        report_html = get_openclaw_report_for_task(task_id)
        send_command_response(chat_id, f"📋 <b>OpenClaw report</b>\n\n{report_html[:3800]}")
        return

    # Actions that change Notion status
    try:
        from app.services.notion_tasks import (
            TASK_STATUS_READY_FOR_PATCH,
            TASK_STATUS_DEPLOYING,
            TASK_STATUS_REJECTED,
            update_notion_task_status,
        )
    except ImportError as imp_err:
        logger.error("[TG][EXT_APPROVAL] notion_tasks import failed: %s", imp_err, exc_info=True)
        send_command_response(chat_id, "❌ Status update module unavailable.")
        return

    if action == "approve_patch":
        ok = update_notion_task_status(task_id, TASK_STATUS_READY_FOR_PATCH,
                                       append_comment=f"Patch approved by {who} via Telegram.")
        if ok:
            logger.info("[TG][EXT_APPROVAL] task %s → ready-for-patch by %s", task_id, who)
            extra_rows = []
            try:
                from app.services.agent_telegram_approval import PREFIX_RUN_CURSOR_BRIDGE
                from app.services._paths import workspace_root
                handoff_path = workspace_root() / "docs" / "agents" / "cursor-handoffs" / f"cursor-handoff-{task_id}.md"
                if handoff_path.exists():
                    extra_rows = [[{"text": "🛠️ Run Cursor Bridge", "callback_data": f"{PREFIX_RUN_CURSOR_BRIDGE}{task_id}"}]]
            except Exception:
                pass
            _edit_approval_card(chat_id, message_id,
                                f"✅ <b>Patch approved</b> by {who}\nTask moved to <b>ready-for-patch</b>.", task_id,
                                extra_rows=extra_rows)
        else:
            logger.warning("[TG][EXT_APPROVAL] Notion status update failed task_id=%s", task_id)
            _edit_approval_card(chat_id, message_id,
                                f"⚠️ Patch approved by {who} but Notion status update failed.", task_id)

        # Best-effort: ensure a Cursor handoff prompt exists for this task
        try:
            from app.services.cursor_handoff import generate_cursor_handoff
            handoff = generate_cursor_handoff({"task": {"id": task_id, "task": ""}, "_openclaw_sections": {}})
            if handoff.get("success"):
                logger.info("[TG][EXT_APPROVAL] Cursor handoff ensured for task %s", task_id)
        except Exception as handoff_err:
            logger.debug("[TG][EXT_APPROVAL] Cursor handoff generation skipped: %s", handoff_err)

        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("patch_approved", task_id=task_id, details={"approved_by": who, "notion_updated": ok})
        except Exception:
            pass
        return

    if action == "approve_deploy":
        # --- Deploy gate: require passing test status ---
        gate_passed, gate_reason = _check_deploy_test_gate(task_id)
        if not gate_passed:
            logger.info(
                "[TG][EXT_APPROVAL] deploy blocked by test gate task_id=%s reason=%s who=%s",
                task_id, gate_reason, who,
            )
            send_command_response(
                chat_id,
                f"🚫 <b>Deploy blocked</b>\n\n"
                f"Task <code>{task_id[:12]}</code> cannot be deployed.\n"
                f"<b>Reason:</b> {gate_reason}\n\n"
                f"Tests must pass before deploy approval. "
                f"Check the task's <b>Test Status</b> in Notion or re-run tests.",
            )
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("deploy_blocked_by_test_gate", task_id=task_id,
                                details={"who": who, "reason": gate_reason})
            except Exception:
                pass
            return

        ok = update_notion_task_status(task_id, TASK_STATUS_DEPLOYING,
                                       append_comment=f"Deploy approved by {who} via Telegram. (Test gate: {gate_reason})")
        if ok:
            try:
                from app.services.notion_tasks import update_notion_deploy_progress
                update_notion_deploy_progress(task_id, 0)
            except Exception:
                pass
            logger.info("[TG][EXT_APPROVAL] task %s → deploying by %s", task_id, who)
            _edit_approval_card(chat_id, message_id,
                                f"🚀 <b>Deploy approved</b> by {who}\nTask moved to <b>deploying</b>.", task_id)
        else:
            logger.warning("[TG][EXT_APPROVAL] Notion status update failed task_id=%s", task_id)
            _edit_approval_card(chat_id, message_id,
                                f"⚠️ Deploy approved by {who} but Notion status update failed.", task_id)

        # --- Trigger real deployment via GitHub Actions ---
        deploy_result: dict = {}
        try:
            from app.services.deploy_trigger import trigger_deploy_workflow
            deploy_result = trigger_deploy_workflow(task_id=task_id, triggered_by=who)
            if deploy_result.get("ok"):
                try:
                    from app.services.notion_tasks import update_notion_deploy_progress
                    update_notion_deploy_progress(task_id, 20)
                except Exception:
                    pass
                logger.info(
                    "[TG][EXT_APPROVAL] deploy workflow triggered task_id=%s summary=%s",
                    task_id, deploy_result.get("summary"),
                )
                send_command_response(
                    chat_id,
                    f"⚙️ <b>Deploy triggered</b>\n\n"
                    f"{deploy_result.get('summary', '')}\n\n"
                    f"Use the <b>Smoke Check</b> button after ~5 min to verify.",
                )
            else:
                error = deploy_result.get("error") or deploy_result.get("summary") or "unknown error"
                logger.error(
                    "[TG][EXT_APPROVAL] deploy trigger FAILED task_id=%s error=%s",
                    task_id, error,
                )
                send_command_response(
                    chat_id,
                    f"⚠️ <b>Deploy trigger failed</b>\n\n"
                    f"Task is in <b>deploying</b> but the workflow could not be dispatched.\n"
                    f"<b>Error:</b> <code>{str(error)[:300]}</code>\n\n"
                    f"You can trigger the deploy manually from GitHub Actions.",
                )
        except Exception as deploy_exc:
            logger.error(
                "[TG][EXT_APPROVAL] deploy trigger raised task_id=%s: %s",
                task_id, deploy_exc, exc_info=True,
            )
            send_command_response(
                chat_id,
                f"⚠️ <b>Deploy trigger error</b>\n\n"
                f"Task is in <b>deploying</b> but an error occurred: <code>{str(deploy_exc)[:300]}</code>\n\n"
                f"You can trigger the deploy manually from GitHub Actions.",
            )

        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("deploy_approved", task_id=task_id, details={
                "approved_by": who,
                "notion_updated": ok,
                "deploy_triggered": deploy_result.get("ok", False),
                "deploy_summary": deploy_result.get("summary", ""),
            })
        except Exception:
            pass
        return

    if action == "smoke_check":
        send_command_response(chat_id, f"🔍 Running post-deploy smoke check for task <code>{task_id[:12]}</code>…")
        try:
            from app.services.deploy_smoke_check import (
                run_and_record_smoke_check,
                format_smoke_result_for_telegram,
            )
            smoke = run_and_record_smoke_check(task_id, advance_on_pass=True, current_status="deploying")
            report = format_smoke_result_for_telegram(smoke)
            send_command_response(chat_id, report)
            logger.info(
                "[TG][EXT_APPROVAL] smoke check completed task_id=%s outcome=%s",
                task_id, smoke.get("outcome"),
            )
        except Exception as smoke_err:
            logger.error("[TG][EXT_APPROVAL] smoke check failed task_id=%s: %s", task_id, smoke_err, exc_info=True)
            send_command_response(chat_id, f"❌ Smoke check error: {str(smoke_err)[:200]}")
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("smoke_check_triggered", task_id=task_id, details={"triggered_by": who, "source": "telegram"})
        except Exception:
            pass
        return

    if action == "reinvestigate":
        from app.services.notion_tasks import TASK_STATUS_READY_FOR_INVESTIGATION, update_notion_task_status
        ok = update_notion_task_status(
            task_id,
            TASK_STATUS_READY_FOR_INVESTIGATION,
            append_comment=f"Re-investigate approved by {who} via Telegram. Scheduler will re-run with verification feedback.",
        )
        if ok:
            logger.info("[TG][EXT_APPROVAL] task %s → ready-for-investigation (reinvestigate) by %s", task_id, who)
            _edit_approval_card(chat_id, message_id,
                                f"🔄 <b>Re-investigate</b> by {who}\nTask moved to <b>ready-for-investigation</b>. "
                                "Scheduler will re-run with feedback.", task_id)
            send_command_response(
                chat_id,
                f"🔄 Task <code>{task_id[:12]}</code> moved to <b>ready-for-investigation</b>.\n\n"
                "The scheduler will re-run the investigation with the verification feedback "
                "(next cycle, typically within 5 min).",
            )
        else:
            _edit_approval_card(chat_id, message_id,
                                f"⚠️ Re-investigate by {who} but Notion status update failed.", task_id)
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("reinvestigate_approved", task_id=task_id, details={"approved_by": who, "notion_updated": ok})
        except Exception:
            pass
        return

    if action == "reject":
        ok = update_notion_task_status(task_id, TASK_STATUS_REJECTED,
                                       append_comment=f"Task rejected by {who} via Telegram.")
        if ok:
            logger.info("[TG][EXT_APPROVAL] task %s → rejected by %s", task_id, who)
            _edit_approval_card(chat_id, message_id,
                                f"❌ <b>Rejected</b> by {who}\nTask marked as <b>rejected</b>.", task_id)
        else:
            logger.warning("[TG][EXT_APPROVAL] Notion status update failed task_id=%s", task_id)
            _edit_approval_card(chat_id, message_id,
                                f"⚠️ Rejected by {who} but Notion status update failed.", task_id)

        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("task_rejected", task_id=task_id, details={"rejected_by": who, "notion_updated": ok})
        except Exception:
            pass
        return

    if action == "run_cursor_bridge":
        _edit_approval_card(chat_id, message_id,
                            f"🛠️ <b>Running Cursor Bridge</b> for task {task_id[:12]}…", task_id)
        try:
            from app.services.cursor_execution_bridge import is_bridge_enabled, run_bridge_phase2
            from app.services.notion_tasks import update_notion_task_status
            update_notion_task_status(task_id, "patching", append_comment=f"Cursor bridge triggered by {who} via Telegram.")
            if not is_bridge_enabled():
                send_command_response(chat_id, "❌ Cursor bridge disabled. Set CURSOR_BRIDGE_ENABLED=true.")
                _edit_approval_card(chat_id, message_id,
                                    f"✅ <b>Patch approved</b> by {who}\nTask in <b>ready-for-patch</b>.\n\n"
                                    "Bridge disabled.", task_id)
                return
            result = run_bridge_phase2(task_id=task_id, ingest=True, create_pr=False, current_status="patching")
            if result.get("ok") and result.get("tests_ok"):
                send_command_response(chat_id,
                    f"✅ <b>Cursor Bridge OK</b>\n\nTask {task_id[:12]}…: apply + tests passed.\n"
                    "Task advanced to awaiting-deploy-approval.")
                _edit_approval_card(chat_id, message_id,
                                    f"✅ <b>Cursor Bridge</b> by {who}\nApply + tests passed.", task_id)
            else:
                err = result.get("error") or "bridge failed"
                send_command_response(chat_id, f"⚠️ <b>Cursor Bridge</b>\n\n{err[:300]}")
                _edit_approval_card(chat_id, message_id,
                                    f"⚠️ <b>Cursor Bridge</b> by {who}\n{err[:100]}", task_id)
        except Exception as exc:
            logger.exception("[TG][EXT_APPROVAL] run_cursor_bridge failed task_id=%s", task_id)
            send_command_response(chat_id, f"❌ Bridge error: {str(exc)[:200]}")
            _edit_approval_card(chat_id, message_id,
                                f"❌ <b>Cursor Bridge</b> error.", task_id)
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("cursor_bridge_telegram_triggered", task_id=task_id, details={"triggered_by": who})
        except Exception:
            pass
        return

    logger.warning("[TG][EXT_APPROVAL] unrecognised action=%s task_id=%s", action, task_id)
    send_command_response(chat_id, f"❓ Unknown action: {action}")


def _handle_setting_callback(chat_id: str, callback_data: str, message_id: Optional[int], db: Optional[Session]) -> None:
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
            sym = getattr(item, "symbol", None)
            if sym is None or not str(sym).strip():
                continue
            symbol_str = str(sym)
            coin_config = coins_config.get(symbol_str, {})
            preset = coin_config.get("preset", "swing")
            
            # Handle preset formats like "swing-conservative" or just "swing"
            if "-" in preset:
                # Already includes risk mode
                strategy_set.add(preset)
            else:
                _rm = getattr(item, "sl_tp_mode", None)
                risk_mode = str(_rm) if _rm is not None else "conservative"
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
            _sym = getattr(item, "symbol", None)
            symbol_str = str(_sym) if _sym is not None else ""
            coin_config = coins_config.get(symbol_str, {})
            coin_preset = coin_config.get("preset", "swing")
            
            if "-" in coin_preset:
                coin_preset_base, coin_risk = coin_preset.split("-", 1)
                if coin_preset_base == preset and coin_risk == risk_mode:
                    matching_items.append(item)
            else:
                _cr = getattr(item, "sl_tp_mode", None)
                coin_risk = str(_cr) if _cr is not None else "conservative"
                if coin_preset == preset:
                    if risk_mode is None or coin_risk == risk_mode:
                        matching_items.append(item)
        
        if not matching_items:
            return "N/A"
        
        values = []
        for item in matching_items:
            pct = getattr(item, "min_price_change_pct", None)
            if pct is not None and isinstance(pct, (int, float)):
                values.append(float(pct))
        
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
            _sym = getattr(item, "symbol", None)
            symbol_str = str(_sym) if _sym is not None else ""
            coin_config = coins_config.get(symbol_str, {})
            coin_preset = coin_config.get("preset", "swing")
            
            if "-" in coin_preset:
                coin_preset_base, coin_risk = coin_preset.split("-", 1)
                if coin_preset_base == preset and coin_risk == risk_mode:
                    matching_items.append(item)
            else:
                _cr = getattr(item, "sl_tp_mode", None)
                coin_risk = str(_cr) if _cr is not None else "conservative"
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
                if hasattr(item, "min_price_change_pct"):
                    setattr(item, "min_price_change_pct", new_value)
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
    from app.utils.http_client import http_get, http_post

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

