import logging
import os
from typing import Dict, List
from decimal import Decimal
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.instrument import Instrument
from app.models.risk_limit import InstrumentRiskLimit
from app.models.order import Order
from app.models.position import Position
from app.services.market_data_manager import market_data_manager
from app.services.brokers.base import Exchange
from app.services.signals.signal_engine import evaluate_signals
from app.services.brokers.crypto_com_trade import trade_client

logger = logging.getLogger(__name__)

def evaluate_once(db: Session, user_id: int) -> Dict:
    """Evaluate and execute paper trading logic for a user"""
    
    placed = []
    rejected = []
    filled = []
    
    # Determine if we're in live trading mode
    live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
    
    # List user's instruments
    instruments = db.query(Instrument).filter(Instrument.user_id == user_id).all()
    
    if not instruments:
        logger.info(f"No instruments found for user {user_id}")
        return {"placed": placed, "rejected": rejected, "filled": filled}
    
    for instrument in instruments:
        # Read risk limit
        risk_limit = db.query(InstrumentRiskLimit).filter(
            InstrumentRiskLimit.instrument_id == instrument.id,
            InstrumentRiskLimit.user_id == user_id
        ).first()
        
        if not risk_limit:
            logger.info(f"No risk limit found for instrument {instrument.id}")
            continue
        
        # Get last price
        try:
            exchange: Exchange = risk_limit.preferred_exchange
            last_price = market_data_manager.get_last_price(exchange, instrument.symbol)
            logger.info(f"Price for {instrument.symbol} on {exchange}: {last_price}")
            
            # Evaluate signals
            signals = evaluate_signals(instrument.symbol, exchange)
            logger.info(f"Signals for {instrument.symbol}: RSI={signals['rsi']}, Res_up={signals['res_up']}, Res_down={signals['res_down']}, Method={signals['method']}")
        except Exception as e:
            logger.error(f"Failed to get price for {instrument.symbol}: {e}")
            continue
        
        if last_price <= 0:
            logger.info(f"Invalid price for {instrument.symbol}: {last_price}")
            continue
        
        # Check existing position
        position = db.query(Position).filter(
            Position.instrument_id == instrument.id,
            Position.user_id == user_id
        ).first()
        
        # Count open orders
        open_orders = db.query(Order).filter(
            Order.instrument_id == instrument.id,
            Order.user_id == user_id,
            Order.status == "NEW"
        ).count()
        
        # Calculate current exposure
        current_exposure = Decimal(0)
        if position:
            current_exposure = position.qty * position.avg_price
        
        # Rule 1: BUY if RSI < 40 and price <= res_down
        if not position and last_price > 0:
            # Check signal conditions
            should_buy = signals['rsi'] < 40 and last_price <= float(signals['res_down'])
            
            if not should_buy:
                logger.info(f"Skipping BUY for {instrument.symbol}: RSI={signals['rsi']}, Price={last_price}, Res_down={signals['res_down']}")
                continue
            
            # Calculate max buy amount (capped by max_buy_usd)
            max_buy_amount = min(Decimal(1000), risk_limit.max_buy_usd)
            
            # Validate limits
            if open_orders >= risk_limit.max_open_orders:
                logger.info(f"Rejected BUY for {instrument.symbol}: open_orders ({open_orders}) >= max_open_orders ({risk_limit.max_open_orders})")
                rejected.append({
                    "instrument_id": instrument.id,
                    "symbol": instrument.symbol,
                    "reason": "MAX_OPEN_ORDERS_EXCEEDED"
                })
                continue
            
            if current_exposure >= risk_limit.max_buy_usd:
                logger.info(f"Rejected BUY for {instrument.symbol}: current_exposure ({current_exposure}) >= max_buy_usd ({risk_limit.max_buy_usd})")
                rejected.append({
                    "instrument_id": instrument.id,
                    "symbol": instrument.symbol,
                    "reason": "MAX_BUY_USD_EXCEEDED"
                })
                continue
            
            # Calculate quantity
            qty = max_buy_amount / Decimal(str(last_price))
            logger.info(f"Calculated BUY qty for {instrument.symbol}: {qty}")
            
            # Validate qty > 0
            if qty <= 0:
                logger.info(f"Rejected BUY for {instrument.symbol}: qty <= 0")
                rejected.append({
                    "instrument_id": instrument.id,
                    "symbol": instrument.symbol,
                    "reason": "INVALID_QTY"
                })
                continue
            
            # Determine margin and leverage
            is_margin = risk_limit.allow_margin
            leverage = None
            if is_margin:
                leverage = min(risk_limit.max_leverage, Decimal(2.0))  # Cap at 2x for demo
            
            # LIVE TRADING LOGIC: Use real exchange if CRYPTO_COM and live_trading=True
            if live_trading and exchange == "CRYPTO_COM":
                logger.info(f"Live trading: placing MARKET BUY order on Crypto.com")
                try:
                    result = trade_client.place_market_order(
                        instrument.symbol,
                        "BUY",
                        float(qty),
                        is_margin=is_margin,
                        leverage=float(leverage) if leverage else None,
                        dry_run=False
                    )
                    
                    # Create order with real exchange response
                    order = Order(
                        user_id=user_id,
                        instrument_id=instrument.id,
                        side="BUY",
                        type="MARKET",
                        price=Decimal(str(last_price)),
                        qty=qty,
                        status="FILLED" if result.get("status") == "FILLED" else "NEW",
                        exchange=risk_limit.preferred_exchange,
                        is_margin=is_margin,
                        leverage=leverage,
                        filled_at=datetime.utcnow() if result.get("status") == "FILLED" else None
                    )
                    db.add(order)
                    db.flush()
                    
                    if result.get("status") == "FILLED":
                        # Create or update position
                        position = Position(
                            user_id=user_id,
                            instrument_id=instrument.id,
                            qty=qty,
                            avg_price=Decimal(str(last_price)),
                            is_margin=is_margin,
                            leverage=leverage
                        )
                        db.add(position)
                    
                    filled.append({
                        "order_id": order.id,
                        "instrument_id": instrument.id,
                        "symbol": instrument.symbol,
                        "side": "BUY",
                        "qty": float(qty),
                        "price": float(last_price),
                        "mode": "LIVE"
                    })
                    
                    logger.info(f"LIVE BUY order filled for {instrument.symbol}: {qty} @ {last_price}")
                except Exception as e:
                    logger.error(f"Failed to place live BUY order: {e}")
                    rejected.append({
                        "instrument_id": instrument.id,
                        "symbol": instrument.symbol,
                        "reason": f"LIVE_ORDER_FAILED: {str(e)}"
                    })
                    continue
            else:
                # PAPER TRADING LOGIC
                logger.info(f"Paper trading: simulating BUY order")
                
                # Create order
                order = Order(
                    user_id=user_id,
                    instrument_id=instrument.id,
                    side="BUY",
                    type="MARKET",
                    price=Decimal(str(last_price)),
                    qty=qty,
                    status="FILLED",  # Auto-fill in paper trading
                    exchange=risk_limit.preferred_exchange,
                    is_margin=is_margin,
                    leverage=leverage,
                    filled_at=datetime.utcnow()
                )
                db.add(order)
                db.flush()
                
                # Create or update position
                position = Position(
                    user_id=user_id,
                    instrument_id=instrument.id,
                    qty=qty,
                    avg_price=Decimal(str(last_price)),
                    is_margin=is_margin,
                    leverage=leverage
                )
                db.add(position)
                
                filled.append({
                    "order_id": order.id,
                    "instrument_id": instrument.id,
                    "symbol": instrument.symbol,
                    "side": "BUY",
                    "qty": float(qty),
                    "price": float(last_price),
                    "mode": "PAPER"
                })
                
                logger.info(f"PAPER BUY order filled for {instrument.symbol}: {qty} @ {last_price}")
        
        # Rule 2: SELL if RSI > 70 and price >= res_up
        elif position and position.qty > 0:
            # Check signal conditions
            should_sell = signals['rsi'] > 70 and last_price >= float(signals['res_up'])
            
            if not should_sell:
                logger.info(f"Skipping SELL for {instrument.symbol}: RSI={signals['rsi']}, Price={last_price}, Res_up={signals['res_up']}")
                continue
            
            # Validate limits
            if open_orders >= risk_limit.max_open_orders:
                logger.info(f"Rejected SELL for {instrument.symbol}: open_orders ({open_orders}) >= max_open_orders ({risk_limit.max_open_orders})")
                rejected.append({
                    "instrument_id": instrument.id,
                    "symbol": instrument.symbol,
                    "reason": "MAX_OPEN_ORDERS_EXCEEDED"
                })
                continue
            
            # Calculate sell quantity (sell all)
            qty = position.qty
            logger.info(f"Calculated SELL qty for {instrument.symbol}: {qty}")
            
            # LIVE TRADING LOGIC: Use real exchange if CRYPTO_COM and live_trading=True
            if live_trading and exchange == "CRYPTO_COM":
                logger.info(f"Live trading: placing MARKET SELL order on Crypto.com")
                try:
                    result = trade_client.place_market_order(
                        instrument.symbol,
                        "SELL",
                        float(qty),
                        is_margin=position.is_margin,
                        leverage=float(position.leverage) if position.leverage else None,
                        dry_run=False
                    )
                    
                    # Create sell order with real exchange response
                    order = Order(
                        user_id=user_id,
                        instrument_id=instrument.id,
                        side="SELL",
                        type="MARKET",
                        price=Decimal(str(last_price)),
                        qty=qty,
                        status="FILLED" if result.get("status") == "FILLED" else "NEW",
                        exchange=risk_limit.preferred_exchange,
                        is_margin=position.is_margin,
                        leverage=position.leverage,
                        filled_at=datetime.utcnow() if result.get("status") == "FILLED" else None
                    )
                    db.add(order)
                    db.flush()
                    
                    if result.get("status") == "FILLED":
                        # Update position (subtract qty, close if reaches 0)
                        position.qty = Decimal(0)
                    
                    filled.append({
                        "order_id": order.id,
                        "instrument_id": instrument.id,
                        "symbol": instrument.symbol,
                        "side": "SELL",
                        "qty": float(qty),
                        "price": float(last_price),
                        "mode": "LIVE"
                    })
                    
                    logger.info(f"LIVE SELL order filled for {instrument.symbol}: {qty} @ {last_price}")
                except Exception as e:
                    logger.error(f"Failed to place live SELL order: {e}")
                    rejected.append({
                        "instrument_id": instrument.id,
                        "symbol": instrument.symbol,
                        "reason": f"LIVE_ORDER_FAILED: {str(e)}"
                    })
                    continue
            else:
                # PAPER TRADING LOGIC
                logger.info(f"Paper trading: simulating SELL order")
                
                # Create sell order
                order = Order(
                    user_id=user_id,
                    instrument_id=instrument.id,
                    side="SELL",
                    type="MARKET",
                    price=Decimal(str(last_price)),
                    qty=qty,
                    status="FILLED",  # Auto-fill in paper trading
                    exchange=risk_limit.preferred_exchange,
                    is_margin=position.is_margin,
                    leverage=position.leverage,
                    filled_at=datetime.utcnow()
                )
                db.add(order)
                db.flush()
                
                # Update position (subtract qty, close if reaches 0)
                position.qty = Decimal(0)
                
                filled.append({
                    "order_id": order.id,
                    "instrument_id": instrument.id,
                    "symbol": instrument.symbol,
                    "side": "SELL",
                    "qty": float(qty),
                    "price": float(last_price),
                    "mode": "PAPER"
                })
                
                logger.info(f"PAPER SELL order filled for {instrument.symbol}: {qty} @ {last_price}")
    
    db.commit()
    
    return {
        "placed": placed,
        "rejected": rejected,
        "filled": filled
    }
