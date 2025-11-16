import os
import logging
import requests
from typing import Optional
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

class TelegramNotifier:
    """Telegram notification service for trading alerts"""
    
    def __init__(self):
        # Use provided bot token and chat ID, or fall back to environment variables
        # If env var is empty string, use default value
        env_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        env_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.bot_token = env_bot_token if env_bot_token else "7401938912:AAEnct4H1QOsxMJz5a6Nr1QlfzYso53caTY"
        self.chat_id = env_chat_id if env_chat_id else "839853931"
        self.enabled = bool(self.bot_token and self.chat_id)
        
        # Timezone configuration - defaults to Asia/Makassar (Bali time UTC+8), can be overridden with TELEGRAM_TIMEZONE env var
        # Examples: "Asia/Makassar" (Bali), "Europe/Madrid" (Spain), "Europe/Paris" (France), etc.
        timezone_name = os.getenv("TELEGRAM_TIMEZONE", "Asia/Makassar")
        try:
            self.timezone = pytz.timezone(timezone_name)
            logger.info(f"Telegram Notifier timezone set to: {timezone_name}")
        except pytz.exceptions.UnknownTimeZoneError:
            logger.warning(f"Unknown timezone '{timezone_name}', falling back to Asia/Makassar")
            self.timezone = pytz.timezone("Asia/Makassar")
        
        if self.enabled:
            logger.info("Telegram Notifier initialized")
            # Set bot commands menu on initialization
            self.set_bot_commands()
        else:
            logger.warning("Telegram Notifier disabled - missing bot_token or chat_id")
    
    def _format_timestamp(self) -> str:
        """Format current timestamp using configured timezone (Bali time)"""
        ts = datetime.now(self.timezone)
        return ts.strftime("%Y-%m-%d %H:%M:%S WIB")
    
    def set_bot_commands(self) -> bool:
        """Set bot commands menu for Telegram - only /menu command to avoid cluttering"""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/setMyCommands"
            # User requested: remove all commands from list, only keep /menu
            # All functionality is available through the menu buttons
            commands = [
                {"command": "menu", "description": "Open main menu"},
            ]
            
            payload = {
                "commands": commands
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.info("Bot commands menu configured - only /menu command visible")
            return True
            
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}")
            return False
    
    def send_message(self, message: str, reply_markup: Optional[dict] = None) -> bool:
        """Send a message to Telegram with optional inline keyboard"""
        if not self.enabled:
            logger.debug("Telegram notifications disabled")
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            if reply_markup:
                payload["reply_markup"] = reply_markup
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.info("Telegram message sent successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    def send_message_with_buttons(self, message: str, buttons: list) -> bool:
        """
        Send a message to Telegram with inline keyboard buttons
        
        Args:
            message: Message text (HTML format)
            buttons: List of button rows, each row is a list of buttons
                     Each button is a dict: {"text": "Button Text", "callback_data": "data"}
        
        Example:
            buttons = [
                [
                    {"text": "✅ Crear SL", "callback_data": "create_sl_ETH_USDT"},
                    {"text": "✅ Crear TP", "callback_data": "create_tp_ETH_USDT"}
                ],
                [
                    {"text": "⏭️ Saltar", "callback_data": "skip_sl_tp_ETH_USDT"}
                ]
            ]
        """
        if not self.enabled:
            logger.debug("Telegram notifications disabled")
            return False
        
        try:
            # Build inline keyboard markup
            inline_keyboard = []
            for row in buttons:
                keyboard_row = []
                for button in row:
                    keyboard_row.append({
                        "text": button["text"],
                        "callback_data": button["callback_data"]
                    })
                inline_keyboard.append(keyboard_row)
            
            reply_markup = {
                "inline_keyboard": inline_keyboard
            }
            
            return self.send_message(message, reply_markup)
            
        except Exception as e:
            logger.error(f"Failed to send Telegram message with buttons: {e}")
            return False
    
    def send_buy_alert(self, symbol: str, price: float, quantity: float, 
                       margin: bool = False, leverage: Optional[int] = None):
        """Send a buy order alert"""
        margin_text = f"🚀 On Margin ({leverage}x)" if margin else "💰 Spot"
        message = f"""
🟢 <b>BUY ORDER CREATED</b>

📊 Symbol: <b>{symbol}</b>
💵 Price: ${price:,.4f}
📦 Quantity: {quantity:,.6f}
{margin_text}
💸 Total: ${price * quantity:,.2f}
"""
        return self.send_message(message.strip())
    
    def send_order_created(self, symbol: str, side: str, price: float, 
                          quantity: float, order_id: str, 
                          margin: bool = False, leverage: Optional[int] = None,
                          dry_run: bool = False, order_type: str = "MARKET"):
        """Send notification when an order is created (BUY or SELL)"""
        side_emoji = "🟢" if side.upper() == "BUY" else "🔴"
        side_text = "BUY" if side.upper() == "BUY" else "SELL"
        margin_text = f"🚀 On Margin ({leverage}x)" if margin else "💰 Spot"
        dry_run_text = " 🧪 (DRY RUN)" if dry_run else ""
        
        # For MARKET orders, price is 0 (will be filled at market price)
        if order_type == "MARKET" and price == 0:
            price_text = "💵 Price: Market Price (will execute at current price)"
            if side.upper() == "BUY":
                # For BUY MARKET orders, quantity is amount_usd (passed from backend)
                # Don't show "Quantity" line since quantity is USD amount, not crypto quantity
                total_text = f"💸 <b>Total Value: ${quantity:,.2f} USD</b>"
                message = f"""
{side_emoji} <b>{side_text} ORDER CREATED{dry_run_text}</b>

📊 Symbol: <b>{symbol}</b>
{price_text}
{total_text}
{margin_text}
📋 Type: {order_type}
🆔 Order ID: {order_id}
"""
            else:  # SELL
                # For SELL MARKET orders, quantity is the amount of crypto to sell
                # Calculate estimated value (will execute at market price)
                total_text = f"📦 Quantity: {quantity:,.6f} (will sell at market price)"
                message = f"""
{side_emoji} <b>{side_text} ORDER CREATED{dry_run_text}</b>

📊 Symbol: <b>{symbol}</b>
{price_text}
{total_text}
{margin_text}
📋 Type: {order_type}
🆔 Order ID: {order_id}
"""
        else:
            # LIMIT orders or MARKET orders with known price
            price_text = f"💵 Price: ${price:,.4f}"
            total_value = price * quantity
            total_text = f"💸 <b>Total Value: ${total_value:,.2f} USD</b>"
        message = f"""
{side_emoji} <b>{side_text} ORDER CREATED{dry_run_text}</b>

📊 Symbol: <b>{symbol}</b>
{price_text}
📦 Quantity: {quantity:,.6f}
{total_text}
{margin_text}
📋 Type: {order_type}
🆔 Order ID: {order_id}
"""
        return self.send_message(message.strip())
    
    def send_executed_order(self, symbol: str, side: str, price: float, 
                           quantity: float, total_usd: float, order_id: Optional[str] = None,
                           order_type: Optional[str] = None,
                           entry_price: Optional[float] = None,
                           sl_price: Optional[float] = None,
                           tp_price: Optional[float] = None,
                           open_orders_count: Optional[int] = None,
                           order_role: Optional[str] = None):
        """Send an executed order notification with profit/loss calculations"""
        side_emoji = "🟢" if side == "BUY" else "🔴"
        order_id_text = f"\n🆔 Order ID: {order_id}" if order_id else ""
        
        # Build order type text - include role (TP/SL) if available
        if order_role:
            role_emoji = "🚀" if order_role == "TAKE_PROFIT" else "🛑" if order_role == "STOP_LOSS" else ""
            role_text = "Take Profit" if order_role == "TAKE_PROFIT" else "Stop Loss" if order_role == "STOP_LOSS" else order_role
            order_type_text = f"\n📋 Type: {order_type or 'LIMIT'} ({role_emoji} {role_text})"
        else:
            order_type_text = f"\n📋 Type: {order_type}" if order_type else "\n📋 Type: LIMIT"
        
        # Add open orders count information
        open_orders_text = ""
        if open_orders_count is not None:
            if open_orders_count > 3:
                open_orders_text = f"\n⚠️ <b>Open Orders: {open_orders_count} (WARNING: Should be ≤ 3)</b>"
            else:
                open_orders_text = f"\n📊 Open Orders: {open_orders_count}"
        
        # Calculate profit/loss if entry_price is provided (for SL/TP orders)
        profit_loss_text = ""
        if entry_price and entry_price > 0:
            if side == "SELL":  # SL or TP executed (selling position)
                # Calculate actual profit/loss
                profit_loss = (price - entry_price) * quantity
                profit_loss_pct = ((price - entry_price) / entry_price) * 100
                
                if profit_loss >= 0:
                    profit_loss_text = f"""
💰 <b>PROFIT REALIZED</b>
   💵 Entry Price: ${entry_price:,.4f}
   💰 Profit: +${profit_loss:,.2f} (+{profit_loss_pct:,.2f}%)
   📊 Total: ${total_usd:,.2f}"""
                else:
                    profit_loss_text = f"""
💰 <b>LOSS REALIZED</b>
   💵 Entry Price: ${entry_price:,.4f}
   💸 Loss: ${profit_loss:,.2f} ({profit_loss_pct:,.2f}%)
   📊 Total: ${total_usd:,.2f}"""
            elif side == "BUY":  # SL or TP executed (buying back short position)
                # Calculate actual profit/loss for short positions
                profit_loss = (entry_price - price) * quantity
                profit_loss_pct = ((entry_price - price) / entry_price) * 100
                
                if profit_loss >= 0:
                    profit_loss_text = f"""
💰 <b>PROFIT REALIZED</b>
   💵 Entry Price: ${entry_price:,.4f}
   💰 Profit: +${profit_loss:,.2f} (+{profit_loss_pct:,.2f}%)
   📊 Total: ${total_usd:,.2f}"""
                else:
                    profit_loss_text = f"""
💰 <b>LOSS REALIZED</b>
   💵 Entry Price: ${entry_price:,.4f}
   💸 Loss: ${profit_loss:,.2f} ({profit_loss_pct:,.2f}%)
   📊 Total: ${total_usd:,.2f}"""
        
        timestamp = self._format_timestamp()
        message = f"""
{side_emoji} <b>ORDER EXECUTED</b>

📊 Symbol: <b>{symbol}</b>
📈 Side: {side}
💵 Price: ${price:,.4f}
📦 Quantity: {quantity:,.6f}
💸 Total: ${total_usd:,.2f}{profit_loss_text}{order_type_text}{order_id_text}{open_orders_text}
📅 Time: {timestamp}
"""
        return self.send_message(message.strip())
    
    def send_sl_tp_orders(self, symbol: str, sl_price: float, tp_price: float, 
                         quantity: float, mode: str, 
                         sl_order_id: Optional[str] = None, 
                         tp_order_id: Optional[str] = None,
                         original_order_id: Optional[str] = None,
                         sl_side: Optional[str] = None,
                         tp_side: Optional[str] = None,
                         entry_price: Optional[float] = None,
                         sl_trigger_price: Optional[float] = None,
                         tp_trigger_price: Optional[float] = None,
                         sl_ref_price: Optional[float] = None,
                         tp_ref_price: Optional[float] = None,
                         sl_percentage: Optional[float] = None,
                         tp_percentage: Optional[float] = None,
                         original_order_side: Optional[str] = None):
        """Send SL/TP orders notification with profit/loss calculations and order details"""
        mode_emoji = "🛡️" if mode == "conservative" else "⚡"
        original_order_text = f"\n📋 Original Order ID: {original_order_id}" if original_order_id else ""
        
        # Determine SL side text
        if sl_side:
            sl_side_text = f" ({sl_side})"
            sl_emoji = "🔴" if sl_side == "SELL" else "🟢"
        else:
            sl_side_text = ""
            sl_emoji = "🔴"
        
        # Determine TP side text
        if tp_side:
            tp_side_text = f" ({tp_side})"
            tp_emoji = "🔴" if tp_side == "SELL" else "🟢"
        else:
            tp_side_text = ""
            tp_emoji = "🟢"
        
        # Calculate profit/loss if entry_price is provided
        profit_loss_text = ""
        if entry_price and entry_price > 0:
            # Determine original order side from sl_side or tp_side if not provided
            # For BUY orders: SL/TP are SELL (to close position)
            # For SELL orders: SL/TP are BUY (to close position)
            if not original_order_side:
                if sl_side == "SELL" or tp_side == "SELL":
                    original_order_side = "BUY"  # If SL/TP is SELL, original was BUY
                elif sl_side == "BUY" or tp_side == "BUY":
                    original_order_side = "SELL"  # If SL/TP is BUY, original was SELL
            
            # Calculate profit/loss based on original order side
            if original_order_side == "BUY":
                # For BUY orders:
                # - SL should be BELOW entry (loss if price drops)
                # - TP should be ABOVE entry (profit if price rises)
                # Both SL and TP are SELL orders to close the position
                sl_loss = (entry_price - sl_price) * quantity  # Loss if SL hits (price dropped)
                sl_loss_pct = ((entry_price - sl_price) / entry_price) * 100
                
                tp_profit = (tp_price - entry_price) * quantity  # Profit if TP hits (price rose)
                tp_profit_pct = ((tp_price - entry_price) / entry_price) * 100
            else:  # original_order_side == "SELL"
                # For SELL orders (short positions):
                # - SL should be ABOVE entry (loss if price rises)
                # - TP should be BELOW entry (profit if price drops)
                # Both SL and TP are BUY orders to close the position
                sl_loss = (sl_price - entry_price) * quantity  # Loss if SL hits (price rose)
                sl_loss_pct = ((sl_price - entry_price) / entry_price) * 100
                
                tp_profit = (entry_price - tp_price) * quantity  # Profit if TP hits (price dropped)
                tp_profit_pct = ((entry_price - tp_price) / entry_price) * 100
            
            # Format profit/loss text (always show absolute values with correct signs)
            profit_loss_text = f"""
💰 <b>PROFIT/LOSS ESTIMATES</b>
   💵 Entry Price: ${entry_price:,.4f}
   📉 If SL hits: ${sl_loss:,.2f} ({sl_loss_pct:,.2f}%)
   📈 If TP hits: ${tp_profit:,.2f} ({tp_profit_pct:,.2f}%)"""
        
        # Format SL order details with trigger and ref prices
        sl_trigger_text = ""
        if sl_trigger_price is not None:
            sl_trigger_text = f"\n   🎯 Trigger Price: ${sl_trigger_price:,.4f}"
            if sl_trigger_price == sl_price:
                sl_trigger_text += " ✅ (igual a SL price)"
            else:
                sl_trigger_text += f" ⚠️ (debe ser igual a SL price: ${sl_price:,.4f})"
        
        sl_ref_text = ""
        if sl_ref_price is not None:
            sl_ref_text = f"\n   📍 Ref Price: ${sl_ref_price:,.4f}"
            if sl_ref_price == sl_price:
                sl_ref_text += " ✅ (igual a SL price)"
            elif sl_trigger_price and sl_ref_price == sl_trigger_price:
                sl_ref_text += " ✅ (igual a trigger price)"
            else:
                sl_ref_text += f" ⚠️ (debe ser igual a trigger price: ${sl_trigger_price or sl_price:,.4f})"
        
        sl_order_details = ""
        if sl_order_id:
            sl_order_details = f"\n{sl_emoji} <b>SL Order Details:</b>"
            sl_order_details += f"\n   🆔 Order ID: {sl_order_id}"
            sl_order_details += f"\n   📊 Type: STOP_LIMIT{sl_side_text}"
            sl_order_details += f"\n   💵 Price: ${sl_price:,.4f}"
            sl_order_details += f"\n   📦 Quantity: {quantity:,.6f}"
            sl_order_details += sl_trigger_text
            sl_order_details += sl_ref_text
        elif sl_order_id is None:
            sl_order_details = f"\n❌ <b>SL Order:</b> FAILED (no se pudo crear)"
        
        # Format TP order details with trigger and execution prices (for TAKE_PROFIT_LIMIT)
        tp_trigger_text = ""
        if tp_trigger_price is not None:
            tp_trigger_text = f"\n   🎯 Trigger Price: ${tp_trigger_price:,.4f}"
            if tp_trigger_price == tp_price:
                tp_trigger_text += " ✅ (igual a TP price y execution price)"
            else:
                tp_trigger_text += f" ⚠️ (debe ser igual a TP price: ${tp_price:,.4f})"
        
        tp_order_details = ""
        if tp_order_id:
            tp_order_details = f"\n{tp_emoji} <b>TP Order Details:</b>"
            tp_order_details += f"\n   🆔 Order ID: {tp_order_id}"
            tp_order_details += f"\n   📊 Type: TAKE_PROFIT_LIMIT{tp_side_text}"
            tp_order_details += f"\n   💵 Execution Price: ${tp_price:,.4f}"
            tp_order_details += f"\n   📦 Quantity: {quantity:,.6f}"
            tp_order_details += tp_trigger_text  # Show trigger price info (should equal execution price)
        elif tp_order_id is None:
            tp_order_details = f"\n❌ <b>TP Order:</b> FAILED (no se pudo crear)"
        
        # Build strategy details section
        strategy_text = f"🎯 Mode: {mode.capitalize()}"
        if sl_percentage is not None or tp_percentage is not None:
            strategy_text += "\n📊 Strategy Details:"
            if sl_percentage is not None:
                strategy_text += f"\n   📉 SL: {sl_percentage:.2f}%"
            if tp_percentage is not None:
                strategy_text += f"\n   📈 TP: {tp_percentage:.2f}%"
            if sl_percentage is None and tp_percentage is None:
                # Use defaults based on mode
                default_sl = 2.0 if mode.lower() == "aggressive" else 3.0
                default_tp = 2.0 if mode.lower() == "aggressive" else 3.0
                strategy_text += f"\n   📉 SL: {default_sl:.2f}% (default)"
                strategy_text += f"\n   📈 TP: {default_tp:.2f}% (default)"
        
        timestamp = self._format_timestamp()
        message = f"""
{mode_emoji} <b>SL/TP ORDERS CREATED</b>

📊 Symbol: <b>{symbol}</b>
📦 Quantity: {quantity:,.6f}{profit_loss_text}
{strategy_text}{original_order_text}{sl_order_details}{tp_order_details}
📅 Time: {timestamp}
"""
        return self.send_message(message.strip())
    
    def send_buy_signal(self, symbol: str, price: float, reason: str, strategy: Optional[str] = None):
        """Send a buy signal alert"""
        strategy_text = ""
        if strategy:
            strategy_emoji = "🛡️" if strategy.lower() == "conservative" else "⚡"
            strategy_text = f"\n🎯 Strategy: {strategy_emoji} {strategy.capitalize()}"
        
        timestamp = self._format_timestamp()
        message = f"""
📊 <b>BUY SIGNAL DETECTED</b>

📈 Symbol: <b>{symbol}</b>
💵 Price: ${price:,.4f}
✅ Reason: {reason}{strategy_text}
📅 Time: {timestamp}
"""
        return self.send_message(message.strip())
    
    def format_signal_message(self, signal_type: str, coin: str, last_price: float, 
                             buy_target: Optional[float], sell_target: Optional[float], 
                             res_up: Optional[float], stop_loss: Optional[float], 
                             rsi: float, method: str, row_idx: Optional[int] = None,
                             extra: Optional[str] = None) -> str:
        """Format a trading signal message with all details according to requirements"""
        ts = self._format_timestamp()
        
        # Format price with appropriate precision
        if last_price >= 100:
            price_str = f"${last_price:,.2f}"
        else:
            price_str = f"${last_price:,.4f}"
        
        lines = [
            f"🔔 Nueva señal: {signal_type}",
            f"🪙 Coin: {coin}",
            f"💰 Precio actual: {price_str}",
        ]
        
        # Buy Target
        if buy_target is not None:
            if buy_target >= 100:
                buy_target_str = f"${buy_target:,.2f}"
            else:
                buy_target_str = f"${buy_target:,.4f}"
            lines.append(f"🎯 Buy Target: {buy_target_str}")
        else:
            lines.append(f"🎯 Buy Target: N/A")
        
        # Sell Target / Resistance Up
        if sell_target is not None:
            if sell_target >= 100:
                sell_target_str = f"${sell_target:,.2f}"
            else:
                sell_target_str = f"${sell_target:,.4f}"
            lines.append(f"📈 Sell Target / Resistance Up: {sell_target_str}")
        elif res_up is not None:
            if res_up >= 100:
                res_up_str = f"${res_up:,.2f}"
            else:
                res_up_str = f"${res_up:,.4f}"
            lines.append(f"📈 Sell Target / Resistance Up: {res_up_str}")
        else:
            lines.append(f"📈 Sell Target / Resistance Up: N/A")
        
        # Stop-Loss
        if stop_loss is not None:
            if stop_loss >= 100:
                stop_loss_str = f"${stop_loss:,.2f}"
            else:
                stop_loss_str = f"${stop_loss:,.4f}"
            lines.append(f"🛑 Stop-Loss: {stop_loss_str}")
        else:
            lines.append(f"🛑 Stop-Loss: N/A")
        
        # RSI with period indicator (using default 14)
        lines.append(f"📊 RSI: {rsi:.1f} (TF usada: 14)")
        
        # Method
        lines.append(f"📏 Método resistencia: {method}")
        
        # Timestamp
        lines.append(f"📅 Timestamp: {ts}")
        
        # Row index / Notes
        if row_idx is not None:
            lines.append(f"📓 Notas / sheet row: {row_idx}")
        else:
            lines.append(f"📓 Notas / sheet row: N/A")
        
        # Extra (e.g., ORDER PURCHASED = YES for SELL)
        if extra:
            lines.append(extra)
        
        return "\n".join(lines)
    
    def send_signal_message(self, signal_type: str, coin: str, last_price: float,
                           buy_target: Optional[float], sell_target: Optional[float],
                           res_up: Optional[float], stop_loss: Optional[float],
                           rsi: float, method: str, row_idx: Optional[int] = None,
                           extra: Optional[str] = None) -> bool:
        """Send a formatted trading signal message to Telegram"""
        try:
            message = self.format_signal_message(
                signal_type, coin, last_price, buy_target, sell_target,
                res_up, stop_loss, rsi, method, row_idx, extra
            )
            
            # Use Markdown instead of HTML for better formatting
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.info(f"[TELEGRAM] Alert sent for {coin} - {signal_type}")
            return True
            
        except Exception as e:
            logger.error(f"[TELEGRAM][ERROR] Failed to send signal alert: {e}")
            return False

# Global instance
telegram_notifier = TelegramNotifier()

