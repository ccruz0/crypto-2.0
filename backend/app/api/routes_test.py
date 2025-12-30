from fastapi import APIRouter, HTTPException, Body, Depends
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from app.database import get_db
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketPrice, MarketData as MarketDataModel
from app.services.signal_monitor import signal_monitor_service
from app.services.telegram_notifier import telegram_notifier
from app.services.sl_tp_checker import sl_tp_checker_service
import requests
import logging
import asyncio
import time
import os

logger = logging.getLogger(__name__)
router = APIRouter()

# Track last test alert time per symbol to prevent duplicates
# Format: {symbol: timestamp}
_test_alert_locks: Dict[str, float] = {}
_TEST_ALERT_COOLDOWN_SECONDS = 30  # Prevent duplicate test alerts within 30 seconds

@router.get("/test-dashboard")
def get_test_dashboard():
    """Get test dashboard data without authentication"""
    try:
        # Get real crypto prices from Crypto.com
        url = "https://api.crypto.com/exchange/v1/public/get-tickers"
        response = http_get(url, timeout=10, calling_module="routes_test")
        response.raise_for_status()
        result = response.json()
        
        # Create test portfolio data with real prices
        portfolio = []
        if "result" in result and "data" in result["result"]:
            for ticker in result["result"]["data"][:10]:  # Get first 10 cryptos
                instrument_name = ticker.get("i", "")
                last_price = float(ticker.get("a", 0))
                
                if "_USDT" in instrument_name:
                    crypto = instrument_name.replace("_USDT", "")
                    portfolio.append({
                        "symbol": crypto,
                        "quantity": 1.0,
                        "current_price": last_price,
                        "total_value": last_price,
                        "pnl": last_price * 0.05,  # 5% profit
                        "pnl_percentage": 5.0,
                        "signals": {
                            "buy": True,
                            "sell": False
                        }
                    })
        
        return {
            "portfolio": portfolio,
            "balance": {
                "total_usd": 50000.0,
                "available_usd": 25000.0
            },
            "open_orders": [
                {
                    "id": "ORD-001",
                    "symbol": "BTC",
                    "side": "BUY",
                    "quantity": 0.1,
                    "price": 65000.0,
                    "status": "OPEN"
                }
            ],
            "recent_orders": [
                {
                    "id": "ORD-002", 
                    "symbol": "ETH",
                    "side": "SELL",
                    "quantity": 1.0,
                    "price": 3600.0,
                    "status": "FILLED"
                }
            ]
        }
    except Exception as e:
        logger.error(f"Error getting test dashboard: {e}")
        # Return fallback data
        return {
            "portfolio": [
                {
                    "symbol": "BTC",
                    "quantity": 0.5,
                    "current_price": 67000.0,
                    "total_value": 33500.0,
                    "pnl": 1000.0,
                    "pnl_percentage": 3.08,
                    "signals": {"buy": True, "sell": False}
                },
                {
                    "symbol": "ETH", 
                    "quantity": 2.0,
                    "current_price": 3600.0,
                    "total_value": 7200.0,
                    "pnl": 200.0,
                    "pnl_percentage": 2.86,
                    "signals": {"buy": False, "sell": True}
                }
            ],
            "balance": {
                "total_usd": 50000.0,
                "available_usd": 25000.0
            },
            "open_orders": [],
            "recent_orders": []
        }

@router.post("/test/check-sl-tp")
def check_sl_tp_now(
    db: Session = Depends(get_db)
):
    """
    Execute SL/TP check manually (for testing)
    Checks all open positions for missing SL/TP orders and sends Telegram reminder
    """
    try:
        from app.services.sl_tp_checker import sl_tp_checker_service
        
        logger.info("🧪 Manually executing SL/TP check...")
        
        # Check positions
        check_result = sl_tp_checker_service.check_positions_for_sl_tp(db)
        positions_missing = check_result.get('positions_missing_sl_tp', [])
        
        logger.info(f"Check result: total_positions={check_result.get('total_positions', 0)}, positions_missing_sl_tp={len(positions_missing)}")
        
        # Send reminder if there are positions missing SL/TP
        reminder_sent = False
        if positions_missing:
            logger.info(f"Sending reminder for {len(positions_missing)} positions missing SL/TP...")
            reminder_sent = sl_tp_checker_service.send_sl_tp_reminder(db)
        
        return {
            "ok": True,
            "message": "SL/TP check completed",
            "total_positions": check_result.get('total_positions', 0),
            "positions_missing_sl_tp": len(positions_missing),
            "reminder_sent": reminder_sent,
            "positions": [
                {
                    "symbol": pos.get('symbol'),
                    "currency": pos.get('currency'),
                    "balance": pos.get('balance'),
                    "has_sl": pos.get('has_sl'),
                    "has_tp": pos.get('has_tp'),
                    "sl_price": pos.get('sl_price'),
                    "tp_price": pos.get('tp_price')
                }
                for pos in positions_missing
            ]
        }
    except Exception as e:
        logger.error(f"Error executing SL/TP check: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error executing SL/TP check: {str(e)}")


