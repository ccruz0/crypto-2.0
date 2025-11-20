"""

Telegram Command Handler
Handles incoming Telegram commands and responds with formatted messages
"""
import os
import logging
import requests
from typing import Optional, Dict, List
from datetime import datetime, timedelta
import pytz
from app.services.telegram_notifier import telegram_notifier
from sqlalchemy.orm import Session
from app.models.watchlist import WatchlistItem

logger = logging.getLogger(__name__)

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
LAST_UPDATE_ID = 0  # Global variable to track last processed update


def _build_keyboard(rows: List[List[Dict[str, str]]]) -> Dict[str, List[List[Dict[str, str]]]]:
    """Create inline keyboard payload."""
    return {"inline_keyboard": rows}


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
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to send menu message: {e}", exc_info=True)
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
            # Message might be unchanged; ignore
            logger.debug(f"[TG] editMessageText warning: {response.text}")
            return False
        response.raise_for_status()
        return True
    except Exception as e:
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


def get_telegram_updates(offset: Optional[int] = None) -> List[Dict]:
    """Get updates from Telegram API using long polling"""
    if not TELEGRAM_ENABLED:
        return []
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
        params = {}
        if offset is not None:
            params["offset"] = offset
        # Use long polling: Telegram will wait up to 30 seconds for new messages
        # This allows real-time command processing
        params["timeout"] = 30
        
        # Increase timeout to 35 seconds to account for network delay
        response = requests.get(url, params=params, timeout=35)
        response.raise_for_status()
        
        data = response.json()
        if data.get("ok"):
            return data.get("result", [])
        return []
    except requests.exceptions.Timeout:
        # Timeout is expected when no new messages - return empty list
        return []
    except requests.exceptions.HTTPError as http_err:
        # If webhook is still configured elsewhere Telegram returns 409. Log once as warning.
        status = getattr(http_err.response, 'status_code', None)
        if status == 409:
            logger.warning("[TG] getUpdates conflict (409). Another webhook or polling client is active. Skipping this cycle.")
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


