import os
import logging
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import pytz
from sqlalchemy.orm import Session
from app.services.telegram_notifier import telegram_notifier
from app.services.brokers.crypto_com_trade import trade_client
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.database import SessionLocal
import json

logger = logging.getLogger(__name__)

# Bali timezone (UTC+8)
BALI_TZ = pytz.timezone('Asia/Makassar')  # Makassar is the same timezone as Bali (WITA)

class DailySummaryService:
    """Daily summary service for portfolio and trading activity"""
    
    def __init__(self):
        self.telegram = telegram_notifier
        self.trade_client = trade_client
    
    def get_portfolio_summary(self) -> Dict:
        """Get current portfolio summary"""
        errors = []
        balance_data = {}
        open_orders = []
        recent_orders = []
        
        try:
            # Get account balance
            try:
                balance_response = self.trade_client.get_account_summary()
                if balance_response:
                    # Handle different response formats
                    if 'accounts' in balance_response:
                        # Convert accounts format to balance_data format
                        accounts = balance_response.get('accounts', [])
                        balance_data = {}
                        for acc in accounts:
                            currency = acc.get('currency', '')
                            balance_data[currency] = {
                                'available': acc.get('available', '0'),
                                'balance': acc.get('balance', '0')
                            }
                    elif 'data' in balance_response:
                        balance_data = balance_response.get('data', {})
                    elif 'result' in balance_response and 'data' in balance_response['result']:
                        balance_data = balance_response['result'].get('data', {})
                    else:
                        balance_data = balance_response
                else:
                    errors.append("get_account_summary returned None")
            except Exception as e:
                error_msg = f"Error getting account summary: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
            
            # Get open orders
            try:
                open_orders_response = self.trade_client.get_open_orders()
                if open_orders_response:
                    open_orders = open_orders_response.get('data', [])
                else:
                    errors.append("get_open_orders returned None")
            except Exception as e:
                error_msg = f"Error getting open orders: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
            
            # Get executed orders from last 24 hours
            try:
                executed_orders_response = self.trade_client.get_order_history(page_size=100)
                if executed_orders_response:
                    executed_orders = executed_orders_response.get('data', [])
                    
                    # Filter orders from last 24 hours
                    yesterday = datetime.now() - timedelta(days=1)
                    for order in executed_orders:
                        try:
                            # Handle both timestamp formats (seconds or milliseconds)
                            create_time = order.get('create_time', 0)
                            if create_time > 1e10:  # milliseconds
                                create_time = create_time / 1000
                            order_time = datetime.fromtimestamp(create_time)
                            if order_time >= yesterday:
                                recent_orders.append(order)
                        except (ValueError, TypeError, OSError) as e:
                            logger.warning(f"Error parsing order time: {e}, order: {order.get('order_id', 'unknown')}")
                            # Include order anyway if we can't parse time
                            recent_orders.append(order)
                else:
                    errors.append("get_order_history returned None")
            except Exception as e:
                error_msg = f"Error getting order history: {str(e)}"
                logger.error(error_msg, exc_info=True)
                errors.append(error_msg)
            
            # Return data even if some calls failed, but include errors
            result = {
                'balance': balance_data,
                'open_orders': open_orders,
                'recent_orders': recent_orders,
                'total_open_orders': len(open_orders),
                'total_executed_24h': len(recent_orders),
                'errors': errors
            }
            
            # If all calls failed, return None to trigger error message
            if errors and not balance_data and not open_orders and not recent_orders:
                logger.error(f"All portfolio summary calls failed: {errors}")
                return None
            
            return result
            
        except Exception as e:
            error_msg = f"Unexpected error getting portfolio summary: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return None
    
    def format_balance_summary(self, balance_data: Dict) -> str:
        """Format balance information"""
        if not balance_data:
            return "❌ No se pudo obtener el balance"
        
        summary = "💰 **Balance de Cuenta**\n"
        
        # Get USD/USDT balance
        usd_balance = 0
        crypto_balances = []
        
        # Handle different data structures
        if isinstance(balance_data, dict):
            for currency, data in balance_data.items():
                if isinstance(data, dict):
                    available = float(data.get('available', data.get('balance', 0)))
                elif isinstance(data, (int, float, str)):
                    available = float(data)
                else:
                    available = 0
                
                # Treat USD and USDT as the same
                if currency in ['USD', 'USDT']:
                    usd_balance += available
                elif available > 0:
                    crypto_balances.append(f"• {currency}: {available:.6f}")
        
        summary += f"💵 USD/USDT: ${usd_balance:,.2f}\n"
        
        if crypto_balances:
            summary += "\n📊 **Criptomonedas:**\n"
            summary += "\n".join(crypto_balances[:5])  # Show top 5
            if len(crypto_balances) > 5:
                summary += f"\n... y {len(crypto_balances) - 5} más"
        
        return summary
    
    def format_orders_summary(self, open_orders: List, recent_orders: List) -> str:
        """Format orders summary"""
        summary = f"📋 **Órdenes Activas:** {len(open_orders)}\n"
        
        if open_orders:
            summary += "\n🔄 **Órdenes Abiertas:**\n"
            for order in open_orders[:3]:  # Show first 3
                symbol = order.get('instrument_name', 'N/A')
                side = order.get('side', 'N/A')
                qty = float(order.get('quantity', 0))
                price = float(order.get('limit_price', 0))
                summary += f"• {symbol} {side} {qty:.6f} @ ${price:.4f}\n"
            
            if len(open_orders) > 3:
                summary += f"... y {len(open_orders) - 3} más\n"
        
        summary += f"\n📈 **Ejecutadas (24h):** {len(recent_orders)}\n"
        
        if recent_orders:
            summary += "\n✅ **Últimas Ejecuciones:**\n"
            for order in recent_orders[:3]:  # Show first 3
                symbol = order.get('instrument_name', 'N/A')
                side = order.get('side', 'N/A')
                qty = float(order.get('quantity', 0))
                price = float(order.get('avg_price', order.get('limit_price', 0)))
                status = order.get('status', 'N/A')
                summary += f"• {symbol} {side} {qty:.6f} @ ${price:.4f} ({status})\n"
            
            if len(recent_orders) > 3:
                summary += f"... y {len(recent_orders) - 3} más\n"
        
        return summary
    
    def send_daily_summary(self):
        """Send daily summary to Telegram"""
        try:
            logger.info("Generating daily summary...")
            
            # Get portfolio data
            portfolio_data = self.get_portfolio_summary()
            
            if portfolio_data is None:
                error_msg = "❌ No se pudo generar el resumen diario"
                logger.error(error_msg)
                self.telegram.send_message(error_msg)
                return
            
            # Check if there were errors but we still have some data
            errors = portfolio_data.get('errors', [])
            if errors:
                logger.warning(f"Daily summary generated with some errors: {errors}")
            
            # Create summary message
            message = f"🌅 **Resumen Diario - {datetime.now().strftime('%d/%m/%Y')}**\n\n"
            
            # Add balance summary
            message += self.format_balance_summary(portfolio_data.get('balance', {}))
            message += "\n"
            
            # Add orders summary
            message += self.format_orders_summary(
                portfolio_data.get('open_orders', []),
                portfolio_data.get('recent_orders', [])
            )
            
            # Add footer
            message += f"\n⏰ Generado: {datetime.now().strftime('%H:%M:%S')}"
            message += "\n🤖 Trading Bot Automático"
            
            # Add error warnings if any
            if errors:
                message += f"\n\n⚠️ Advertencias: {len(errors)} error(es) durante la obtención de datos"
                for error in errors[:3]:  # Show first 3 errors
                    message += f"\n  • {error[:100]}"  # Truncate long errors
            
            # Send message
            success = self.telegram.send_message(message)
            
            if success:
                logger.info("Daily summary sent successfully")
            else:
                logger.error("Failed to send daily summary")
                
        except Exception as e:
            logger.error(f"Error sending daily summary: {e}")
            self.telegram.send_message(f"❌ Error en resumen diario: {str(e)}")

    def send_sell_orders_report(self, db: Session = None):
        """
        Send a report of all executed SELL orders from the last 24 hours
        with profit/loss per order and total P&L
        """
        try:
            # Use provided session or create new one
            if db is None:
                db = SessionLocal()
                should_close = True
            else:
                should_close = False
            
            try:
                # Calculate time range (last 24 hours) - use UTC for database queries
                now_utc = datetime.now(timezone.utc)
                yesterday_utc = now_utc - timedelta(hours=24)
                
                # Get Bali time for display
                now_bali = now_utc.astimezone(BALI_TZ)
                
                # Query executed SELL orders from last 24 hours
                sell_orders = db.query(ExchangeOrder).filter(
                    ExchangeOrder.side == OrderSideEnum.SELL,
                    ExchangeOrder.status == OrderStatusEnum.FILLED,
                    ExchangeOrder.exchange_update_time >= yesterday_utc
                ).order_by(ExchangeOrder.exchange_update_time.desc()).all()
                
                logger.info(f"Found {len(sell_orders)} executed SELL orders in last 24 hours")
                
                if not sell_orders:
                    message = f"📊 **Reporte de Ventas - {now_bali.strftime('%d/%m/%Y %H:%M')} (Bali)**\n\n"
                    message += "ℹ️ No se ejecutaron órdenes de venta en las últimas 24 horas."
                    self.telegram.send_message(message)
                    return
                
                # Build report message
                message = f"📊 **Reporte de Ventas - {now_bali.strftime('%d/%m/%Y %H:%M')} (Bali)**\n\n"
                message += f"⏰ Período: Últimas 24 horas\n"
                message += f"📈 Total de órdenes: {len(sell_orders)}\n\n"
                message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                total_profit_loss = 0.0
                total_profit_loss_pct = 0.0
                orders_with_pnl = 0
                
                # Process each order
                for order in sell_orders:
                    symbol = order.symbol
                    sell_price = float(order.avg_price) if order.avg_price else float(order.price) if order.price else 0.0
                    quantity = float(order.quantity) if order.quantity else 0.0
                    order_id = order.exchange_order_id
                    order_time = order.exchange_update_time.strftime('%d/%m/%Y %H:%M:%S') if order.exchange_update_time else 'N/A'
                    order_role = order.order_role or 'SELL'
                    
                    # Try to find entry price from parent order or related BUY order
                    entry_price = None
                    if order.parent_order_id:
                        # Try to find parent BUY order
                        parent_order = db.query(ExchangeOrder).filter(
                            ExchangeOrder.exchange_order_id == order.parent_order_id
                        ).first()
                        if parent_order and parent_order.side == OrderSideEnum.BUY:
                            entry_price = float(parent_order.avg_price) if parent_order.avg_price else float(parent_order.price) if parent_order.price else None
                    
                    # If no parent order, try to find the most recent BUY order for this symbol before this SELL
                    if entry_price is None:
                        buy_order = db.query(ExchangeOrder).filter(
                            ExchangeOrder.symbol == symbol,
                            ExchangeOrder.side == OrderSideEnum.BUY,
                            ExchangeOrder.status == OrderStatusEnum.FILLED,
                            ExchangeOrder.exchange_update_time < order.exchange_update_time
                        ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
                        
                        if buy_order:
                            entry_price = float(buy_order.avg_price) if buy_order.avg_price else float(buy_order.price) if buy_order.price else None
                    
                    # Calculate P&L if entry price is available
                    pnl_info = ""
                    if entry_price and entry_price > 0:
                        profit_loss = (sell_price - entry_price) * quantity
                        profit_loss_pct = ((sell_price - entry_price) / entry_price) * 100
                        total_profit_loss += profit_loss
                        total_profit_loss_pct += profit_loss_pct
                        orders_with_pnl += 1
                        
                        pnl_emoji = "💰" if profit_loss >= 0 else "💸"
                        pnl_sign = "+" if profit_loss >= 0 else ""
                        pnl_info = f"\n   {pnl_emoji} P&L: {pnl_sign}${profit_loss:,.2f} ({pnl_sign}{profit_loss_pct:,.2f}%)"
                        pnl_info += f"\n   💵 Entrada: ${entry_price:,.4f}"
                    
                    # Format order line
                    role_emoji = "🚀" if order_role == "TAKE_PROFIT" else "🛑" if order_role == "STOP_LOSS" else "🔴"
                    role_text = "TP" if order_role == "TAKE_PROFIT" else "SL" if order_role == "STOP_LOSS" else "SELL"
                    
                    message += f"• <b>{symbol}</b> {role_emoji} {role_text}\n"
                    message += f"   💵 Precio: ${sell_price:,.4f}\n"
                    message += f"   📦 Cantidad: {quantity:,.6f}\n"
                    message += f"   💰 Total: ${(sell_price * quantity):,.2f}\n"
                    if pnl_info:
                        message += pnl_info
                    message += f"\n   🆔 ID: {order_id}\n"
                    message += f"   ⏰ {order_time}\n\n"
                
                # Add summary
                message += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                message += f"📊 <b>RESUMEN</b>\n"
                message += f"   Total órdenes: {len(sell_orders)}\n"
                
                if orders_with_pnl > 0:
                    avg_pnl_pct = total_profit_loss_pct / orders_with_pnl
                    total_emoji = "💰" if total_profit_loss >= 0 else "💸"
                    total_sign = "+" if total_profit_loss >= 0 else ""
                    message += f"   {total_emoji} P&L Total: {total_sign}${total_profit_loss:,.2f}\n"
                    message += f"   📈 P&L Promedio: {total_sign}{avg_pnl_pct:,.2f}%\n"
                    message += f"   ✅ Órdenes con P&L: {orders_with_pnl}/{len(sell_orders)}\n"
                else:
                    message += f"   ⚠️ No se pudo calcular P&L (falta precio de entrada)\n"
                
                message += f"\n⏰ Generado: {now_bali.strftime('%H:%M:%S')} (Bali)\n"
                message += "🤖 Trading Bot Automático"
                
                # ============================================================
                # WORKING TELEGRAM PATH (CANONICAL) - Daily Sales Report
                # ============================================================
                # Trigger: Scheduled task (scheduler.py) → send_sell_orders_report()
                # Message Builder: Builds message with sales data
                # Telegram Sender: self.telegram.send_message(message)
                #   → telegram_notifier.send_message() [telegram_notifier.py:151]
                #   → Uses: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID env vars
                #   → Origin: Defaults to get_runtime_origin() → "AWS" in AWS
                #   → API Call: requests.post("https://api.telegram.org/bot{token}/sendMessage")
                #   → Result: Message sent to Telegram chat
                # ============================================================
                # ALL other alerts (signals, monitoring, watchlist, CPI) should
                # use the SAME path: telegram_notifier.send_message()
                # ============================================================
                success = self.telegram.send_message(message)
                
                if success:
                    logger.info(f"Sell orders report sent successfully: {len(sell_orders)} orders, P&L: ${total_profit_loss:,.2f}")
                else:
                    logger.error("Failed to send sell orders report")
                    
            finally:
                if should_close:
                    db.close()
                    
        except Exception as e:
            logger.error(f"Error sending sell orders report: {e}", exc_info=True)
            self.telegram.send_message(f"❌ Error en reporte de ventas: {str(e)}")

# Global instance
daily_summary_service = DailySummaryService()