@router.post("/test/simulate-alert")
async def simulate_alert(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """
    Simulate a BUY or SELL alert for testing purposes
    Body: {
        "symbol": "ETH_USDT",
        "signal_type": "BUY" or "SELL",
        "force_order": true/false (optional, force order creation even if alert_enabled is false)
    }
    """
    try:
        symbol = payload.get("symbol", "").upper()
        signal_type = payload.get("signal_type", "BUY").upper()
        force_order = payload.get("force_order", False)
        
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")
        
        if signal_type not in ["BUY", "SELL"]:
            raise HTTPException(status_code=400, detail="signal_type must be 'BUY' or 'SELL'")
        
        # Get watchlist item
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol
        ).first()
        
        if not watchlist_item:
            # Create a temporary watchlist item for testing
            # Use trade_amount_usd from payload if provided, otherwise raise error
            trade_amount_usd = payload.get("trade_amount_usd")
            if not trade_amount_usd or trade_amount_usd <= 0:
                error_message = f"⚠️ CONFIGURACIÓN REQUERIDA\n\nEl campo 'Amount USD' no está configurado para {symbol}.\n\nPor favor configura el campo 'Amount USD' en la Watchlist del Dashboard antes de crear órdenes."
                logger.warning(f"Cannot create order for {symbol}: trade_amount_usd not configured")
                
                # Send error notification to Telegram
                try:
                    telegram_notifier.send_message(
                        f"❌ <b>ORDER CREATION FAILED</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"❌ Error: {error_message}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Telegram error notification: {e}")
                
                raise HTTPException(
                    status_code=400,
                    detail=error_message
                )
            
            watchlist_item = WatchlistItem(
                symbol=symbol,
                exchange="CRYPTO_COM",
                alert_enabled=force_order or True,
                trade_amount_usd=trade_amount_usd,  # Use provided amount from payload
                trade_on_margin=False
            )
            db.add(watchlist_item)
            db.commit()
        else:
            # Watchlist item exists - prioritize payload value if provided, otherwise use watchlist value
            # But if neither has value, raise error
            trade_amount_usd_from_payload = payload.get("trade_amount_usd")
            trade_enabled_from_payload = payload.get("trade_enabled")
            
            # CRITICAL: Refresh watchlist_item from database to get latest values
            # This ensures we have the most up-to-date trade_enabled value
            db.refresh(watchlist_item)
            logger.info(f"Refreshed watchlist_item for {symbol}: trade_enabled={watchlist_item.trade_enabled}, trade_amount_usd={watchlist_item.trade_amount_usd}")
            
            # Priority for trade_enabled: 1) Payload value (from dashboard), 2) Watchlist value (from database)
            if trade_enabled_from_payload is not None:
                # Use payload value (from dashboard) - update watchlist item to match
                watchlist_item.trade_enabled = bool(trade_enabled_from_payload)
                logger.info(f"Using trade_enabled={watchlist_item.trade_enabled} from payload (dashboard) for {symbol}, updated watchlist item")
            else:
                # Use watchlist value (from database)
                logger.info(f"Using trade_enabled={watchlist_item.trade_enabled} from watchlist item (database) for {symbol}")
            
            # Priority for trade_amount_usd: 1) Payload value (from dashboard), 2) Watchlist value (from database)
            if trade_amount_usd_from_payload and trade_amount_usd_from_payload > 0:
                # Use payload value (from dashboard) - update watchlist item to match
                watchlist_item.trade_amount_usd = trade_amount_usd_from_payload
                logger.info(f"Using trade_amount_usd={trade_amount_usd_from_payload} from payload (dashboard) for {symbol}, updated watchlist item")
            elif watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0:
                # Use watchlist value (from database) - no update needed
                logger.info(f"Using trade_amount_usd={watchlist_item.trade_amount_usd} from watchlist item (database) for {symbol}")
            else:
                # No trade_amount_usd in watchlist or payload - raise error
                error_message = f"⚠️ CONFIGURACIÓN REQUERIDA\n\nEl campo 'Amount USD' no está configurado para {symbol}.\n\nPor favor configura el campo 'Amount USD' en la Watchlist del Dashboard antes de crear órdenes."
                logger.warning(f"Cannot create order for {symbol}: trade_amount_usd not configured in watchlist or payload")
                
                # Send error notification to Telegram
                try:
                    telegram_notifier.send_message(
                        f"❌ <b>ORDER CREATION FAILED</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"❌ Error: {error_message}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Telegram error notification: {e}")
                
                raise HTTPException(
                    status_code=400,
                    detail=error_message
                )
            
            # Commit any updates to trade_enabled or trade_amount_usd
            if trade_enabled_from_payload is not None or (trade_amount_usd_from_payload and trade_amount_usd_from_payload > 0):
                db.commit()
                logger.info(f"Committed watchlist updates for {symbol}: trade_enabled={watchlist_item.trade_enabled}, trade_amount_usd={watchlist_item.trade_amount_usd}")
        
        # Check for cooldown to prevent duplicate test alerts (before fetching price)
        current_time = time.time()
        last_alert_time = _test_alert_locks.get(symbol, 0)
        time_since_last = current_time - last_alert_time
        
        if time_since_last < _TEST_ALERT_COOLDOWN_SECONDS:
            remaining = _TEST_ALERT_COOLDOWN_SECONDS - time_since_last
            logger.warning(f"⚠️ Test alert for {symbol} blocked: cooldown active ({remaining:.1f}s remaining)")
            return {
                "ok": True,
                "message": f"Test alert blocked: cooldown active ({remaining:.1f}s remaining)",
                "symbol": symbol,
                "signal_type": signal_type,
                "price": 0,
                "alert_sent": False,
                "order_created": False,
                "cooldown_active": True,
                "cooldown_remaining_seconds": remaining,
                "note": f"Please wait {remaining:.1f} seconds before sending another test alert for {symbol}"
            }
        
        # Update lock with current time
        _test_alert_locks[symbol] = current_time
        logger.info(f"✅ Test alert lock acquired for {symbol} (cooldown: {_TEST_ALERT_COOLDOWN_SECONDS}s)")
        
        # Get current price
        try:
            from price_fetcher import get_price_with_fallback
            result = get_price_with_fallback(symbol, "15m")
            current_price = result.get('price', 0)
            if not current_price:
                raise HTTPException(status_code=400, detail=f"Could not fetch price for {symbol}")
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
            raise HTTPException(status_code=400, detail=f"Error fetching price: {str(e)}")
        
        # Simulate the signal by directly calling the monitor service
        # We'll manually trigger the signal handling logic
        if signal_type == "BUY":
            logger.info(f"🧪 SIMULATING BUY signal for {symbol}")
            
            # Send Telegram alert
            try:
                risk_display = (watchlist_item.sl_tp_mode or "conservative").title() if watchlist_item else "Conservative"
                telegram_notifier.send_buy_signal(
                    symbol=symbol,
                    price=current_price,
                    reason=f"🧪 SIMULATED TEST ALERT - RSI=35.0, Price={current_price:.4f}, MA50={current_price*1.01:.2f}, EMA10={current_price*1.02:.2f}",
                    strategy_type="Swing",
                    risk_approach=risk_display,
                    source="TEST",
                )
            except Exception as e:
                logger.warning(f"Failed to send Telegram BUY alert: {e}")
            
            # Create order if trade_enabled = true AND trade_amount_usd > 0
            order_created = False
            order_error_message = None
            order_result = None
            
            # Check if trade_enabled = true (REQUIRED for order creation)
            if not watchlist_item.trade_enabled:
                order_error_message = f"⚠️ TRADE NO HABILITADO\n\nEl campo 'Trade' está en NO para {symbol}.\n\nPor favor configura 'Trade' = YES en la Watchlist del Dashboard para crear órdenes automáticas."
                logger.info(f"Trade not enabled for {symbol} - only alert sent, no order created")
                
                # Send error notification to Telegram so user knows why order wasn't created
                try:
                    telegram_notifier.send_message(
                        f"⚠️ <b>TEST ALERT: Orden no creada</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"🟢 Señal: BUY detectada\n"
                        f"✅ Alerta enviada\n"
                        f"❌ Orden no creada: {order_error_message}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Telegram notification: {e}")
            
            # Check if trade_amount_usd is configured - REQUIRED, no default
            elif not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
                # Don't create order, return error message for dashboard display and Telegram
                order_error_message = f"⚠️ CONFIGURACIÓN REQUERIDA\n\nEl campo 'Amount USD' no está configurado para {symbol}.\n\nPor favor configura el campo 'Amount USD' en la Watchlist del Dashboard antes de crear órdenes automáticas."
                logger.warning(f"Cannot create order for {symbol}: trade_amount_usd not configured or invalid ({watchlist_item.trade_amount_usd})")
                
                # Send error notification to Telegram
                try:
                    telegram_notifier.send_message(
                        f"❌ <b>ORDER CREATION FAILED</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"🟢 Side: BUY\n"
                        f"❌ Error: {order_error_message}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Telegram error notification: {e}")
            
            # Create order if trade_enabled = true AND trade_amount_usd > 0
            elif watchlist_item.trade_enabled and watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0:
                logger.info(f"✅ Trade enabled for {symbol} - creating BUY order automatically from simulate-alert (async)")
                
                # Create order asynchronously in background to avoid timeout
                # This allows the endpoint to return immediately while order creation happens in background
                async def create_order_async():
                    """Background task to create order without blocking the response"""
                    try:
                        # Create a new database session for the background task
                        from app.database import SessionLocal
                        bg_db = SessionLocal()
                        try:
                            # Refresh watchlist_item in the new session
                            bg_watchlist_item = bg_db.query(WatchlistItem).filter(
                                WatchlistItem.symbol == symbol
                            ).first()
                            
                            if not bg_watchlist_item:
                                logger.error(f"Watchlist item not found in background task for {symbol}")
                                return
                            
                            # Import signal monitor service to reuse the order creation logic
                            from app.services.signal_monitor import SignalMonitorService
                            signal_monitor = SignalMonitorService()
                            
                            # Calculate resistance levels for SL/TP calculation (use current price as reference)
                            res_up = current_price * 1.05  # 5% above current price
                            res_down = current_price * 0.95  # 5% below current price
                            
                            # Create BUY order using the same logic as signal_monitor
                            logger.info(f"🔍 [Background] Calling _create_buy_order for {symbol} with amount_usd={bg_watchlist_item.trade_amount_usd}")
                            order_result = await signal_monitor._create_buy_order(
                                db=bg_db,
                                watchlist_item=bg_watchlist_item,
                                current_price=current_price,
                                res_up=res_up,
                                res_down=res_down
                            )
                            logger.info(f"🔍 [Background] _create_buy_order returned: {order_result}")
                            
                            # Check if this is an authentication error (already handled with specific message)
                            is_auth_error = (
                                order_result and 
                                isinstance(order_result, dict) and 
                                order_result.get("error_type") == "authentication"
                            )
                            
                            if is_auth_error:
                                # Authentication error was already handled with a specific message in _create_buy_order
                                # Don't send redundant generic message
                                logger.info(f"🔐 [Background] Authentication error detected for {symbol} - specific error message already sent, skipping generic message")
                            elif order_result and (order_result.get("order_id") or order_result.get("client_order_id")):
                                order_id = order_result.get("order_id") or order_result.get("client_order_id")
                                logger.info(f"✅ [Background] BUY order created successfully for {symbol}: order_id={order_id}")
                                
                                # Send success notification to Telegram
                                try:
                                    telegram_notifier.send_message(
                                        f"✅ <b>TEST ALERT: Orden creada exitosamente</b>\n\n"
                                        f"📊 Symbol: <b>{symbol}</b>\n"
                                        f"🟢 Side: BUY\n"
                                        f"💰 Amount: ${bg_watchlist_item.trade_amount_usd:.2f}\n"
                                        f"💵 Price: ${current_price:.4f}\n"
                                        f"🆔 Order ID: {order_id}\n"
                                        f"📊 Status: {order_result.get('status', 'UNKNOWN')}"
                                    )
                                except Exception as e:
                                    logger.warning(f"Failed to send Telegram success notification: {e}")
                                
                                # If order is immediately filled (MARKET orders usually are), trigger SL/TP creation
                                filled_price = order_result.get("filled_price") or order_result.get("avg_price") or current_price
                                filled_qty = order_result.get("filled_quantity")
                                
                                # If we don't have filled_quantity, estimate it
                                if not filled_qty and filled_price:
                                    filled_qty = bg_watchlist_item.trade_amount_usd / filled_price
                                elif not filled_qty:
                                    filled_qty = bg_watchlist_item.trade_amount_usd / current_price
                                
                                # Check if order is filled (MARKET orders are usually filled immediately)
                                order_status = order_result.get("status", "").upper()
                                is_filled = (
                                    order_status in ["FILLED", "filled"] or 
                                    order_result.get("avg_price") is not None or
                                    filled_price != current_price
                                )
                                
                                if is_filled:
                                    logger.info(f"✅ [Background] Order {order_id} is FILLED - creating SL/TP orders automatically")
                                    
                                    # Trigger SL/TP creation immediately
                                    try:
                                        from app.services.exchange_sync import ExchangeSyncService
                                        exchange_sync = ExchangeSyncService()
                                        
                                        # Create SL/TP orders for the filled order
                                        exchange_sync._create_sl_tp_for_filled_order(
                                            db=bg_db,
                                            symbol=symbol,
                                            side="BUY",
                                            filled_price=float(filled_price),
                                            filled_qty=float(filled_qty),
                                            order_id=str(order_id)
                                        )
                                        logger.info(f"✅ [Background] SL/TP orders created for {symbol} order {order_id}")
                                    except Exception as sl_tp_err:
                                        logger.warning(f"⚠️ [Background] Could not create SL/TP orders: {sl_tp_err}. Exchange sync will handle this.", exc_info=True)
                                else:
                                    logger.info(f"ℹ️ [Background] Order {order_id} status={order_status} - SL/TP will be created when order is filled")
                            else:
                                # Order creation failed for non-authentication reasons
                                error_msg = f"⚠️ La creación de orden retornó None para {symbol}. Esto puede deberse a:\n- Límite de órdenes abiertas alcanzado\n- Verificación de seguridad bloqueó la orden\n- Error interno en la creación de orden"
                                logger.warning(f"⚠️ [Background] Order creation returned None for {symbol}")
                                
                                # Send error notification to Telegram
                                try:
                                    telegram_notifier.send_message(
                                        f"⚠️ <b>TEST ALERT: Orden no creada</b>\n\n"
                                        f"📊 Symbol: <b>{symbol}</b>\n"
                                        f"🟢 Señal: BUY detectada\n"
                                        f"✅ Alerta enviada\n"
                                        f"❌ Orden no creada: {error_msg}\n\n"
                                        f"💡 Revisa los logs del backend para más detalles."
                                    )
                                except Exception as e:
                                    logger.warning(f"Failed to send Telegram error notification: {e}")
                                
                        except Exception as order_err:
                            logger.error(f"❌ [Background] Error creating order for {symbol}: {order_err}", exc_info=True)
                            
                            # Send error notification to Telegram
                            try:
                                telegram_notifier.send_message(
                                    f"❌ <b>ORDER CREATION FAILED</b>\n\n"
                                    f"📊 Symbol: <b>{symbol}</b>\n"
                                    f"🟢 Side: BUY\n"
                                    f"❌ Error: {str(order_err)}"
                                )
                            except Exception as e:
                                logger.warning(f"Failed to send Telegram error notification: {e}")
                        finally:
                            bg_db.close()
                    except Exception as bg_err:
                        logger.error(f"❌ [Background] Fatal error in order creation task for {symbol}: {bg_err}", exc_info=True)
                
                # Start order creation in background (don't await - return immediately)
                asyncio.create_task(create_order_async())
                logger.info(f"🚀 Order creation started in background for {symbol} - returning response immediately")
                
                # Mark as in progress (not completed yet)
                order_created = False
                order_result = None
                order_error_message = None
            
            response_data = {
                "ok": True,
                "message": f"BUY signal simulated for {symbol}",
                "symbol": symbol,
                "signal_type": signal_type,
                "price": current_price,
                "alert_sent": True,
                "order_created": order_created,
                "order_in_progress": watchlist_item.trade_enabled and watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 and not order_created and not order_error_message,
                "trade_enabled": watchlist_item.trade_enabled,
                "trade_amount_usd": watchlist_item.trade_amount_usd,
                "alert_enabled": watchlist_item.alert_enabled
            }
            
            # Add order details if order was created synchronously
            if order_result and order_created:
                response_data["order_id"] = order_result.get("order_id") or order_result.get("client_order_id")
                response_data["order_status"] = order_result.get("status", "UNKNOWN")
                response_data["filled_price"] = order_result.get("filled_price")
                response_data["sl_tp_created"] = True  # SL/TP creation attempted
            
            # Add note if order is being created in background
            if response_data.get("order_in_progress"):
                response_data["note"] = "Order creation started in background. Check logs or Telegram for order status."
            
            # Add error message if order was not created
            if order_error_message:
                response_data["note"] = order_error_message
                response_data["order_error"] = order_error_message
            
            return response_data
        
        else:  # SELL
            logger.info(f"🧪 SIMULATING SELL signal for {symbol}")
            
            # Send Telegram alert
            try:
                risk_display = (watchlist_item.sl_tp_mode or "conservative").title() if watchlist_item else "Conservative"
                telegram_notifier.send_sell_signal(
                    symbol=symbol,
                    price=current_price,
                    reason=f"🧪 SIMULATED TEST ALERT - RSI=75.0, Price={current_price:.4f}, MA50={current_price*0.98:.2f}, EMA10={current_price*0.97:.2f}",
                    strategy_type="Swing",
                    risk_approach=risk_display,
                    source="TEST",
                )
            except Exception as e:
                logger.warning(f"Failed to send Telegram SELL alert: {e}")
            
            # Create order if trade_enabled = true AND trade_amount_usd > 0
            order_created = False
            order_error_message = None
            order_result = None
            
            # Check if trade_enabled = true (REQUIRED for order creation)
            if not watchlist_item.trade_enabled:
                order_error_message = f"⚠️ TRADE NO HABILITADO\n\nEl campo 'Trade' está en NO para {symbol}.\n\nPor favor configura 'Trade' = YES en la Watchlist del Dashboard para crear órdenes automáticas."
                logger.info(f"Trade not enabled for {symbol} - only alert sent, no order created")
            
            # Check if trade_amount_usd is configured
            elif not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
                order_error_message = f"⚠️ CONFIGURACIÓN REQUERIDA\n\nEl campo 'Amount USD' no está configurado para {symbol}.\n\nPor favor configura el campo 'Amount USD' en la Watchlist del Dashboard antes de crear órdenes automáticas."
                logger.warning(f"Cannot create SELL order for {symbol}: trade_amount_usd not configured or invalid ({watchlist_item.trade_amount_usd})")
                
                try:
                    telegram_notifier.send_message(
                        f"❌ <b>ORDER CREATION FAILED</b>\n\n"
                        f"📊 Symbol: <b>{symbol}</b>\n"
                        f"🔴 Side: SELL\n"
                        f"❌ Error: {order_error_message}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send Telegram error notification: {e}")
            
            # Create order if trade_enabled = true AND trade_amount_usd > 0
            elif watchlist_item.trade_enabled and watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0:
                logger.info(f"✅ Trade enabled for {symbol} - creating SELL order automatically from simulate-alert (async)")
                
                # Create order asynchronously in background to avoid timeout
                async def create_sell_order_async():
                    """Background task to create SELL order without blocking the response"""
                    try:
                        # Create a new database session for the background task
                        from app.database import SessionLocal
                        bg_db = SessionLocal()
                        try:
                            # Refresh watchlist_item in the new session
                            bg_watchlist_item = bg_db.query(WatchlistItem).filter(
                                WatchlistItem.symbol == symbol
                            ).first()
                            
                            if not bg_watchlist_item:
                                logger.error(f"Watchlist item not found in background task for {symbol}")
                                return
                            
                            from app.services.signal_monitor import SignalMonitorService
                            signal_monitor = SignalMonitorService()
                            
                            # Calculate resistance levels for SL/TP calculation
                            res_up = current_price * 1.05
                            res_down = current_price * 0.95
                            
                            # Create SELL order using the same logic as signal_monitor
                            logger.info(f"🔍 [Background] Calling _create_sell_order for {symbol} with amount_usd={bg_watchlist_item.trade_amount_usd}")
                            order_result = await signal_monitor._create_sell_order(
                                db=bg_db,
                                watchlist_item=bg_watchlist_item,
                                current_price=current_price,
                                res_up=res_up,
                                res_down=res_down
                            )
                            logger.info(f"🔍 [Background] _create_sell_order returned: {order_result}")
                            
                            # Check if this is an authentication error (already handled with specific message)
                            is_auth_error = (
                                order_result and 
                                isinstance(order_result, dict) and 
                                order_result.get("error_type") == "authentication"
                            )
                            
                            if is_auth_error:
                                # Authentication error was already handled with a specific message in _create_sell_order
                                # Don't send redundant generic message
                                logger.info(f"🔐 [Background] Authentication error detected for SELL {symbol} - specific error message already sent, skipping generic message")
                            elif order_result and (order_result.get("order_id") or order_result.get("client_order_id")):
                                order_id = order_result.get("order_id") or order_result.get("client_order_id")
                                logger.info(f"✅ [Background] SELL order created successfully for {symbol}: order_id={order_id}")
                                
                                # If order is immediately filled, SL/TP creation is handled in _create_sell_order
                                filled_price = order_result.get("filled_price") or order_result.get("avg_price") or current_price
                                filled_qty = order_result.get("filled_quantity")
                                
                                order_status = order_result.get("status", "").upper()
                                is_filled = (
                                    order_status in ["FILLED", "filled"] or 
                                    order_result.get("avg_price") is not None or
                                    filled_price != current_price
                                )
                                
                                if is_filled:
                                    logger.info(f"✅ [Background] Order {order_id} is FILLED - SL/TP orders created automatically")
                                else:
                                    logger.info(f"ℹ️ [Background] Order {order_id} status={order_status} - SL/TP will be created when order is filled")
                            else:
                                logger.warning(f"⚠️ [Background] SELL order creation returned None or failed for {symbol}")
                                
                        except Exception as order_err:
                            logger.error(f"❌ [Background] Error creating SELL order for {symbol}: {order_err}", exc_info=True)
                            
                            try:
                                telegram_notifier.send_message(
                                    f"❌ <b>ORDER CREATION FAILED</b>\n\n"
                                    f"📊 Symbol: <b>{symbol}</b>\n"
                                    f"🔴 Side: SELL\n"
                                    f"❌ Error: {str(order_err)}"
                                )
                            except Exception as e:
                                logger.warning(f"Failed to send Telegram error notification: {e}")
                        finally:
                            bg_db.close()
                    except Exception as bg_err:
                        logger.error(f"❌ [Background] Fatal error in SELL order creation task for {symbol}: {bg_err}", exc_info=True)
                
                # Start order creation in background (don't await - return immediately)
                asyncio.create_task(create_sell_order_async())
                logger.info(f"🚀 SELL order creation started in background for {symbol} - returning response immediately")
                
                # Mark as in progress (not completed yet)
                order_created = False
                order_result = None
                order_error_message = None
            
            response_data = {
                "ok": True,
                "message": f"SELL signal simulated for {symbol}",
                "symbol": symbol,
                "signal_type": signal_type,
                "price": current_price,
                "alert_sent": True,
                "order_created": order_created,
                "order_in_progress": watchlist_item.trade_enabled and watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0 and not order_created and not order_error_message,
                "trade_enabled": watchlist_item.trade_enabled,
                "trade_amount_usd": watchlist_item.trade_amount_usd,
                "alert_enabled": watchlist_item.alert_enabled
            }
            
            # Add order details if order was created synchronously
            if order_result and order_created:
                response_data["order_id"] = order_result.get("order_id") or order_result.get("client_order_id")
                response_data["order_status"] = order_result.get("status", "UNKNOWN")
                response_data["filled_price"] = order_result.get("filled_price")
                response_data["sl_tp_created"] = True  # SL/TP creation attempted
            
            # Add note if order is being created in background
            if response_data.get("order_in_progress"):
                response_data["note"] = "Order creation started in background. Check logs or Telegram for order status."
            
            # Add error message if order was not created
            if order_error_message:
                response_data["note"] = order_error_message
                response_data["order_error"] = order_error_message
            
            return response_data
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error simulating alert: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error simulating alert: {str(e)}")


@router.post("/test/check-sl-tp")
def check_sl_tp(
    db: Session = Depends(get_db)
):
    """
    Manually trigger SL/TP check for all open positions
    """
    try:
        logger.info("🧪 Manually triggering SL/TP check...")
        
        # Check positions
        result = sl_tp_checker_service.check_positions_for_sl_tp(db)
        positions_missing = result.get('positions_missing_sl_tp', [])
        
        # Send reminder if needed
        reminder_sent = False
        if positions_missing:
            reminder_sent = sl_tp_checker_service.send_sl_tp_reminder(db)
        
        return {
            "ok": True,
            "message": "SL/TP check completed",
            "total_positions": result.get('total_positions', 0),
            "positions_missing_sl_tp": len(positions_missing),
            "reminder_sent": reminder_sent,
            "positions": [
                {
                    "symbol": pos['symbol'],
                    "currency": pos['currency'],
                    "balance": pos['balance'],
                    "has_sl": pos['has_sl'],
                    "has_tp": pos['has_tp'],
                    "sl_price": pos.get('sl_price'),
                    "tp_price": pos.get('tp_price')
                }
                for pos in positions_missing
            ],
            "checked_at": result.get('checked_at').isoformat() if result.get('checked_at') else None
        }
        
    except Exception as e:
        logger.error(f"Error checking SL/TP: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error checking SL/TP: {str(e)}")


@router.get("/test/diagnose-alert/{symbol}")
def diagnose_alert_issue(
    symbol: str,
    db: Session = Depends(get_db)
):
    """
    Diagnose why a test alert might not be creating orders
    Returns comprehensive diagnostic information about symbol configuration
    """
    try:
        symbol = symbol.upper()
        
        # Get watchlist item
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol
        ).first()
        
        if not watchlist_item:
            return {
                "ok": False,
                "symbol": symbol,
                "exists": False,
                "error": f"{symbol} not found in watchlist",
                "recommendations": [
                    f"Add {symbol} to watchlist from Dashboard",
                    "Configure 'Trade' = YES",
                    "Configure 'Amount USD' > 0"
                ]
            }
        
        # Get open orders for this symbol
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
        open_statuses = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]
        
        symbol_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == symbol,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status.in_(open_statuses)
        ).all()
        
        # Get total open orders
        total_open_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status.in_(open_statuses)
        ).count()
        
        # Check recent orders (last 5 minutes)
        from datetime import timedelta
        threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
        recent_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == symbol,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.created_at >= threshold
        ).count()
        
        # Check portfolio value if possible
        portfolio_value = None
        portfolio_exceeds_limit = False
        try:
            from app.services.order_position_service import calculate_portfolio_value_for_symbol
            # Use a dummy price for now
            current_price = 100.0  # Will be updated if we can fetch it
            try:
                from price_fetcher import get_price_with_fallback
                result = get_price_with_fallback(symbol, "15m")
                if result.get('price'):
                    current_price = result.get('price')
            except:
                pass
            
            portfolio_value, net_quantity = calculate_portfolio_value_for_symbol(db, symbol, current_price)
            if watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0:
                limit_value = 3 * watchlist_item.trade_amount_usd
                portfolio_exceeds_limit = portfolio_value > limit_value
        except Exception as e:
            logger.warning(f"Could not calculate portfolio value: {e}")
        
        # Build diagnostic results
        checks = []
        issues = []
        
        # Check 1: trade_enabled
        if not watchlist_item.trade_enabled:
            checks.append({
                "check": "trade_enabled",
                "status": "error",
                "message": "Trade is disabled - orders will NOT be created",
                "value": False
            })
            issues.append("trade_enabled = False")
        else:
            checks.append({
                "check": "trade_enabled",
                "status": "success",
                "message": "Trade is enabled",
                "value": True
            })
        
        # Check 2: trade_amount_usd
        if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
            checks.append({
                "check": "trade_amount_usd",
                "status": "error",
                "message": f"Amount USD not configured ({watchlist_item.trade_amount_usd}) - orders will NOT be created",
                "value": watchlist_item.trade_amount_usd
            })
            issues.append("trade_amount_usd not configured or <= 0")
        else:
            checks.append({
                "check": "trade_amount_usd",
                "status": "success",
                "message": f"Amount USD configured: ${watchlist_item.trade_amount_usd}",
                "value": watchlist_item.trade_amount_usd
            })
        
        # Check 3: alert_enabled
        if not watchlist_item.alert_enabled:
            checks.append({
                "check": "alert_enabled",
                "status": "warning",
                "message": "Alerts are disabled",
                "value": False
            })
        else:
            checks.append({
                "check": "alert_enabled",
                "status": "success",
                "message": "Alerts are enabled",
                "value": True
            })
        
        # Check 4: Open orders count
        if len(symbol_orders) >= 3:
            checks.append({
                "check": "open_orders_limit",
                "status": "warning",
                "message": f"Maximum open orders reached: {len(symbol_orders)}/3",
                "value": len(symbol_orders)
            })
            issues.append(f"Open orders limit reached: {len(symbol_orders)}/3")
        else:
            checks.append({
                "check": "open_orders_limit",
                "status": "success",
                "message": f"Open orders: {len(symbol_orders)}/3",
                "value": len(symbol_orders)
            })
        
        # Check 5: Recent orders
        if recent_orders > 0:
            checks.append({
                "check": "recent_orders",
                "status": "warning",
                "message": f"Recent orders in last 5 minutes: {recent_orders} - may block new orders due to cooldown",
                "value": recent_orders
            })
        else:
            checks.append({
                "check": "recent_orders",
                "status": "success",
                "message": "No recent orders",
                "value": recent_orders
            })
        
        # Check 6: Portfolio value
        if portfolio_value is not None:
            if portfolio_exceeds_limit:
                limit_value = 3 * watchlist_item.trade_amount_usd
                checks.append({
                    "check": "portfolio_limit",
                    "status": "warning",
                    "message": f"Portfolio value ${portfolio_value:.2f} exceeds limit ${limit_value:.2f} (3x trade_amount_usd)",
                    "value": portfolio_value
                })
                issues.append(f"Portfolio value exceeds limit")
            else:
                checks.append({
                    "check": "portfolio_limit",
                    "status": "success",
                    "message": f"Portfolio value: ${portfolio_value:.2f}",
                    "value": portfolio_value
                })
        
        # Build recommendations
        recommendations = []
        if not watchlist_item.trade_enabled:
            recommendations.append(f"Enable 'Trade' = YES for {symbol} in Dashboard")
        if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
            recommendations.append(f"Configure 'Amount USD' > 0 for {symbol} in Dashboard")
        if len(symbol_orders) >= 3:
            recommendations.append(f"Wait for some open orders to complete or cancel them (currently {len(symbol_orders)}/3)")
        if recent_orders > 0:
            recommendations.append(f"Wait for cooldown period (recent order created in last 5 minutes)")
        if portfolio_exceeds_limit:
            recommendations.append("Wait for portfolio value to decrease or increase trade_amount_usd")
        
        if not recommendations:
            recommendations.append("Configuration looks correct. If orders still don't create, check backend logs for specific errors.")
        
        return {
            "ok": True,
            "symbol": symbol,
            "exists": True,
            "configuration": {
                "trade_enabled": watchlist_item.trade_enabled,
                "trade_amount_usd": watchlist_item.trade_amount_usd,
                "alert_enabled": watchlist_item.alert_enabled,
                "buy_alert_enabled": getattr(watchlist_item, 'buy_alert_enabled', None),
                "sell_alert_enabled": getattr(watchlist_item, 'sell_alert_enabled', None),
                "trade_on_margin": watchlist_item.trade_on_margin,
                "sl_tp_mode": watchlist_item.sl_tp_mode,
            },
            "orders": {
                "open_for_symbol": len(symbol_orders),
                "total_open_global": total_open_orders,
                "recent_count": recent_orders,
                "max_per_symbol": 3,
            },
            "portfolio": {
                "value": portfolio_value,
                "exceeds_limit": portfolio_exceeds_limit,
            } if portfolio_value is not None else None,
            "checks": checks,
            "issues": issues,
            "has_issues": len(issues) > 0,
            "recommendations": recommendations,
        }
        
    except Exception as e:
        logger.error(f"Error diagnosing alert issue for {symbol}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error diagnosing: {str(e)}")


