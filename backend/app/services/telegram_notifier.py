import os
import logging
import requests
import inspect
from typing import Optional
from datetime import datetime
from enum import Enum
import pytz
from app.core.config import Settings
from app.core.runtime import is_aws_runtime, get_runtime_origin
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

logger = logging.getLogger(__name__)


class AppEnv(str, Enum):
    """Application environment identifiers for alert routing"""
    AWS = "aws"
    LOCAL = "local"


def get_app_env() -> AppEnv:
    """
    Get the current application environment.
    
    Returns:
        AppEnv.AWS if APP_ENV=aws, otherwise AppEnv.LOCAL
        Defaults to LOCAL if APP_ENV is not set (with warning log)
    
    Configuration:
        - Set APP_ENV=aws on AWS deployment (alerts go to hilovivo-alerts-aws)
        - Set APP_ENV=local for local development (alerts go to hilovivo-alerts-local)
    """
    settings = Settings()
    env_override = os.getenv("APP_ENV")
    app_env = (env_override or settings.APP_ENV or "").strip().lower()
    if app_env == "aws":
        return AppEnv.AWS
    elif app_env == "local":
        return AppEnv.LOCAL
    else:
        # Default to LOCAL but log warning if APP_ENV is explicitly set to unknown value
        configured_value = env_override or settings.APP_ENV
        if configured_value:
            logger.warning(
                f"Unknown APP_ENV value '{configured_value}', defaulting to LOCAL. "
                f"Valid values are: 'aws' or 'local'"
            )
        else:
            logger.debug("APP_ENV not set, defaulting to LOCAL")
        return AppEnv.LOCAL