def send_welcome_message(chat_id: str) -> bool:
    """Send welcome message with menu"""
    try:
        # Show the main menu instead of just text commands
        return show_main_menu(chat_id, db=None)
    except Exception as e:
        logger.error(f"[TG][ERROR] Error in welcome message: {e}", exc_info=True)
        # Fallback to text message with menu button
        message = """🎉 <b>Welcome to Trading Bot</b>

Use the menu below to access all features.

<b>Note:</b> Only authorized users can use these commands."""
        keyboard = _build_keyboard([
            [{"text": "📋 Open Main Menu", "callback_data": "menu:main"}]
        ])
        return _send_menu_message(chat_id, message, keyboard)


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
    """Show main menu with buttons matching dashboard layout"""
    try:
        text = "📋 <b>Main Menu</b>\n\nSelect an option:"
        
        keyboard = _build_keyboard([
            [
                {"text": "💼 Portfolio", "callback_data": "cmd:portfolio"},
            ],
            [
                {"text": "👀 Watchlist", "callback_data": "cmd:watchlist"},
            ],
            [
                {"text": "📋 Open Orders", "callback_data": "cmd:open_orders"},
            ],
            [
                {"text": "✅ Executed Orders", "callback_data": "cmd:executed_orders"},
            ],
            [
                {"text": "📝 Version", "callback_data": "cmd:version"},
            ],
        ])
        
        return _send_menu_message(chat_id, text, keyboard)
    except Exception as e:
        logger.error(f"[TG][ERROR] Error showing main menu: {e}", exc_info=True)
        return send_command_response(chat_id, f"❌ Error showing menu: {str(e)}")


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
                    WatchlistItem.trade_enabled == True
                ).count()
                
                # Count tracked coins (coins with Trade=YES)
                tracked_coins = db.query(WatchlistItem).filter(
                    WatchlistItem.trade_enabled == True,
                    WatchlistItem.symbol.isnot(None)
                ).count()
                
                # Get coins with Trade=YES for auto trading and trade amounts
                active_trade_coins = db.query(WatchlistItem).filter(
                    WatchlistItem.trade_enabled == True,
                    WatchlistItem.symbol.isnot(None)
                ).all()
                
                for coin in active_trade_coins:
                    symbol = coin.symbol or "N/A"
                    margin = "✅" if coin.trade_on_margin else "❌"
                    auto_trading_coins.append(f"{symbol} (Margin: {margin})")
                    
                    amount = coin.trade_amount_usd or 0
                    if amount > 0:
                        trade_amounts_list.append(f"{symbol}: ${amount:,.2f}")
                    else:
                        trade_amounts_list.append(f"{symbol}: N/A")
                
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
                from datetime import datetime, timedelta
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
• Tracked Coins (Trade=YES): {tracked_coins}
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
    """Send portfolio with exchange balances and open orders"""
    try:
        if not db:
            return send_command_response(chat_id, "❌ Database not available")
        
        # Import ExchangeBalance and ExchangeOrder models
        from app.models.exchange_balance import ExchangeBalance
        from app.models.exchange_order import ExchangeOrder
        from app.models.trade_signal import TradeSignal
        
        # Get exchange balances
        balances = db.query(ExchangeBalance).filter(
            ExchangeBalance.total > 0
        ).order_by(ExchangeBalance.total.desc()).all()
        
        # Get open orders
        from app.models.exchange_order import OrderStatusEnum
        open_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.status.in_([
                OrderStatusEnum.NEW,
                OrderStatusEnum.ACTIVE,
                OrderStatusEnum.PARTIALLY_FILLED
            ])
        ).order_by(ExchangeOrder.exchange_create_time.desc()).limit(5).all()
        
        # Calculate total portfolio value (simplified - assuming balances are in USD equivalent)
        total_usd = sum(float(bal.total) for bal in balances if bal.asset == 'USDT')
        
        # Build message
        if not balances:
            message = """💰 *Exchange Portfolio*

No balances found.
Check if exchange sync is running and API credentials are configured."""
        else:
            message = f"""💰 *Exchange Portfolio*

💵 *Total USDT:* ${total_usd:,.2f}

📊 *Balances:* ({len(balances)} assets)"""

            for bal in balances[:10]:  # Show top 10
                asset = bal.asset
                free = float(bal.free)
                locked = float(bal.locked)
                total = float(bal.total)
                
                # Format based on asset type
                if asset == 'USDT' or asset == 'USD':
                    free_str = f"${free:,.2f}"
                    locked_str = f"${locked:,.2f}"
                    total_str = f"${total:,.2f}"
                elif total >= 1:
                    free_str = f"{free:,.4f}"
                    locked_str = f"{locked:,.4f}"
                    total_str = f"{total:,.4f}"
                else:
                    free_str = f"{free:.8f}"
                    locked_str = f"{locked:.8f}"
                    total_str = f"{total:.8f}"
                
                locked_indicator = "🔒" if locked > 0 else ""
                
                message += f"""

🪙 *{asset}*
• Free: {free_str}
• Locked: {locked_str} {locked_indicator}
• Total: {total_str}"""
            
            if len(balances) > 10:
                message += f"\n\n… and {len(balances) - 10} more assets"
        
        # Add open orders section
        if open_orders:
            message += f"""

📋 *Open Orders ({len(open_orders)})*"""

            for order in open_orders:
                symbol = order.symbol or "N/A"
                side = order.side.value if order.side else "N/A"
                status = order.status.value if order.status else "N/A"
                quantity = float(order.quantity) if order.quantity else 0
                price = float(order.price) if order.price else 0
                
                price_str = f"${price:,.4f}" if price > 0 else "Market"
                quantity_str = f"{quantity:,.6f}" if quantity >= 0.000001 else f"{quantity:.8f}"
                
                message += f"""

🔴 *{symbol}* {side}
• Type: {order.order_type or 'LIMIT'}
• Quantity: {quantity_str}
• Price: {price_str}
• Status: {status}"""
        
        logger.info(f"[TG][CMD] /portfolio")
        return send_command_response(chat_id, message)
    except Exception as e:
        logger.error(f"[TG][ERROR] Failed to build portfolio: {e}")
        return send_command_response(chat_id, f"❌ Error building portfolio: {str(e)}")


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
        
        # Import config loader to get strategy names
        from app.services.config_loader import load_config
        
        config = load_config()
        coins_config = config.get("coins", {})
        
        # Get coins with Trade=YES only
        coins = db.query(WatchlistItem).filter(
            WatchlistItem.trade_enabled == True,
            WatchlistItem.symbol.isnot(None)
        ).order_by(WatchlistItem.symbol).all()
        
        logger.info(f"[TG][WATCHLIST] Found {len(coins)} coins with Trade=YES")
        for coin in coins:
            logger.info(f"[TG][WATCHLIST] {coin.symbol}: trade_enabled={coin.trade_enabled}, trade_amount_usd={coin.trade_amount_usd}, price={coin.price}")
        
        if not coins:
            message = """👀 <b>Watchlist</b>

No coins with Trade=YES."""
        else:
            message = f"""👀 <b>Watchlist ({len(coins)} coins with Trade=YES)</b>"""
            
            for coin in coins:
                symbol = coin.symbol or "N/A"
                last_price = coin.price or 0
                buy_target = coin.buy_target or "N/A"
                
                # Get strategy name in full format (e.g., "swing-conservative", "intradia-agresiva")
                coin_config = coins_config.get(symbol, {})
                preset = coin_config.get("preset", "swing")
                
                # Handle preset formats like "swing-conservative" or just "swing"
                if "-" in preset:
                    # Already includes risk mode (e.g., "swing-conservative")
                    strategy_name = preset
                else:
                    # Get risk mode from watchlist item and combine
                    risk_mode = coin.sl_tp_mode or "conservative"
                    strategy_name = f"{preset}-{risk_mode}"
                
                # Status indicators
                alert_status = "✅ Alert" if coin.alert_enabled else "❌ Alert"
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
                    amount_str = f"${coin.trade_amount_usd:,.2f}"
                else:
                    amount_str = "N/A"
                
                message += f"""

📊 <b>{symbol}</b>
  📈 Strategy: <b>{strategy_name}</b>
  {alert_status} | {margin_status}
  💰 Price: {price_str} | Target: {target_str}
  💵 Amount: {amount_str}"""
        
        logger.info(f"[TG][CMD] /watchlist")
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
        from datetime import datetime, timedelta, timezone
        
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
    # Handle callback_query (button clicks)
    callback_query = update.get("callback_query")
    if callback_query:
        from_user = callback_query.get("from", {})
        chat_id = str(from_user.get("id", ""))
        callback_data = callback_query.get("data", "")
        
        # Only authorized user
        if chat_id != AUTH_CHAT_ID:
            logger.warning(f"[TG][DENY] callback_query from chat_id={chat_id}")
            return
        
        # Answer callback query to remove loading state
        callback_query_id = callback_query.get("id")
        if callback_query_id:
            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
                requests.post(url, json={"callback_query_id": callback_query_id}, timeout=5)
            except:
                pass
        
        # Process callback data
        logger.info(f"[TG] Processing callback_query: {callback_data} from chat_id={chat_id}")
        
        if callback_data.startswith("analyze_"):
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
            elif cmd == "executed_orders":
                send_executed_orders_message(chat_id, db)
            elif cmd == "version":
                send_version_message(chat_id)
            elif cmd == "alerts":
                send_alerts_list_message(chat_id, db)
            elif cmd == "help":
                send_help_message(chat_id)
        elif callback_data.startswith("setting:"):
            # Handle settings menu callbacks (e.g., setting:min_price_change_pct:select_strategy)
            _handle_setting_callback(chat_id, callback_data, callback_query.get("message", {}).get("message_id"), db)
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
    
    # Only authorized user
    if chat_id != AUTH_CHAT_ID:
        logger.warning(f"[TG][DENY] chat_id={chat_id}")
        send_command_response(chat_id, "⛔ Not authorized")
        return
    
    # Parse command
    text = text.strip()
    
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
        send_welcome_message(chat_id)
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
    global LAST_UPDATE_ID
    
    try:
        # Long polling: Telegram will wait up to 30 seconds for new messages
        # This allows immediate processing when a command is sent
        offset = LAST_UPDATE_ID + 1 if LAST_UPDATE_ID > 0 else None
        updates = get_telegram_updates(offset=offset)
        
        if not updates:
            # No new updates (this is normal with long polling timeout)
            return
        
        logger.info(f"[TG] ⚡ Received {len(updates)} update(s) - processing immediately")
        
        for update in updates:
            update_id = update.get("update_id", 0)
            message = update.get("message") or update.get("edited_message")
            callback_query = update.get("callback_query")
            
            if callback_query:
                callback_data = callback_query.get("data", "")
                from_user = callback_query.get("from", {})
                chat_id = from_user.get("id", "")
                logger.info(f"[TG] ⚡ Processing callback_query: '{callback_data}' from chat_id={chat_id}, update_id={update_id}")
            elif message:
                text = message.get("text", "")
                chat_id = message.get("chat", {}).get("id", "")
                logger.info(f"[TG] ⚡ Processing command: '{text}' from chat_id={chat_id}, update_id={update_id}")
            else:
                logger.debug(f"[TG] Update {update_id} has no message or callback_query (might be other type)")
                # Update ID anyway to skip this update
                LAST_UPDATE_ID = update_id
                continue
            
            # Process update immediately
            try:
                handle_telegram_update(update, db)
            except Exception as handle_error:
                logger.error(f"[TG] Error handling update {update_id}: {handle_error}", exc_info=True)
            
            # Update last processed ID
            LAST_UPDATE_ID = update_id
            
    except Exception as e:
        logger.error(f"[TG] Error processing commands: {e}", exc_info=True)


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

