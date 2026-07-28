from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.deps.auth import get_current_user
from app.database import get_db
from app.services.brokers.crypto_com_trade import trade_client
from app.services.telegram_notifier import telegram_notifier
from pydantic import BaseModel
from typing import Optional
import logging
import os
import json

logger = logging.getLogger(__name__)
router = APIRouter()

# ============================================================================
# REFERENCE FLOW DOCUMENTATION
# ============================================================================
# This endpoint implements the "golden reference" flow for manual BUY + SL + TP orders.
# 
# FLOW:
# 1. Creates a BUY LIMIT order (entry order)
# 2. Automatically creates a STOP_LOSS order (STOP_LIMIT type)
# 3. Automatically creates a TAKE_PROFIT order (TAKE_PROFIT_LIMIT type)
#
# PAYLOAD FORMATS THAT WORK:
# 
# STOP_LOSS (STOP_LIMIT):
#   - type: "STOP_LIMIT"
#   - side: "SELL" (for BUY entry) or "BUY" (for SELL entry) - UPPERCASE
#   - price: SL price (execution price)
#   - quantity: quantity to close
#   - trigger_price: SL trigger price (usually SL price * 0.99 for BUY entry)
#   - ref_price: entry_price (price of the original BUY order)
#   - instrument_name: symbol (e.g., "AKT_USDT")
#   - Optional: client_oid, time_in_force="GOOD_TILL_CANCEL"
#
# TAKE_PROFIT (TAKE_PROFIT_LIMIT):
#   - type: "TAKE_PROFIT_LIMIT"
#   - side: "SELL" (for BUY entry) or "BUY" (for SELL entry) - UPPERCASE
#   - price: TP price (execution price)
#   - quantity: quantity to close
#   - trigger_price: TP price (same as price for TAKE_PROFIT_LIMIT)
#   - ref_price: calculated from market price (must be < market for SELL, > market for BUY)
#   - trigger_condition: ">= {TP_price}"
#   - instrument_name: symbol (e.g., "AKT_USDT")
#   - Optional: client_oid, time_in_force="GOOD_TILL_CANCEL"
#
# IMPORTANT NOTES:
# - entry_price is CRITICAL for STOP_LOSS ref_price (must be the original BUY price)
# - For TAKE_PROFIT, ref_price is calculated dynamically from current market price
# - Both orders use the same quantity as the entry order
# - Side is inverted from entry: BUY entry → SELL for SL/TP
# ============================================================================

class ManualTradeRequest(BaseModel):
    symbol: str
    side: str  # "BUY" or "SELL"
    quantity: float
    price: Optional[float] = None  # If None, uses market price
    is_margin: bool = False
    leverage: Optional[int] = None
    sl_percentage: Optional[float] = None
    tp_percentage: Optional[float] = None
    sl_tp_mode: str = "conservative"  # "conservative" or "aggressive"