class TelegramNotifier:
    """Telegram notification service for trading alerts
    
    IMPORTANT: Telegram messages are ONLY sent from AWS environment.
    Local development must NEVER send Telegram messages.
    This is enforced via RUN_TELEGRAM environment variable.
    """
    
    def __init__(self):
        # Check if Telegram should be enabled based on environment flag
        settings = Settings()
        environment = (settings.ENVIRONMENT or "").strip().lower()
        app_env = (os.getenv("APP_ENV") or settings.APP_ENV or "").strip().lower()
        
        # Determine if we're on AWS
        is_aws = (
            app_env == "aws" or 
            environment == "aws" or 
            os.getenv("ENVIRONMENT", "").lower() == "aws" or
            os.getenv("APP_ENV", "").lower() == "aws"
        )
        
        run_telegram = (
            settings.RUN_TELEGRAM
            or os.getenv("RUN_TELEGRAM")
            or "true"
        )
        run_telegram = run_telegram.strip().lower()
        
        # Telegram is enabled whenever RUN_TELEGRAM=true (default), regardless of environment.
        # Set RUN_TELEGRAM=false to disable alerts entirely (used in certain tests/local runs).
        should_enable = run_telegram == "true"
        
        # Environment-only configuration
        bot_token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
        chat_id = (settings.TELEGRAM_CHAT_ID or "").strip()
        self.bot_token = bot_token or None
        self.chat_id = chat_id or None
        
        # Only enable if toggle allows it and credentials are configured
        self.enabled = should_enable and bool(self.bot_token and self.chat_id)
        
        if not should_enable:
            logger.info(
                f"Telegram disabled via RUN_TELEGRAM flag. Environment: {environment}, "
                f"APP_ENV: {app_env}, RUN_TELEGRAM: {run_telegram}, is_aws: {is_aws}"
            )
            return
        
        # Timezone configuration - defaults to Asia/Makassar (Bali time UTC+8), can be overridden with TELEGRAM_TIMEZONE env var
        # Examples: "Asia/Makassar" (Bali), "Europe/Madrid" (Spain), "Europe/Paris" (France), etc.
        timezone_name = os.getenv("TELEGRAM_TIMEZONE", "Asia/Makassar")
        try:
            self.timezone = pytz.timezone(timezone_name)
            logger.info(f"Telegram Notifier timezone set to: {timezone_name}")
        except pytz.exceptions.UnknownTimeZoneError:
            logger.warning(f"Unknown timezone '{timezone_name}', falling back to Asia/Makassar")
            self.timezone = pytz.timezone("Asia/Makassar")
        
        if not self.enabled:
            logger.warning("Telegram disabled: missing env vars")
            return

        logger.info("Telegram Notifier initialized")
        self.set_bot_commands()
    
    def _format_timestamp(self) -> str:
        """Format current timestamp using configured timezone (Bali time)"""
        ts = datetime.now(self.timezone)
        return ts.strftime("%Y-%m-%d %H:%M:%S WIB")
    
    def set_bot_commands(self) -> bool:
        """Set bot commands menu for Telegram - only /menu command to avoid cluttering"""
        if not self.enabled:
            logger.debug("Telegram disabled: skipping bot command configuration")
            return False
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
    
    def send_message(self, message: str, reply_markup: Optional[dict] = None, origin: Optional[str] = None) -> bool:
        """
        Send a message to Telegram with optional inline keyboard.
        
        This is the canonical helper that ALL alerts must route through.
        It automatically:
        - Blocks Telegram sends for non-AWS origins (logs instead)
        - Adds environment prefix [AWS] or [LOCAL] based on origin
        - Uses TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID from environment
        - Routes to the correct Telegram channel (hilovivo-alerts-aws or hilovivo-alerts-local)
        
        Args:
            message: Message text (HTML format supported)
            reply_markup: Optional inline keyboard markup
            origin: Origin identifier ("AWS" or "LOCAL"). If None, defaults to runtime origin.
                    Only "AWS" origin will actually send to Telegram.
            
        Returns:
            True if message sent successfully, False otherwise
        """
        # ============================================================
        # [TELEGRAM_INVOKE] - Diagnostic logging at entry point
        # ============================================================
        timestamp = datetime.now().isoformat()
        
        # Get caller information
        # Check if currentframe() returns None before accessing .f_back
        current_frame = inspect.currentframe()
        caller_frame = current_frame.f_back if current_frame is not None else None
        caller_path = "unknown"
        caller_function = "unknown"
        if caller_frame:
            try:
                caller_file = caller_frame.f_code.co_filename
                caller_function = caller_frame.f_code.co_name
                # Extract relative path from caller_file
                if "backend" in caller_file:
                    caller_path = caller_file.split("backend")[-1]
                else:
                    caller_path = os.path.basename(caller_file)
                caller_path = f"{caller_path}:{caller_frame.f_lineno} in {caller_function}"
            except Exception:
                pass
        
        # Extract symbol for logging
        symbol = None
        try:
            import re
            symbol_match = re.search(r'([A-Z]+_[A-Z]+|[A-Z]{2,5}(?:\s|:))', message)
            if symbol_match:
                potential_symbol = symbol_match.group(1).strip().rstrip(':').rstrip()
                if '_' in potential_symbol or len(potential_symbol) >= 2:
                    symbol = potential_symbol
        except Exception:
            pass
        
        # Get environment variables for diagnostics
        env_runtime_origin = os.getenv("RUNTIME_ORIGIN", "NOT_SET")
        env_aws_execution = os.getenv("AWS_EXECUTION_ENV", os.getenv("AWS_EXECUTION", "NOT_SET"))
        env_run_telegram = os.getenv("RUN_TELEGRAM", "NOT_SET")
        env_bot_token_present = "YES" if os.getenv("TELEGRAM_BOT_TOKEN") else "NO"
        env_chat_id_present = "YES" if os.getenv("TELEGRAM_CHAT_ID") else "NO"
        
        logger.info(
            "[TELEGRAM_INVOKE] timestamp=%s origin_param=%s message_len=%d symbol=%s "
            "caller=%s RUNTIME_ORIGIN=%s AWS_EXECUTION=%s RUN_TELEGRAM=%s "
            "TELEGRAM_BOT_TOKEN=%s TELEGRAM_CHAT_ID=%s",
            timestamp,
            origin if origin else "None",
            len(message),
            symbol or "N/A",
            caller_path,
            env_runtime_origin,
            env_aws_execution,
            env_run_telegram,
            env_bot_token_present,
            env_chat_id_present,
        )
        
        # CENTRAL GATEKEEPER: Only AWS and TEST origins can send Telegram alerts
        # If origin is not provided, use runtime origin as fallback
        if origin is None:
            origin = get_runtime_origin()
        
        origin_upper = origin.upper() if origin else "LOCAL"
        
        # E2E TEST LOGGING: Log normalized origin
        logger.info(f"[E2E_TEST_GATEKEEPER_ORIGIN] origin_upper={origin_upper}")
        
        # ============================================================
        # [TELEGRAM_GATEKEEPER] - All conditions that decide send/skip
        # ============================================================
        # ALERT PATH COMPARISON:
        # - Executed orders: Called from backend-aws (RUNTIME_ORIGIN=AWS) → origin="AWS" → ALLOW ✅
        # - BUY/SELL signals: Called from market-updater (needs RUNTIME_ORIGIN=AWS) → origin="AWS" → ALLOW ✅
        # - Monitoring alerts: Same as signals, must have RUNTIME_ORIGIN=AWS
        # - If origin="LOCAL" or not in whitelist → BLOCK ❌
        gatekeeper_checks = {
            "origin_upper": origin_upper,
            "origin_in_whitelist": origin_upper in ("AWS", "TEST"),
            "self.enabled": self.enabled,
            "bot_token_present": bool(self.bot_token),
            "chat_id_present": bool(self.chat_id),
        }
        gatekeeper_result = "ALLOW" if (
            gatekeeper_checks["origin_in_whitelist"] and 
            gatekeeper_checks["self.enabled"] and
            gatekeeper_checks["bot_token_present"] and
            gatekeeper_checks["chat_id_present"]
        ) else "BLOCK"
        
        logger.info(
            "[TELEGRAM_GATEKEEPER] origin_upper=%s origin_in_whitelist=%s enabled=%s "
            "bot_token_present=%s chat_id_present=%s RESULT=%s",
            gatekeeper_checks["origin_upper"],
            gatekeeper_checks["origin_in_whitelist"],
            gatekeeper_checks["self.enabled"],
            gatekeeper_checks["bot_token_present"],
            gatekeeper_checks["chat_id_present"],
            gatekeeper_result,
        )
        
        # LIVE ALERT LOGGING: Log gatekeeper check for live alerts
        if "LIVE ALERT" in message or "BUY SIGNAL" in message or "SELL SIGNAL" in message:
            allowed = origin_upper in ("AWS", "TEST") and self.enabled
            side = "BUY" if "BUY SIGNAL" in message else ("SELL" if "SELL SIGNAL" in message else "UNKNOWN")
            # Use symbol if available, otherwise extract it safely
            log_symbol = symbol if 'symbol' in locals() else (None)
            if log_symbol is None:
                try:
                    import re
                    symbol_match = re.search(r'([A-Z]+_[A-Z]+|[A-Z]{2,5}(?:\s|:))', message)
                    if symbol_match:
                        potential_symbol = symbol_match.group(1).strip().rstrip(':').rstrip()
                        if '_' in potential_symbol or len(potential_symbol) >= 2:
                            log_symbol = potential_symbol
                except Exception:
                    pass
            logger.info(
                f"[LIVE_ALERT_GATEKEEPER] symbol={log_symbol or 'UNKNOWN'} side={side} origin={origin_upper} "
                f"enabled={self.enabled} bot_token_present={bool(self.bot_token)} "
                f"chat_id_present={bool(self.chat_id)} allowed={allowed}"
            )
        
        # 1) Block truly LOCAL / non-AWS, non-TEST origins
        if origin_upper not in ("AWS", "TEST"):
            # Log what would have been sent
            preview = message[:200] + "..." if len(message) > 200 else message
            logger.warning(
                f"[TELEGRAM_BLOCKED] Skipping Telegram send for non-AWS/non-TEST origin '{origin_upper}'. "
                f"Message would have been: {preview}. "
                f"ROOT CAUSE: Service must have RUNTIME_ORIGIN=AWS env var set. "
                f"Check docker-compose.yml for the service calling this alert."
            )
            # E2E TEST LOGGING: Log block
            logger.info(f"[E2E_TEST_GATEKEEPER_BLOCK] origin_upper={origin_upper}, message_preview={message[:80]}")
            # Note: This block only executes when origin_upper is NOT "AWS" or "TEST",
            # so checking for "TEST" here would be unreachable. Removed unreachable code.
            
            # Still register in dashboard for debugging, but mark as blocked
            try:
                from app.api.routes_monitoring import add_telegram_message
                add_telegram_message(
                    f"[LOCAL DEBUG] {message}", 
                    symbol=symbol, 
                    blocked=True
                )
            except Exception as e:
                logger.debug(f"Could not register LOCAL debug message in dashboard: {e}")
            return False
        
        if not self.enabled:
            logger.debug("Telegram disabled: skipping send_message call")
            # E2E TEST LOGGING: Log disabled state
            logger.warning("[E2E_TEST_CONFIG] Telegram sending disabled by configuration (RUN_TELEGRAM or similar)")
            return False
        
        try:
            # 2) For TEST origin: allow sending, but prefix with [TEST]
            if origin_upper == "TEST":
                # Add [TEST] prefix if not already present
                if not message.startswith("[TEST]"):
                    full_message = f"[TEST] {message}"
                else:
                    full_message = message
                env_label = "[TEST]"
                # Extract symbol and side for logging
                test_symbol = symbol or "UNKNOWN"
                test_side = "UNKNOWN"
                if "BUY SIGNAL" in message or "🟢" in message:
                    test_side = "BUY"
                elif "SELL SIGNAL" in message or "🟥" in message:
                    test_side = "SELL"
                logger.info(
                    f"[TEST_ALERT_LOG] symbol={test_symbol}, side={test_side}, origin=TEST, "
                    f"prefix=[TEST], message_length={len(full_message)}, sending_to_telegram=True"
                )
                logger.info(
                    f"[TEST_ALERT_SENDING] origin=TEST, prefix=[TEST], symbol={test_symbol}, "
                    f"side={test_side}, chat_id={self.chat_id}, url=api.telegram.org/bot.../sendMessage"
                )
            
            # 3) For AWS origin: production alerts with [AWS] prefix
            elif origin_upper == "AWS":
                # Add [AWS] prefix if not already present
                if not message.startswith("[AWS]"):
                    full_message = f"[AWS] {message}"
                else:
                    full_message = message
                env_label = "[AWS]"
            else:
                # Should not reach here due to gatekeeper above, but fallback
                full_message = message
                env_label = "[UNKNOWN]"
            
            # E2E TEST LOGGING: Log before sending to Telegram API
            prefix = "[TEST]" if origin_upper == "TEST" else "[AWS]" if origin_upper == "AWS" else "[UNKNOWN]"
            logger.info(f"[E2E_TEST_SENDING_TELEGRAM] origin_upper={origin_upper}, prefix={prefix}, message_preview={message[:80]}")
            
            # Extract symbol and side for logging
            log_symbol = symbol or "UNKNOWN"
            log_side = "UNKNOWN"
            if "BUY SIGNAL" in message or "🟢" in message:
                log_side = "BUY"
            elif "SELL SIGNAL" in message or "🔴" in message:
                log_side = "SELL"
            
            # Log Telegram send attempt with full context
            logger.info(
                "[TELEGRAM_SEND] type=ALERT symbol=%s side=%s chat_id=%s origin=%s message_len=%d message_preview=%s",
                log_symbol,
                log_side,
                self.chat_id,
                origin_upper,
                len(full_message),
                full_message[:100] if len(full_message) > 100 else full_message,
            )
            
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            # Log URL without token for security
            url_safe = f"https://api.telegram.org/bot***/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": full_message,
                "parse_mode": "HTML"
            }
            
            if reply_markup:
                payload["reply_markup"] = reply_markup
            
            # ============================================================
            # [TELEGRAM_REQUEST] - Request details before sending
            # ============================================================
            payload_keys = list(payload.keys())
            timeout_seconds = 10
            logger.info(
                "[TELEGRAM_REQUEST] url=%s payload_keys=%s timeout=%d message_len=%d",
                url_safe,
                payload_keys,
                timeout_seconds,
                len(full_message),
            )
            
            try:
                response = requests.post(url, json=payload, timeout=timeout_seconds)
                
                # ============================================================
                # [TELEGRAM_RESPONSE] - Response details
                # ============================================================
                status_code = response.status_code
                response_text = response.text[:500] if response.text else ""
                
                if status_code == 200:
                    try:
                        response_data = response.json()
                        message_id = response_data.get("result", {}).get("message_id", "unknown")
                        logger.info(
                            "[TELEGRAM_RESPONSE] status=%d RESULT=SUCCESS message_id=%s",
                            status_code,
                            message_id,
                        )
                    except Exception as e:
                        logger.warning(
                            "[TELEGRAM_RESPONSE] status=%d RESULT=SUCCESS (but failed to parse JSON: %s)",
                            status_code,
                            str(e),
                        )
                else:
                    logger.error(
                        "[TELEGRAM_RESPONSE] status=%d RESULT=FAILURE response_text=%s",
                        status_code,
                        response_text,
                    )
                
                response.raise_for_status()
            except requests.exceptions.HTTPError as e:
                # Log Telegram error with details
                status_code = e.response.status_code if hasattr(e, 'response') and e.response else "unknown"
                error_body = e.response.text[:200] if hasattr(e, 'response') and e.response else str(e)[:200] if str(e) else "unknown"
                
                # Enhanced error logging
                logger.error(
                    "[TELEGRAM_RESPONSE] status=%s RESULT=FAILURE error_type=HTTPError response_text=%s",
                    status_code,
                    error_body,
                )
                logger.error(
                    "[TELEGRAM_ERROR] symbol=%s side=%s status=%s body=%s origin=%s",
                    log_symbol,
                    log_side,
                    status_code,
                    error_body,
                    origin_upper,
                )
                raise
            except Exception as e:
                # Log other Telegram errors
                error_str = str(e)[:200]
                logger.error(
                    "[TELEGRAM_RESPONSE] status=unknown RESULT=FAILURE error_type=Exception error=%s",
                    error_str,
                )
                logger.error(
                    "[TELEGRAM_ERROR] symbol=%s side=%s status=unknown body=%s origin=%s",
                    log_symbol,
                    log_side,
                    error_str,
                    origin_upper,
                )
                raise
            
            # Extract message_id from response for logging (already logged in [TELEGRAM_RESPONSE])
            try:
                response_data = response.json()
                message_id = response_data.get("result", {}).get("message_id", "unknown")
            except Exception:
                message_id = "unknown"
            
            # Enhanced success logging with diagnostics
            logger.info(
                "[TELEGRAM_SUCCESS] type=ALERT symbol=%s side=%s origin=%s message_id=%s chat_id=%s",
                log_symbol,
                log_side,
                origin_upper,
                message_id,
                self.chat_id,
            )
            
            # E2E TEST LOGGING: Log success
            logger.info(f"[E2E_TEST_TELEGRAM_OK] origin_upper={origin_upper}, message_id={message_id}")
            
            # Log TEST alert Telegram success
            if origin_upper == "TEST":
                logger.info(
                    f"[TEST_ALERT_TELEGRAM_OK] origin={origin_upper}, chat_id={self.chat_id}, "
                    f"message_id={message_id}, symbol={symbol or 'UNKNOWN'}"
                )
            
            # Register sent message in dashboard (both AWS and TEST messages)
            try:
                from app.api.routes_monitoring import add_telegram_message
                # Store the message with its prefix for clarity in monitoring
                # TEST messages should show [TEST] prefix, AWS messages show [AWS]
                display_message = full_message  # Keep prefix for monitoring clarity
                add_telegram_message(display_message, symbol=symbol, blocked=False)
                # Additional logging for TEST alerts
                if origin_upper == "TEST":
                    logger.info(
                        f"[TEST_ALERT_MONITORING] Registered in Monitoring: symbol={symbol or 'UNKNOWN'}, "
                        f"blocked=False, prefix=[TEST], message_preview={display_message[:100]}"
                    )
                    # Also log after saving to DB (will be logged in add_telegram_message if we add it there)
            except Exception as e:
                logger.debug(f"Could not register Telegram message in dashboard: {e}")
                # Non-critical, continue
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            # E2E TEST LOGGING: Log error with full traceback
            logger.error(f"[E2E_TEST_TELEGRAM_ERROR] origin_upper={origin_upper}, error={e}", exc_info=True)
            # Log TEST alert Telegram error
            if origin_upper == "TEST":
                error_status = getattr(e, "status_code", None) or getattr(e, "response", {}).get("status_code", "unknown") if hasattr(e, "response") else "unknown"
                error_body = str(e)[:200]
                logger.error(
                    f"[TEST_ALERT_TELEGRAM_ERROR] origin={origin_upper}, status={error_status}, "
                    f"error={error_body}, symbol={symbol or 'UNKNOWN'}"
                )
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
            logger.debug("Telegram disabled: skipping send_message_with_buttons call")
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
        """Send an executed order notification with profit/loss calculations
        
        WORKING PATH (Order Executed Alerts):
        - Called from exchange_sync.py in backend-aws service
        - Uses get_runtime_origin() which returns "AWS" (backend-aws has RUNTIME_ORIGIN=AWS)
        - send_executed_order() → send_message() → origin="AWS" → passes gatekeeper → Telegram ✅
        """
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
        # Executed order alert → send_message() → get_runtime_origin() → Telegram
        # This works because backend-aws service has RUNTIME_ORIGIN=AWS
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
        # CRITICAL: Pass origin="AWS" explicitly to ensure notification is sent
        # SL/TP orders are created from exchange_sync which runs in backend-aws service
        # This ensures the gatekeeper allows the notification to be sent
        from app.core.runtime import get_runtime_origin
        origin = get_runtime_origin()  # Will be "AWS" if RUNTIME_ORIGIN=AWS is set
        return self.send_message(message.strip(), origin=origin)
    
    def send_buy_signal(
        self,
        symbol: str,
        price: float,
        reason: str,
        strategy: Optional[str] = None,
        strategy_type: Optional[str] = None,
        risk_approach: Optional[str] = None,
        price_variation: Optional[str] = None,
        previous_price: Optional[float] = None,
        source: str = "LIVE ALERT",  # "LIVE ALERT" or "TEST"
        throttle_status: Optional[str] = None,
        throttle_reason: Optional[str] = None,
        origin: Optional[str] = None,  # "AWS" or "LOCAL"
    ):
        """Send a buy signal alert
        
        NOTE: Verification of alert_enabled and buy_alert_enabled is done by SignalMonitorService
        before calling this method. This method should NEVER block alerts - it only sends them.
        
        SIGNAL ALERT PATH (BUY/SELL signals):
        - Called from signal_monitor.py in market-updater service
        - If origin=None, uses get_runtime_origin() which must return "AWS" for alerts to send
        - send_buy_signal() → send_message(origin=...) → gatekeeper checks origin → Telegram
        - FIX: market-updater service must have RUNTIME_ORIGIN=AWS in docker-compose.yml
        """
        logger.info(f"🔍 send_buy_signal called for {symbol} - Sending alert (verification already done by SignalMonitorService)")
        # Log TEST alert signal entry
        logger.info(
            f"[TEST_ALERT_SIGNAL_ENTRY] send_buy_signal called: symbol={symbol}, origin={origin}, "
            f"source={source}, price={price:.4f}"
        )
        resolved_strategy = strategy_type
        if not resolved_strategy:
            if strategy and strategy.lower() not in {"conservative", "aggressive"}:
                resolved_strategy = strategy
            else:
                resolved_strategy = "Swing"

        resolved_approach = risk_approach
        if not resolved_approach:
            if strategy and strategy.lower() in {"conservative", "aggressive"}:
                resolved_approach = strategy.title()
            else:
                resolved_approach = "Conservative"

        strategy_line = f"\n🎯 Strategy: <b>{resolved_strategy}</b>"
        approach_line = f"\n⚖️ Approach: <b>{resolved_approach}</b>"
        
        timestamp = self._format_timestamp()
        
        # Always show price change percentage from last alert
        price_change_text = ""
        if price_variation:
            # Use provided price_variation if available
            price_change_text = f"\n📊 Cambio desde última alerta: {price_variation}"
        elif previous_price is not None and previous_price > 0:
            # Calculate price change if previous_price is provided
            try:
                change_pct = ((price - previous_price) / previous_price) * 100
                direction = "↑" if change_pct > 0 else "↓" if change_pct < 0 else "→"
                price_change_text = f"\n📊 Cambio desde última alerta: {direction} {abs(change_pct):.2f}%"
            except (ZeroDivisionError, ValueError):
                price_change_text = "\n📊 Cambio desde última alerta: N/A"
        else:
            # First alert for this symbol/side
            price_change_text = "\n📊 Cambio desde última alerta: Primera alerta"
        
        price_line = f"💵 Price: ${price:,.4f}"
        
        # Add source indicator
        source_text = ""
        if source == "TEST":
            source_text = "\n🧪 <b>TEST MODE</b> - Simulated alert"
        elif source == "LIVE ALERT":
            source_text = "\n🔴 <b>LIVE ALERT</b> - Real-time signal"

        message = f"""
🟢 <b>BUY SIGNAL DETECTED</b>{source_text}

📈 Symbol: <b>{symbol}</b>
{price_line}{price_change_text}
✅ Reason: {reason}{strategy_line}{approach_line}
📅 Time: {timestamp}
"""
        # Log TEST alert signal if origin is TEST
        if origin == "TEST":
            logger.info(
                f"[TEST_ALERT_SIGNAL] BUY signal: symbol={symbol}, side=BUY, origin=TEST, "
                f"price={price:.4f}, reason={reason[:100]}"
            )
        
        # Default to AWS if origin not provided (for backward compatibility)
        if origin is None:
            origin = get_runtime_origin()
        
        result = self.send_message(message.strip(), origin=origin)
        
        # Register sent message
        if result:
            try:
                from app.api.routes_monitoring import add_telegram_message
                # Include price change in stored message
                price_change_display = price_change_text.replace("\n📊 Cambio desde última alerta: ", "") if price_change_text else "N/A"
                sent_message = f"✅ BUY SIGNAL: {symbol} @ ${price:,.4f} ({price_change_display}) - {reason}"
                add_telegram_message(
                    sent_message,
                    symbol=symbol,
                    blocked=False,
                    throttle_status=throttle_status or "SENT",
                    throttle_reason=throttle_reason or reason,
                )
            except Exception:
                pass  # Non-critical, continue
        
        return result
    
    def send_sell_signal(
        self,
        symbol: str,
        price: float,
        reason: str,
        strategy: Optional[str] = None,
        strategy_type: Optional[str] = None,
        risk_approach: Optional[str] = None,
        price_variation: Optional[str] = None,
        previous_price: Optional[float] = None,
        source: str = "LIVE ALERT",  # "LIVE ALERT" or "TEST"
        throttle_status: Optional[str] = None,
        throttle_reason: Optional[str] = None,
        origin: Optional[str] = None,  # "AWS" or "LOCAL"
    ):
        """Send a sell signal alert
        
        NOTE: Verification of alert_enabled and sell_alert_enabled is done by SignalMonitorService
        before calling this method. This method should NEVER block alerts - it only sends them.
        
        SIGNAL ALERT PATH (BUY/SELL signals):
        - Called from signal_monitor.py in market-updater service
        - If origin=None, uses get_runtime_origin() which must return "AWS" for alerts to send
        - send_sell_signal() → send_message(origin=...) → gatekeeper checks origin → Telegram
        - FIX: market-updater service must have RUNTIME_ORIGIN=AWS in docker-compose.yml
        """
        logger.info(f"🔍 send_sell_signal called for {symbol} - Sending alert (verification already done by SignalMonitorService)")
        # Log TEST alert signal entry
        logger.info(
            f"[TEST_ALERT_SIGNAL_ENTRY] send_sell_signal called: symbol={symbol}, origin={origin}, "
            f"source={source}, price={price:.4f}"
        )
        resolved_strategy = strategy_type
        if not resolved_strategy:
            if strategy and strategy.lower() not in {"conservative", "aggressive"}:
                resolved_strategy = strategy
            else:
                resolved_strategy = "Swing"

        resolved_approach = risk_approach
        if not resolved_approach:
            if strategy and strategy.lower() in {"conservative", "aggressive"}:
                resolved_approach = strategy.title()
            else:
                resolved_approach = "Conservative"

        strategy_line = f"\n🎯 Strategy: <b>{resolved_strategy}</b>"
        approach_line = f"\n⚖️ Approach: <b>{resolved_approach}</b>"
        
        timestamp = self._format_timestamp()
        
        # Always show price change percentage from last alert
        price_change_text = ""
        if price_variation:
            # Use provided price_variation if available
            price_change_text = f"\n📊 Cambio desde última alerta: {price_variation}"
        elif previous_price is not None and previous_price > 0:
            # Calculate price change if previous_price is provided
            try:
                change_pct = ((price - previous_price) / previous_price) * 100
                direction = "↑" if change_pct > 0 else "↓" if change_pct < 0 else "→"
                price_change_text = f"\n📊 Cambio desde última alerta: {direction} {abs(change_pct):.2f}%"
            except (ZeroDivisionError, ValueError):
                price_change_text = "\n📊 Cambio desde última alerta: N/A"
        else:
            # First alert for this symbol/side
            price_change_text = "\n📊 Cambio desde última alerta: Primera alerta"
        
        price_line = f"💵 Price: ${price:,.4f}"
        
        # Add source indicator
        source_text = ""
        if source == "TEST":
            source_text = "\n🧪 <b>TEST MODE</b> - Simulated alert"
        elif source == "LIVE ALERT":
            source_text = "\n🔴 <b>LIVE ALERT</b> - Real-time signal"

        message = f"""
🔴 <b>SELL SIGNAL DETECTED</b>{source_text}

📈 Symbol: <b>{symbol}</b>
{price_line}{price_change_text}
✅ Reason: {reason}{strategy_line}{approach_line}
📅 Time: {timestamp}
"""
        # Default to AWS if origin not provided (for backward compatibility)
        if origin is None:
            origin = get_runtime_origin()
        
        result = self.send_message(message.strip(), origin=origin)
        
        # Register sent message
        if result:
            try:
                from app.api.routes_monitoring import add_telegram_message
                # Include price change in stored message
                price_change_display = price_change_text.replace("\n📊 Cambio desde última alerta: ", "") if price_change_text else "N/A"
                sent_message = f"🔴 SELL SIGNAL: {symbol} @ ${price:,.4f} ({price_change_display}) - {reason}"
                add_telegram_message(
                    sent_message,
                    symbol=symbol,
                    blocked=False,
                    throttle_status=throttle_status or "SENT",
                    throttle_reason=throttle_reason or reason,
                )
            except Exception:
                pass
        
        return result
    
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
        """
        Send a formatted trading signal message to Telegram.
        
        Refactored to use send_message() for consistent environment prefix handling.
        """
        try:
            message = self.format_signal_message(
                signal_type, coin, last_price, buy_target, sell_target,
                res_up, stop_loss, rsi, method, row_idx, extra
            )
            
            # Convert Markdown to HTML for consistency with send_message()
            # send_message() uses HTML parse_mode, so we'll send as plain text
            # and let send_message() add the environment prefix
            # Note: Markdown formatting will be lost, but environment prefix is more important
            return self.send_message(message)
            
        except Exception as e:
            logger.error(f"[TELEGRAM][ERROR] Failed to send signal alert: {e}")
            return False

    def debug_test_alert(self, alert_type: str, symbol: Optional[str] = None, origin: Optional[str] = None) -> bool:
        """
        Debug helper function to test Telegram sending through all alert paths.
        
        This function sends a test message with explicit alert type, symbol, and origin
        to help diagnose which execution contexts successfully send to Telegram.
        
        Args:
            alert_type: Type of alert being tested (e.g., "BUY", "SELL", "ORDER", "MONITORING", "DAILY_REPORT")
            symbol: Optional symbol for the alert
            origin: Optional origin override. If None, uses get_runtime_origin()
        
        Returns:
            True if message sent successfully, False otherwise
        """
        timestamp = datetime.now().isoformat()
        test_message = (
            f"[AWS TEST] AlertType={alert_type} Symbol={symbol or 'N/A'} "
            f"Origin={origin or get_runtime_origin()} Timestamp={timestamp}"
        )
        
        logger.info(
            "[DEBUG_TEST_ALERT] alert_type=%s symbol=%s origin_param=%s message=%s",
            alert_type,
            symbol,
            origin,
            test_message,
        )
        
        return self.send_message(test_message, origin=origin)

# Global instance
telegram_notifier = TelegramNotifier()

