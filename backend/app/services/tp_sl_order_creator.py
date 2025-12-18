"""
Reusable service for creating Take Profit and Stop Loss orders.
This centralizes the logic used by both automatic and manual TP/SL creation.
"""
import os
import logging
from typing import Optional, Dict, Tuple
from datetime import datetime
from sqlalchemy.orm import Session

from app.services.brokers.crypto_com_trade import trade_client
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum

logger = logging.getLogger(__name__)


def get_closing_side_from_entry(entry_side: str) -> str:
    """
    Get the correct closing side for TP/SL orders based on entry side.
    
    Args:
        entry_side: Original order side ("BUY" or "SELL")
        
    Returns:
        Closing side ("SELL" for BUY entry, "BUY" for SELL entry)
        
    Raises:
        ValueError: If entry_side is invalid
    """
    entry_side = entry_side.upper()
    if entry_side == "BUY":
        return "SELL"
    if entry_side == "SELL":
        return "BUY"
    raise ValueError(f"Invalid entry_side for TP/SL closing order: {entry_side}")


def create_take_profit_order(
    db: Session,
    symbol: str,
    side: str,  # "BUY" or "SELL" - the original order side
    tp_price: float,
    quantity: float,
    entry_price: float,
    parent_order_id: Optional[str] = None,
    oco_group_id: Optional[str] = None,
    is_margin: bool = False,
    leverage: Optional[float] = None,
    dry_run: bool = False,
    source: str = "auto"  # "auto" or "manual" to track the source
) -> Dict:
    """
    Create a Take Profit order using the same logic as automatic TP creation.
    
    Args:
        db: Database session
        symbol: Trading symbol (e.g., "ETH_USDT")
        side: Original order side ("BUY" or "SELL")
        tp_price: Take profit price
        quantity: Order quantity
        entry_price: Entry price (filled BUY price) - REQUIRED for ref_price
        parent_order_id: Parent order ID (optional, for linking)
        oco_group_id: OCO group ID (optional, for linking SL/TP)
        dry_run: Whether to run in dry-run mode
        
    Returns:
        Dict with 'order_id' (if successful) or 'error' (if failed)
    """
    # Determine correct side for TP order using helper function
    # After BUY: TP is SELL (sell at profit)
    # After SELL: TP is BUY (buy at profit)
    entry_side = side.upper()  # Ensure uppercase
    tp_side = get_closing_side_from_entry(entry_side)
    
    # CRITICAL: Verify TP price is valid for current market conditions (AUTO mode only).
    #
    # For manual/explicit SL/TP requests we must respect the exact requested percentage/price.
    # Auto flows can adjust slightly to avoid creating an immediately-invalid TP (e.g. TP <= market for SELL TP).
    if (not dry_run) and str(source).lower() != "manual":
        try:
            import requests
            ticker_url = "https://api.crypto.com/v2/public/get-ticker"
            ticker_params = {"instrument_name": symbol}
            ticker_response = requests.get(ticker_url, params=ticker_params, timeout=5)
            
            if ticker_response.status_code == 200:
                ticker_data = ticker_response.json()
                result_data = ticker_data.get("result", {})
                if "data" in result_data and len(result_data["data"]) > 0:
                    ticker_data_item = result_data["data"][0]
                    # For SELL orders, use ask price; for BUY orders, use bid price
                    current_price = float(ticker_data_item.get("a", 0) if tp_side == "SELL" else ticker_data_item.get("b", 0))
                    
                    if current_price > 0:
                        original_tp_price = tp_price
                        if tp_side == "SELL" and tp_price <= current_price:
                            # TP price is below or equal to current price - adjust it
                            # Add 0.5% margin above current price to ensure it's valid
                            tp_price = current_price * 1.005
                            logger.warning(
                                f"⚠️ TP price ({original_tp_price:.4f}) was below current market price ({current_price:.4f}). "
                                f"Adjusted to {tp_price:.4f} (0.5% above current price) to ensure order validity."
                            )
                        elif tp_side == "BUY" and tp_price >= current_price:
                            # TP price is above or equal to current price - adjust it
                            # Subtract 0.5% margin below current price to ensure it's valid
                            tp_price = current_price * 0.995
                            logger.warning(
                                f"⚠️ TP price ({original_tp_price:.4f}) was above current market price ({current_price:.4f}). "
                                f"Adjusted to {tp_price:.4f} (0.5% below current price) to ensure order validity."
                            )
        except Exception as price_check_err:
            logger.warning(f"Could not verify TP price against current market: {price_check_err}. Proceeding with calculated TP price.")
    
    # Round TP price if necessary (same logic as automatic creation)
    # Use precision matching crypto_com_trade.py place_limit_order logic:
    # - Prices >= 100: 2 decimal places (BTC, ETH, etc. - Crypto.com requirement)
    # - Prices >= 1: 6 decimal places  
    # - Prices < 1: 8 decimal places (for small coins like ALGO_USDT at $0.11)
    if entry_price >= 100:
        tp_price = round(tp_price, 2)
    elif entry_price >= 1:
        tp_price = round(tp_price, 6)
    else:
        # For small prices (< $1), use 8 decimal places to maintain precision
        tp_price = round(tp_price, 8)
    
    # For TAKE_PROFIT_LIMIT: both trigger_price and price must equal tp_price
    tp_trigger = tp_price
    tp_execution_price = tp_price
    
    logger.info(
        f"[{source.upper()}_TP] Creating TP order as TAKE_PROFIT_LIMIT: {symbol}, original_side={entry_side}, "
        f"tp_side={tp_side}, price={tp_execution_price}, trigger={tp_trigger}, "
        f"qty={quantity}, entry_price={entry_price}"
    )
    
    # Log closing side details before sending to exchange
    logger.info(
        f"[TP_ORDER][{source.upper()}] Closing TP side={tp_side}, entry_side={entry_side}, "
        f"ref_price={entry_price}, price={tp_execution_price}, instrument={symbol}"
    )
    
    tp_order_id = None
    tp_order_error = None
    
    try:
        # Log detailed payload before sending to exchange
        logger.info(
            f"[{source.upper()}_TP] PAYLOAD DETAILS before calling place_take_profit_order:\n"
            f"  symbol={symbol}\n"
            f"  side={tp_side} (original_side={entry_side}, closing_side={tp_side})\n"
            f"  price={tp_execution_price}\n"
            f"  qty={quantity}\n"
            f"  trigger_price={tp_trigger}\n"
            f"  entry_price={entry_price}\n"
            f"  dry_run={dry_run}\n"
            f"  source={source}"
        )
        
        # Create TAKE_PROFIT_LIMIT order with trigger_price and price both equal to tp_price
        tp_order = trade_client.place_take_profit_order(
            symbol=symbol,
            side=tp_side,  # SELL for BUY orders, BUY for SELL orders
            price=tp_execution_price,  # Execution price = tp_price
            qty=quantity,  # Same quantity as the filled order
            trigger_price=tp_trigger,  # Trigger price = tp_price (same as execution price)
            entry_price=entry_price,  # REQUIRED: Use entry price for ref_price
            is_margin=is_margin,
            leverage=leverage,
            dry_run=dry_run,
            source=source  # Propagate source to HTTP logging
        )
        
        if "error" not in tp_order:
            tp_order_id = tp_order.get("order_id") or tp_order.get("client_order_id")
            logger.info(
                f"✅ Created TP order (TAKE_PROFIT_LIMIT) for {symbol} @ {tp_price} "
                f"(trigger={tp_trigger}, price={tp_execution_price})"
            )
            
            # Save TP order to database with OCO fields (same as automatic creation)
            if tp_order_id and parent_order_id:
                try:
                    tp_db_order = ExchangeOrder(
                        exchange_order_id=str(tp_order_id),
                        symbol=symbol,
                        side=OrderSideEnum.SELL if entry_side == "BUY" else OrderSideEnum.BUY,
                        order_type="TAKE_PROFIT_LIMIT",
                        status=OrderStatusEnum.NEW,
                        price=tp_price,
                        quantity=quantity,
                        parent_order_id=parent_order_id,
                        oco_group_id=oco_group_id,
                        order_role="TAKE_PROFIT",
                        exchange_create_time=datetime.utcnow()
                    )
                    db.add(tp_db_order)
                    db.commit()
                    logger.info(f"✅ Saved TP order to DB with OCO group: {oco_group_id}")
                except Exception as db_err:
                    logger.warning(f"Failed to save TP order to database: {db_err}")
                    db.rollback()
            
            return {"order_id": tp_order_id, "error": None}
        else:
            tp_order_error = tp_order.get("error", "Unknown error")
            logger.error(f"❌ Failed to create TP order (TAKE_PROFIT_LIMIT) for {symbol} @ {tp_price}: {tp_order_error}")
            return {"order_id": None, "error": tp_order_error}
            
    except Exception as e:
        tp_order_error = str(e)
        logger.error(f"❌ Error creating TP order (TAKE_PROFIT_LIMIT) for {symbol}: {e}", exc_info=True)
        return {"order_id": None, "error": tp_order_error}