@router.post("/test/send-telegram-message")
def send_test_telegram_message(
    payload: Dict[str, Any] = Body(...),
):
    """
    Send a test message to Telegram
    Body: {
        "symbol": "BTC_USDT",
        "message": "Optional custom message"
    }
    """
    try:
        symbol = payload.get("symbol", "BTC_USDT").upper()
        custom_message = payload.get("message", None)
        
        if custom_message:
            message = custom_message
        else:
            from datetime import datetime
            from app.utils.http_client import http_get, http_post
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = f"""🧪 <b>MENSAJE DE PRUEBA</b>

📈 Symbol: <b>{symbol}</b>
⏰ Hora: {now}

✅ Este es un mensaje de prueba para verificar la conexión con Telegram.
"""
        
        result = telegram_notifier.send_message(message)
        
        if result:
            logger.info(f"✅ Test message sent to Telegram for {symbol}")
            return {
                "ok": True,
                "message": "Test message sent successfully",
                "symbol": symbol,
                "telegram_enabled": telegram_notifier.enabled
            }
        else:
            logger.warning(f"❌ Failed to send test message to Telegram for {symbol}")
            return {
                "ok": False,
                "message": "Failed to send test message (Telegram may be disabled)",
                "symbol": symbol,
                "telegram_enabled": telegram_notifier.enabled
            }
    
    except Exception as e:
        logger.error(f"Error sending test Telegram message: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error sending test message: {str(e)}")