@router.post("/manual-trade/confirm")
def confirm_manual_trade(
    request: ManualTradeRequest,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Confirm manual trade order with SL/TP"""
    try:
        symbol = request.symbol
        side = request.side.upper()
        quantity = request.quantity
        price = request.price
        is_margin = request.is_margin
        leverage = request.leverage
        sl_percentage = request.sl_percentage
        tp_percentage = request.tp_percentage
        sl_tp_mode = request.sl_tp_mode
        
        # Validate inputs
        if side not in ["BUY", "SELL"]:
            raise HTTPException(status_code=400, detail="Side must be BUY or SELL")
        
        if quantity <= 0:
            raise HTTPException(status_code=400, detail="Quantity must be positive")
        
        # Get current price if not provided
        if not price:
            # This would need to be implemented to get current market price
            raise HTTPException(status_code=400, detail="Price is required for manual trades")
        
        # Calculate SL/TP prices
        if side == "BUY":
            if sl_percentage:
                sl_price = price * (1 - sl_percentage / 100)
            else:
                # Use default SL based on mode
                sl_price = price * 0.97 if sl_tp_mode == "conservative" else price * 0.98
            
            if tp_percentage:
                tp_price = price * (1 + tp_percentage / 100)
            else:
                # Use default TP based on mode
                tp_price = price * 1.03 if sl_tp_mode == "conservative" else price * 1.02
        else:  # SELL
            if sl_percentage:
                sl_price = price * (1 + sl_percentage / 100)
            else:
                # Use default SL based on mode
                sl_price = price * 1.03 if sl_tp_mode == "conservative" else price * 1.02
            
            if tp_percentage:
                tp_price = price * (1 - tp_percentage / 100)
            else:
                # Use default TP based on mode
                tp_price = price * 0.97 if sl_tp_mode == "conservative" else price * 0.98
        
        # Place main order
        live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
        
        if price:
            # Limit order
            main_order = trade_client.place_limit_order(
                symbol=symbol,
                side=side,
                price=price,
                qty=quantity,
                is_margin=is_margin,
                leverage=leverage,
                dry_run=not live_trading
            )
            
            # Log BUY order payload for reference
            logger.info(f"[TP_ORDER][REFERENCE] BUY order created:")
            logger.info(f"[TP_ORDER][REFERENCE]   symbol: {symbol}")
            logger.info(f"[TP_ORDER][REFERENCE]   side: {side}")
            logger.info(f"[TP_ORDER][REFERENCE]   price: {price}")
            logger.info(f"[TP_ORDER][REFERENCE]   quantity: {quantity}")
            logger.info(f"[TP_ORDER][REFERENCE]   order_id: {main_order.get('order_id') or main_order.get('client_order_id')}")
            logger.info(f"[TP_ORDER][REFERENCE]   BUY order response: {json.dumps(main_order, indent=2, ensure_ascii=False)}")
        else:
            # Market order (would need to implement market order function)
            raise HTTPException(status_code=400, detail="Market orders not implemented yet")
        
        # Get entry price from main order (for SL/TP ref_price calculation)
        entry_price = price  # Use the limit price as entry price
        if isinstance(main_order, dict):
            # Try to get filled price if order was immediately filled
            filled_price = main_order.get("avg_price") or main_order.get("price")
            if filled_price:
                try:
                    entry_price = float(filled_price)
                    logger.info(f"[TP_ORDER][REFERENCE] Using filled price as entry_price: {entry_price}")
                except:
                    pass
        
        # Send Telegram notification for main order
        margin_text = f"on margin ({leverage}x)" if is_margin else "spot"
        telegram_notifier.send_buy_alert(
            symbol=symbol,
            price=price,
            quantity=quantity,
            margin=is_margin,
            leverage=leverage
        )
        
        # Calculate SL trigger price
        sl_trigger_price = sl_price * 0.99 if side == "BUY" else sl_price * 1.01
        
        # Place SL order
        logger.info(f"[TP_ORDER][REFERENCE] Creating STOP_LOSS order:")
        logger.info(f"[TP_ORDER][REFERENCE]   symbol: {symbol}")
        logger.info(f"[TP_ORDER][REFERENCE]   side: {'SELL' if side == 'BUY' else 'BUY'} (inverted from entry)")
        logger.info(f"[TP_ORDER][REFERENCE]   price: {sl_price} (SL execution price)")
        logger.info(f"[TP_ORDER][REFERENCE]   quantity: {quantity}")
        logger.info(f"[TP_ORDER][REFERENCE]   trigger_price: {sl_trigger_price}")
        logger.info(f"[TP_ORDER][REFERENCE]   entry_price: {entry_price} (for ref_price)")
        
        sl_order = trade_client.place_stop_loss_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            price=sl_price,
            qty=quantity,
            trigger_price=sl_trigger_price,
            entry_price=entry_price,  # CRITICAL: Pass entry_price for ref_price calculation
            dry_run=not live_trading,
            source="manual"  # Mark as manual for logging
        )
        
        # Log SL order payload for reference
        logger.info(f"[TP_ORDER][REFERENCE] STOP_LOSS order response:")
        logger.info(f"[TP_ORDER][REFERENCE]   SL order response: {json.dumps(sl_order, indent=2, ensure_ascii=False)}")
        if "error" in sl_order:
            logger.warning(f"[TP_ORDER][REFERENCE]   SL order ERROR: {sl_order.get('error')}")
        else:
            logger.info(f"[TP_ORDER][REFERENCE]   SL order_id: {sl_order.get('order_id') or sl_order.get('client_order_id')}")
        
        # Place TP order
        logger.info(f"[TP_ORDER][REFERENCE] Creating TAKE_PROFIT order:")
        logger.info(f"[TP_ORDER][REFERENCE]   symbol: {symbol}")
        logger.info(f"[TP_ORDER][REFERENCE]   side: {'SELL' if side == 'BUY' else 'BUY'} (inverted from entry)")
        logger.info(f"[TP_ORDER][REFERENCE]   price: {tp_price} (TP execution price)")
        logger.info(f"[TP_ORDER][REFERENCE]   quantity: {quantity}")
        logger.info(f"[TP_ORDER][REFERENCE]   entry_price: {entry_price} (for ref_price calculation)")
        
        tp_order = trade_client.place_take_profit_order(
            symbol=symbol,
            side="SELL" if side == "BUY" else "BUY",
            price=tp_price,
            qty=quantity,
            entry_price=entry_price,  # CRITICAL: Pass entry_price for ref_price calculation
            dry_run=not live_trading,
            source="manual"  # Mark as manual for logging
        )
        
        # Log TP order payload for reference
        logger.info(f"[TP_ORDER][REFERENCE] TAKE_PROFIT order response:")
        logger.info(f"[TP_ORDER][REFERENCE]   TP order response: {json.dumps(tp_order, indent=2, ensure_ascii=False)}")
        if "error" in tp_order:
            logger.warning(f"[TP_ORDER][REFERENCE]   TP order ERROR: {tp_order.get('error')}")
        else:
            logger.info(f"[TP_ORDER][REFERENCE]   TP order_id: {tp_order.get('order_id') or tp_order.get('client_order_id')}")
        
        # Get order IDs
        sl_order_id = sl_order.get("order_id") or sl_order.get("client_order_id") if isinstance(sl_order, dict) and "error" not in sl_order else None
        tp_order_id = tp_order.get("order_id") or tp_order.get("client_order_id") if isinstance(tp_order, dict) and "error" not in tp_order else None
        main_order_id = main_order.get("order_id") or main_order.get("client_order_id") if isinstance(main_order, dict) else None
        
        # Send Telegram notification for SL/TP orders
        telegram_notifier.send_sl_tp_orders(
            symbol=symbol,
            sl_price=sl_price,
            tp_price=tp_price,
            quantity=quantity,
            mode=sl_tp_mode,
            sl_order_id=str(sl_order_id) if sl_order_id else None,
            tp_order_id=str(tp_order_id) if tp_order_id else None,
            original_order_id=str(main_order_id) if main_order_id else None
        )
        
        return {
            "message": "Manual trade executed successfully",
            "main_order": main_order,
            "sl_order": sl_order,
            "tp_order": tp_order,
            "sl_price": sl_price,
            "tp_price": tp_price
        }
        
    except Exception as e:
        logger.error(f"Error executing manual trade: {e}")
        raise HTTPException(status_code=500, detail=f"Error executing trade: {str(e)}")

@router.get("/manual-trade/price/{symbol}")
def get_current_price(
    symbol: str,
    current_user = Depends(get_current_user)
):
    """Get current price for a symbol"""
    try:
        # This would need to be implemented to get current market price
        # For now, return a placeholder
        return {
            "symbol": symbol,
            "price": 0.0,  # Placeholder
            "message": "Price fetching not implemented yet"
        }
    except Exception as e:
        logger.error(f"Error getting current price: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting price: {str(e)}")