def create_stop_loss_order(
    db: Session,
    symbol: str,
    side: str,  # "BUY" or "SELL" - the original order side
    sl_price: float,
    quantity: float,
    entry_price: float,
    parent_order_id: Optional[str] = None,
    oco_group_id: Optional[str] = None,
    is_margin: bool = False,
    leverage: Optional[float] = None,
    dry_run: bool = False,
    source: str = "auto"  # "auto" or "manual" to track the source
) -> Dict:
    """
    Create a Stop Loss order using the same logic as automatic SL creation.
    
    Args:
        db: Database session
        symbol: Trading symbol (e.g., "ETH_USDT")
        side: Original order side ("BUY" or "SELL")
        sl_price: Stop loss price
        quantity: Order quantity
        entry_price: Entry price (filled BUY price) - REQUIRED for ref_price
        parent_order_id: Parent order ID (optional, for linking)
        oco_group_id: OCO group ID (optional, for linking SL/TP)
        dry_run: Whether to run in dry-run mode
        
    Returns:
        Dict with 'order_id' (if successful) or 'error' (if failed)
    """
    # Round SL price if necessary (same logic as automatic creation)
    # Use precision matching crypto_com_trade.py place_limit_order logic:
    # - Prices >= 100: 2 decimal places (BTC, ETH, etc. - Crypto.com requirement)
    # - Prices >= 1: 6 decimal places  
    # - Prices < 1: 8 decimal places (for small coins like ALGO_USDT at $0.11)
    if entry_price >= 100:
        sl_price = round(sl_price, 2)
    elif entry_price >= 1:
        sl_price = round(sl_price, 6)
    else:
        # For small prices (< $1), use 8 decimal places to maintain precision
        sl_price = round(sl_price, 8)
    
    # IMPORTANT: trigger_price must be equal to sl_price for STOP_LIMIT orders
    sl_trigger = sl_price  # trigger_price equals sl_price
    entry_side = side.upper()  # Ensure uppercase
    sl_side = get_closing_side_from_entry(entry_side)
    
    logger.info(
        f"[{source.upper()}_SL] Creating SL order: {symbol}, entry_side={entry_side}, closing_side={sl_side}, "
        f"sl_price={sl_price}, trigger={sl_trigger}, qty={quantity}, entry_price={entry_price}"
    )
    
    sl_order_id = None
    sl_order_error = None
    
    try:
        # Log detailed payload before sending to exchange
        logger.info(
            f"[{source.upper()}_SL] PAYLOAD DETAILS before calling place_stop_loss_order:\n"
            f"  symbol={symbol}\n"
            f"  side={sl_side} (original_side={entry_side}, closing_side={sl_side})\n"
            f"  price={sl_price}\n"
            f"  qty={quantity}\n"
            f"  trigger_price={sl_trigger}\n"
            f"  entry_price={entry_price}\n"
            f"  dry_run={dry_run}\n"
            f"  source={source}"
        )
        
        sl_order = trade_client.place_stop_loss_order(
            symbol=symbol,
            side=sl_side,
            price=sl_price,
            qty=quantity,
            trigger_price=sl_trigger,  # trigger_price = sl_price
            entry_price=entry_price,  # REQUIRED: Use entry price for ref_price
            is_margin=is_margin,
            leverage=leverage,
            dry_run=dry_run,
            source=source  # Propagate source to HTTP logging
        )
        
        if "error" not in sl_order:
            sl_order_id = sl_order.get("order_id") or sl_order.get("client_order_id")
            logger.info(f"✅ Created SL order for {symbol} @ {sl_price}")
            
            # Save SL order to database with OCO fields (same as automatic creation)
            if sl_order_id and parent_order_id:
                try:
                    sl_db_order = ExchangeOrder(
                        exchange_order_id=str(sl_order_id),
                        symbol=symbol,
                        side=OrderSideEnum.SELL if entry_side == "BUY" else OrderSideEnum.BUY,
                        order_type="STOP_LIMIT",  # Match API order type (STOP_LIMIT, not STOP_LOSS_LIMIT)
                        status=OrderStatusEnum.NEW,
                        price=sl_price,
                        quantity=quantity,
                        parent_order_id=parent_order_id,
                        oco_group_id=oco_group_id,
                        order_role="STOP_LOSS",
                        exchange_create_time=datetime.utcnow()
                    )
                    db.add(sl_db_order)
                    db.commit()
                    logger.info(f"✅ Saved SL order to DB with OCO group: {oco_group_id}")
                except Exception as db_err:
                    logger.warning(f"Failed to save SL order to database: {db_err}")
                    db.rollback()
            
            return {"order_id": sl_order_id, "error": None}
        else:
            sl_order_error = sl_order.get("error", "Unknown error")
            logger.error(f"❌ Failed to create SL order for {symbol} @ {sl_price}: {sl_order_error}")
            return {"order_id": None, "error": sl_order_error}
            
    except Exception as e:
        sl_order_error = str(e)
        logger.error(f"❌ Error creating SL order for {symbol}: {e}", exc_info=True)
        return {"order_id": None, "error": sl_order_error}