@router.post("/test/send-executed-order")
def test_send_executed_order(
    symbol: str = Body(..., embed=True, description="Symbol (e.g., ETH_USDT)"),
    side: str = Body("BUY", embed=True, description="Order side: BUY or SELL"),
    price: float = Body(..., embed=True, description="Execution price"),
    quantity: float = Body(..., embed=True, description="Quantity executed"),
    order_id: Optional[str] = Body(None, embed=True, description="Order ID"),
    order_type: Optional[str] = Body("LIMIT", embed=True, description="Order type"),
    order_role: Optional[str] = Body(None, embed=True, description="Order role: STOP_LOSS, TAKE_PROFIT, or None"),
    trade_signal_id: Optional[int] = Body(None, embed=True, description="Trade signal ID if created by alert"),
    parent_order_id: Optional[str] = Body(None, embed=True, description="Parent order ID if SL/TP"),
    entry_price: Optional[float] = Body(None, embed=True, description="Entry price for profit/loss calculation")
):
    """
    Test endpoint to send an executed order notification with the new format showing order origin.
    
    Examples:
    - SL/TP order: {"symbol": "ETH_USDT", "side": "SELL", "price": 2500.0, "quantity": 0.1, "order_role": "STOP_LOSS", "entry_price": 2600.0}
    - Alert order: {"symbol": "BTC_USDT", "side": "BUY", "price": 45000.0, "quantity": 0.01, "trade_signal_id": 123}
    - Manual order: {"symbol": "DOGE_USDT", "side": "BUY", "price": 0.08, "quantity": 1000}
    """
    try:
        total_usd = price * quantity
        
        result = telegram_notifier.send_executed_order(
            symbol=symbol,
            side=side,
            price=price,
            quantity=quantity,
            total_usd=total_usd,
            order_id=order_id or f"TEST_{int(time.time())}",
            order_type=order_type,
            entry_price=entry_price,
            open_orders_count=None,
            order_role=order_role,
            trade_signal_id=trade_signal_id,
            parent_order_id=parent_order_id
        )
        
        if result:
            return {
                "ok": True,
                "message": "Executed order notification sent successfully",
                "symbol": symbol,
                "side": side,
                "order_origin": _determine_order_origin(order_role, trade_signal_id, parent_order_id)
            }
        else:
            return {
                "ok": False,
                "message": "Failed to send executed order notification",
                "symbol": symbol
            }
    except Exception as e:
        logger.error(f"Error sending test executed order notification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


def _determine_order_origin(order_role: Optional[str], trade_signal_id: Optional[int], parent_order_id: Optional[str]) -> str:
    """Helper to determine order origin for response"""
    if order_role:
        if trade_signal_id:
            return f"{order_role} (triggered by alert)"
        return order_role
    elif trade_signal_id:
        return "Alert"
    elif parent_order_id:
        return "Related order"
    else:
        return "Manual"


@router.post("/test/inject-price")
def inject_test_price(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """
    Test-only endpoint to inject a mock price for a symbol to simulate threshold crossing.
    
    This endpoint is ONLY enabled when ENABLE_TEST_PRICE_INJECTION=1 (local dev only).
    It updates MarketPrice and MarketData with a simulated price change to test throttle logic.
    
    Body: {
        "symbol": "BTC_USDT",
        "price": 50000.0,  # Optional: Absolute price (takes precedence over price_delta_usd)
        "price_delta_usd": 10.5,  # Optional: Price change in USD (absolute, not percentage)
        "rsi": 30.0,  # Optional: Override RSI value
        "ma50": 49000.0,  # Optional: Override MA50 value
        "ema10": 49500.0,  # Optional: Override EMA10 value
        "ma200": 48000.0,  # Optional: Override MA200 value
    }
    
    If both "price" and "price_delta_usd" are provided, "price" takes precedence.
    """
    # CRITICAL: Only enable in local dev with explicit flag
    if os.getenv("ENABLE_TEST_PRICE_INJECTION") != "1":
        raise HTTPException(
            status_code=403,
            detail="Test price injection is disabled. Set ENABLE_TEST_PRICE_INJECTION=1 to enable (local dev only)."
        )
    
    try:
        symbol = payload.get("symbol", "").upper()
        
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")
        
        # Support both absolute price and price delta
        price_delta_usd = 0.0
        if "price" in payload and payload.get("price") is not None:
            # Use absolute price if provided
            target_price = float(payload.get("price"))
            price_delta_usd = None  # Will be calculated after getting current price
        elif "price_delta_usd" in payload and payload.get("price_delta_usd") is not None:
            # Use price delta if provided
            price_delta_usd = float(payload.get("price_delta_usd"))
        else:
            raise HTTPException(status_code=400, detail="Either 'price' or 'price_delta_usd' is required")
        
        # Get current price from MarketPrice
        market_price = db.query(MarketPrice).filter(MarketPrice.symbol == symbol).first()
        if not market_price or not market_price.price:
            raise HTTPException(status_code=404, detail=f"No price data found for {symbol}")
        
        current_price = float(market_price.price)
        
        # Calculate new price based on provided input
        if price_delta_usd is None:
            # Absolute price was provided
            new_price = target_price
            price_delta_usd = new_price - current_price
        else:
            # Price delta was provided
            new_price = current_price + price_delta_usd
        
        if new_price <= 0:
            raise HTTPException(status_code=400, detail=f"Invalid price delta: would result in price <= 0")
        
        # Update MarketPrice
        market_price.price = new_price
        market_price.updated_at = datetime.now(timezone.utc)
        
        # Update MarketData if it exists (MarketDataModel is imported at top from market_price)
        market_data = db.query(MarketDataModel).filter(MarketDataModel.symbol == symbol).first()
        if market_data:
            # Update price in MarketData to match MarketPrice
            market_data.price = new_price
            # Optionally update indicators if provided
            if "rsi" in payload and payload.get("rsi") is not None:
                market_data.rsi = float(payload.get("rsi"))
            if "ma50" in payload and payload.get("ma50") is not None:
                market_data.ma50 = float(payload.get("ma50"))
            if "ema10" in payload and payload.get("ema10") is not None:
                market_data.ema10 = float(payload.get("ema10"))
            if "ma200" in payload and payload.get("ma200") is not None:
                market_data.ma200 = float(payload.get("ma200"))
            if "current_volume" in payload and payload.get("current_volume") is not None:
                market_data.current_volume = float(payload.get("current_volume"))
            if "avg_volume" in payload and payload.get("avg_volume") is not None:
                market_data.avg_volume = float(payload.get("avg_volume"))
                # Calculate volume ratio
                if market_data.current_volume and market_data.avg_volume and market_data.avg_volume > 0:
                    market_data.volume_ratio = market_data.current_volume / market_data.avg_volume
            market_data.updated_at = datetime.now(timezone.utc)
        else:
            # Create MarketData entry if it doesn't exist (MarketDataModel is imported at top from market_price)
            # Calculate volume ratio if volumes provided
            volume_ratio = None
            current_volume = payload.get("current_volume")
            avg_volume = payload.get("avg_volume")
            if current_volume and avg_volume and avg_volume > 0:
                volume_ratio = float(current_volume) / float(avg_volume)
            
            market_data = MarketDataModel(
                symbol=symbol,
                price=new_price,
                rsi=payload.get("rsi"),
                ma50=payload.get("ma50"),
                ema10=payload.get("ema10"),
                ma200=payload.get("ma200"),
                current_volume=current_volume,
                avg_volume=avg_volume,
                volume_ratio=volume_ratio,
                updated_at=datetime.now(timezone.utc)
            )
            db.add(market_data)
        
        db.commit()
        
        price_change_pct = (price_delta_usd / current_price) * 100
        
        logger.info(
            f"[TEST_PRICE_INJECTION] {symbol} price injected: "
            f"${current_price:.4f} -> ${new_price:.4f} "
            f"(delta: ${price_delta_usd:.2f}, {price_change_pct:.2f}%)"
        )
        
        # Trigger signal evaluation for this symbol
        try:
            watchlist_item = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol,
                WatchlistItem.is_deleted == False
            ).first()
            
            if watchlist_item:
                # Trigger evaluation
                signal_monitor_service._check_signal_for_coin_sync(db, watchlist_item)
                logger.info(f"[TEST_PRICE_INJECTION] Triggered signal evaluation for {symbol}")
        except Exception as eval_err:
            logger.warning(f"[TEST_PRICE_INJECTION] Failed to trigger evaluation: {eval_err}")
        
        return {
            "ok": True,
            "symbol": symbol,
            "previous_price": current_price,
            "new_price": new_price,
            "price_delta_usd": price_delta_usd,
            "price_change_pct": round(price_change_pct, 2),
            "message": f"Price injected: ${current_price:.4f} -> ${new_price:.4f}"
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error injecting test price: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error injecting test price: {str(e)}")

