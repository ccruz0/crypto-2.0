from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import get_db
from app.deps.auth import get_current_user
from app.services.brokers.crypto_com_trade import trade_client
from app.services.order_history_db import order_history_db
from app.utils.redact import redact_secrets
import logging
import os
import time

logger = logging.getLogger(__name__)
router = APIRouter()


# Enums for order validation
class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class PlaceOrderRequest(BaseModel):
    exchange: str
    symbol: str
    side: OrderSide
    type: OrderType
    qty: float
    price: Optional[float] = Field(default=None, gt=0)


class CancelOrderRequest(BaseModel):
    exchange: str
    order_id: Optional[str] = None
    client_oid: Optional[str] = None


class QuickOrderRequest(BaseModel):
    symbol: str
    side: str  # "BUY" or "SELL"
    price: float
    amount_usd: float
    use_margin: bool = False


def _ensure_exchange(exchange: str):
    """Validate that exchange is supported"""
    if exchange != "CRYPTO_COM":
        raise HTTPException(status_code=400, detail="Only CRYPTO_COM supported")


def _should_disable_auth() -> bool:
    """Check if auth should be disabled (for testing)"""
    return os.getenv("DISABLE_AUTH", "false").lower() == "true"


def _get_auth_dependency():
    """Get auth dependency or None based on DISABLE_AUTH env var"""
    if _should_disable_auth():
        return None
    return Depends(get_current_user)


@router.post("/orders/place")
def place_order(
    request: PlaceOrderRequest,
    current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Place order on specified exchange"""
    _ensure_exchange(request.exchange)
    
    from app.utils.live_trading import get_live_trading_status
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        live_trading = get_live_trading_status(db)
    finally:
        db.close()
    
    # Validate LIMIT orders have price
    if request.type == OrderType.LIMIT and request.price is None:
        raise HTTPException(status_code=400, detail="Price required for LIMIT orders")
    
    try:
        if request.type == OrderType.MARKET:
            result = trade_client.place_market_order(
                request.symbol,
                request.side.value,
                request.qty,
                dry_run=not live_trading
            )
        elif request.type == OrderType.LIMIT:
            result = trade_client.place_limit_order(
                request.symbol,
                request.side.value,
                request.price,
                request.qty,
                dry_run=not live_trading
            )
        else:
            raise HTTPException(status_code=400, detail="Invalid order type")
        
        logger.info(f"Order placed: {request.symbol} {request.side.value} {request.type.value} qty={request.qty}")
        logger.debug(f"Response: {redact_secrets(result)}")
        
        # Save order to history database if it was successfully placed
        try:
            # Check if the order result contains order_id (means it was placed)
            if "order_id" in result or "client_order_id" in result:
                order_data = {
                    "order_id": str(result.get("order_id", result.get("client_order_id", ""))),
                    "client_oid": str(result.get("client_order_id", result.get("client_oid", ""))),
                    "instrument_name": request.symbol,
                    "order_type": request.type.value,
                    "side": request.side.value,
                    "status": "OPEN",  # Initially open
                    "quantity": str(request.qty),
                    "price": str(request.price) if request.price else None,
                    "create_time": int(time.time() * 1000),
                    "update_time": int(time.time() * 1000),
                }
                # Add result fields if available
                if "avg_price" in result:
                    order_data["avg_price"] = str(result["avg_price"])
                if "cumulative_quantity" in result:
                    order_data["cumulative_quantity"] = str(result["cumulative_quantity"])
                
                # Save to database
                order_history_db.upsert_order(order_data)
                logger.info(f"Order saved to history database")
        except Exception as e:
            logger.error(f"Error saving order to history: {e}")
        
        return {
            "ok": True,
            "dry_run": not live_trading,
            "exchange": "CRYPTO_COM",
            "symbol": request.symbol,
            "side": request.side.value,
            "type": request.type.value,
            "result": result,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error placing order")
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/orders/cancel")
def cancel_order(
    request: CancelOrderRequest,
    current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Cancel order on specified exchange"""
    _ensure_exchange(request.exchange)
    
    if not request.order_id and not request.client_oid:
        raise HTTPException(status_code=400, detail="order_id or client_oid required")
    
    try:
        order_id = request.order_id or request.client_oid
        result = trade_client.cancel_order(order_id)
        
        logger.info(f"Order cancelled: {order_id}")
        logger.debug(f"Response: {redact_secrets(result)}")
        
        return {
            "ok": True,
            "exchange": "CRYPTO_COM",
            "canceled_id": order_id,
            "result": result
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error cancelling order")
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/orders/cancel-sl-tp/{symbol}")
def cancel_sl_tp_orders(
    symbol: str,
    db: Session = Depends(get_db),
    current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Cancel all SL/TP orders for a specific symbol
    
    This endpoint:
    1. First checks the database for SL/TP orders
    2. Then checks the exchange directly for open orders matching the symbol
    3. Cancels all SL/TP orders found (by order_role or order_type)
    """
    try:
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        
        # Normalize symbol (uppercase)
        symbol_upper = symbol.upper()
        
        canceled_orders = []
        failed_orders = []
        
        # Step 1: Check database for SL/TP orders
        from sqlalchemy import or_
        open_statuses = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]
        
        sl_tp_orders_db = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == symbol_upper,
            ExchangeOrder.status.in_(open_statuses),
            or_(
                ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
                ExchangeOrder.order_type.in_(["STOP_LIMIT", "TAKE_PROFIT_LIMIT", "STOP_LOSS", "TAKE_PROFIT"])
            )
        ).all()
        
        logger.info(f"Found {len(sl_tp_orders_db)} SL/TP orders in database for {symbol_upper}")
        
        # Step 2: Check exchange directly for open orders
        try:
            exchange_orders_result = trade_client.get_open_orders()
            exchange_orders = exchange_orders_result.get('data', [])
            
            # Filter for orders matching symbol and SL/TP types
            sl_tp_orders_exchange = []
            for order in exchange_orders:
                order_symbol = order.get('instrument_name', '').upper()
                order_type = order.get('type', '').upper()
                order_status = order.get('status', '').upper()
                
                if order_symbol == symbol_upper and order_status in ['NEW', 'ACTIVE', 'PARTIALLY_FILLED']:
                    # Check if it's an SL/TP order by type
                    if order_type in ['STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT']:
                        sl_tp_orders_exchange.append(order)
            
            logger.info(f"Found {len(sl_tp_orders_exchange)} SL/TP orders on exchange for {symbol_upper}")
        except Exception as e:
            logger.warning(f"Error fetching orders from exchange: {e}")
            sl_tp_orders_exchange = []
        
        # Combine orders from database and exchange (avoid duplicates)
        all_order_ids = set()
        orders_to_cancel = []
        
        # Add database orders
        for order in sl_tp_orders_db:
            order_id = order.exchange_order_id
            if order_id not in all_order_ids:
                all_order_ids.add(order_id)
                orders_to_cancel.append({
                    'order_id': order_id,
                    'order_role': order.order_role,
                    'order_type': order.order_type,
                    'symbol': order.symbol,
                    'side': order.side.value if hasattr(order.side, 'value') else str(order.side),
                    'source': 'database'
                })
        
        # Add exchange orders (if not already in database)
        for order in sl_tp_orders_exchange:
            order_id = order.get('order_id')
            if order_id and order_id not in all_order_ids:
                all_order_ids.add(order_id)
                orders_to_cancel.append({
                    'order_id': order_id,
                    'order_role': None,
                    'order_type': order.get('type'),
                    'symbol': order.get('instrument_name'),
                    'side': order.get('side'),
                    'source': 'exchange'
                })
        
        if not orders_to_cancel:
            return {
                "ok": True,
                "message": f"No open SL/TP orders found for {symbol_upper}",
                "canceled_count": 0,
                "canceled_orders": []
            }
        
        # Cancel all orders
        for order_info in orders_to_cancel:
            try:
                order_id = order_info['order_id']
                order_role = order_info['order_role'] or order_info['order_type'] or 'UNKNOWN'
                
                logger.info(f"Cancelling {order_role} order {order_id} for {symbol_upper} (from {order_info['source']})")
                
                result = trade_client.cancel_order(order_id)
                
                # Check if cancellation was successful
                if "error" in result:
                    failed_orders.append({
                        "order_id": order_id,
                        "order_role": order_role,
                        "error": result["error"]
                    })
                    logger.error(f"Failed to cancel {order_role} order {order_id}: {result['error']}")
                else:
                    # Update order status in database if it exists
                    db_order = db.query(ExchangeOrder).filter(
                        ExchangeOrder.exchange_order_id == order_id
                    ).first()
                    if db_order:
                        db_order.status = OrderStatusEnum.CANCELLED
                    
                    canceled_orders.append({
                        "order_id": order_id,
                        "order_role": order_role,
                        "symbol": order_info['symbol'],
                        "side": order_info['side'],
                        "source": order_info['source']
                    })
                    logger.info(f"✅ Successfully cancelled {order_role} order {order_id} for {symbol_upper}")
            except Exception as e:
                failed_orders.append({
                    "order_id": order_info['order_id'],
                    "order_role": order_info['order_role'] or order_info['order_type'],
                    "error": str(e)
                })
                logger.error(f"Error cancelling order {order_info['order_id']}: {e}", exc_info=True)
        
        # Commit database changes
        db.commit()
        
        return {
            "ok": True,
            "message": f"Cancelled {len(canceled_orders)} SL/TP order(s) for {symbol_upper}",
            "canceled_count": len(canceled_orders),
            "failed_count": len(failed_orders),
            "canceled_orders": canceled_orders,
            "failed_orders": failed_orders if failed_orders else None
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error cancelling SL/TP orders for {symbol}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/orders/create-sl-tp/{order_id}")
def create_sl_tp_for_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Create SL/TP orders for a filled order that doesn't have them
    
    This endpoint will:
    1. Find the order by order_id
    2. Verify it's FILLED and doesn't have SL/TP
    3. Create SL/TP orders using watchlist configuration or defaults
    """
    try:
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        from app.services.exchange_sync import exchange_sync_service
        
        # Find the order
        order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == order_id
        ).first()
        
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        
        # Verify order is FILLED
        if order.status != OrderStatusEnum.FILLED:
            raise HTTPException(
                status_code=400, 
                detail=f"Order {order_id} is not FILLED (status: {order.status.value}). SL/TP can only be created for FILLED orders."
            )
        
        # Check if SL/TP already exist
        existing_sl_tp = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == order_id,
            ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
        ).all()
        
        if existing_sl_tp:
            return {
                "ok": True,
                "message": f"Order {order_id} already has {len(existing_sl_tp)} SL/TP order(s)",
                "existing_sl_tp": [
                    {
                        "order_id": o.exchange_order_id,
                        "order_role": o.order_role,
                        "status": o.status.value
                    }
                    for o in existing_sl_tp
                ]
            }
        
        # Get order details
        symbol = order.symbol
        side = order.side.value if hasattr(order.side, 'value') else str(order.side)
        filled_price = float(order.avg_price) if order.avg_price else (float(order.price) if order.price else 0)
        filled_qty = float(order.cumulative_quantity) if order.cumulative_quantity else (float(order.quantity) if order.quantity else 0)
        
        if not filled_price or filled_qty <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"Order {order_id} has invalid price ({filled_price}) or quantity ({filled_qty})"
            )
        
        logger.info(f"Creating SL/TP for order {order_id}: {symbol} {side} price={filled_price} qty={filled_qty}")
        
        # Check if watchlist_item exists - if not, we'll use defaults
        from app.models.watchlist import WatchlistItem
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol
        ).first()
        
        if not watchlist_item:
            # Create a temporary watchlist_item or use defaults
            logger.warning(f"No watchlist_item found for {symbol}, will use default SL/TP percentages (3% conservative)")
            # We'll let the _create_sl_tp_for_filled_order function handle defaults
            # But we need to ensure the watchlist_item exists, so create a minimal one
            watchlist_item = WatchlistItem(
                symbol=symbol,
                exchange=order.exchange or "CRYPTO_COM",
                sl_tp_mode="conservative",
                is_deleted=False
            )
            db.add(watchlist_item)
            db.commit()
            db.refresh(watchlist_item)
            logger.info(f"Created temporary watchlist_item for {symbol}")
        
        # Check if original order was created with margin
        # Try to detect from watchlist_item trade_on_margin setting
        is_margin_order = watchlist_item.trade_on_margin if watchlist_item else False
        
        # Create SL/TP using the exchange_sync_service method
        # The method will use watchlist_item.trade_on_margin to determine if SL/TP should use margin
        try:
            exchange_sync_service._create_sl_tp_for_filled_order(
                db=db,
                symbol=symbol,
                side=side,
                filled_price=filled_price,
                filled_qty=filled_qty,
                order_id=order_id
            )
            
            # Verify SL/TP were created
            new_sl_tp = db.query(ExchangeOrder).filter(
                ExchangeOrder.parent_order_id == order_id,
                ExchangeOrder.order_role.in_(["STOP_LOSS", "TAKE_PROFIT"]),
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).all()
            
            return {
                "ok": True,
                "message": f"Created {len(new_sl_tp)} SL/TP order(s) for order {order_id}",
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "filled_price": filled_price,
                "filled_qty": filled_qty,
                "created_sl_tp": [
                    {
                        "order_id": o.exchange_order_id,
                        "order_role": o.order_role,
                        "status": o.status.value,
                        "price": float(o.price) if o.price else None,
                        "quantity": float(o.quantity) if o.quantity else None
                    }
                    for o in new_sl_tp
                ]
            }
        except Exception as create_err:
            logger.error(f"Error creating SL/TP for order {order_id}: {create_err}", exc_info=True)
            db.rollback()
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create SL/TP orders: {str(create_err)}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating SL/TP for order {order_id}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/open")
def get_open_orders(
    db: Session = Depends(get_db),
    # Temporarily disable authentication for local testing
    # current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Get all open/pending orders, sorted by creation time (newest first)"""
    import time as time_module
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import func, or_
    start_time = time_module.time()
    try:
        logger.info("get_open_orders called - fetching all open orders from database")
        
        if db is None:
            logger.warning("Database not available, returning empty orders")
            return {
                "ok": True,
                "exchange": "CRYPTO_COM",
                "orders": [],
                "count": 0,
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d")
            }
        
        # Get open/pending orders from ExchangeOrder table using correct enum values
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        
        # Open orders are: NEW, ACTIVE, PARTIALLY_FILLED
        # IMPORTANT: Show ALL open orders regardless of creation date
        # Open orders can be created days/weeks ago and still be active
        open_statuses = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]
        
        # RESTORED v4.0: Query ALL open orders (no date filter), sorted by creation time (newest first)
        # Use COALESCE to handle NULL exchange_create_time (fallback to created_at)
        # This ensures ALL open orders are returned, even if exchange_create_time is NULL
        orders_query = db.query(ExchangeOrder).filter(
            ExchangeOrder.status.in_(open_statuses)
        )
        
        # Sort by creation time (newest first) - use COALESCE to handle None values (v4.0 behavior)
        orders = orders_query.order_by(
            func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at).desc()
        ).limit(500).all()
        
        # Convert to dict format expected by frontend
        orders_list = []
        for order in orders:
            # Get creation time (prefer exchange_create_time, fallback to created_at)
            create_time = order.exchange_create_time or order.created_at
            create_timestamp_ms = int(create_time.timestamp() * 1000) if create_time else None
            
            # Format creation datetime for display - use ISO format so frontend can parse as UTC correctly
            if create_time:
                # Ensure datetime is timezone-aware (UTC)
                if create_time.tzinfo is None:
                    create_time = create_time.replace(tzinfo=timezone.utc)
                create_datetime_str = create_time.isoformat()
            else:
                create_datetime_str = "N/A"
            
            orders_list.append({
                "order_id": order.exchange_order_id,
                "client_oid": order.client_oid,
                "instrument_name": order.symbol,
                "order_type": order.order_type or "LIMIT",
                "side": order.side.value if hasattr(order.side, 'value') else str(order.side),
                "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
                "quantity": float(order.quantity) if order.quantity else 0.0,
                "price": float(order.price) if order.price else None,
                "avg_price": float(order.avg_price) if order.avg_price else None,
                "cumulative_quantity": float(order.cumulative_quantity) if order.cumulative_quantity else 0.0,
                "cumulative_value": float(order.cumulative_value) if order.cumulative_value else 0.0,
                "create_time": create_timestamp_ms,
                "create_datetime": create_datetime_str,  # Human-readable datetime
                "update_time": int(order.exchange_update_time.timestamp() * 1000) if order.exchange_update_time else int(order.updated_at.timestamp() * 1000),
                # Ensure orders are sorted by creation time (newest first) - already sorted in query
            })
        
        # Also check SQLite order_history_db for compatibility
        try:
            sqlite_orders = order_history_db.get_orders_by_status(['ACTIVE', 'NEW', 'PARTIALLY_FILLED'], limit=100)
            # Merge SQLite orders (avoid duplicates by order_id)
            existing_ids = {o.get('order_id') for o in orders_list}
            for sqlite_order in sqlite_orders:
                if sqlite_order.get('order_id') not in existing_ids:
                    orders_list.append(sqlite_order)
        except Exception as e:
            logger.debug(f"Error getting orders from SQLite: {e}")
        
        elapsed_time = time_module.time() - start_time
        logger.info(f"Retrieved {len(orders_list)} open orders (all time) in {elapsed_time:.3f}s")
        
        if elapsed_time > 0.3:
            logger.warning(f"⚠️ Open orders fetch took {elapsed_time:.3f}s - this is slow! Should be < 0.2 seconds.")
        
        return {
            "ok": True,
            "exchange": "CRYPTO_COM",
            "orders": orders_list,
            "count": len(orders_list),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "sorted_by": "creation_time_desc"
        }
    except Exception as e:
        logger.exception("Error getting open orders")
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/orders/verify-stale")
def verify_and_cleanup_stale_orders(
    symbol: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """
    Verify orders in database against exchange and mark stale ones as CANCELLED.
    
    Args:
        symbol: Optional symbol to check (e.g., "BTC_USDT"). If None, checks all symbols.
    
    Returns:
        Dict with verification results and cleanup status
    """
    try:
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
        from datetime import datetime, timezone
        
        # Get all active orders from database
        query = db.query(ExchangeOrder).filter(
            ExchangeOrder.status.in_([
                OrderStatusEnum.NEW, 
                OrderStatusEnum.ACTIVE, 
                OrderStatusEnum.PARTIALLY_FILLED
            ])
        )
        
        if symbol:
            query = query.filter(ExchangeOrder.symbol == symbol.upper())
        
        db_orders = query.all()
        logger.info(f"Found {len(db_orders)} active orders in database" + (f" for {symbol}" if symbol else ""))
        
        if not db_orders:
            return {
                "ok": True,
                "message": "No active orders found in database",
                "valid_orders": 0,
                "stale_orders": 0,
                "cleaned_up": 0
            }
        
        # Get actual open orders from exchange
        logger.info("Fetching open orders from exchange...")
        try:
            exchange_response = trade_client.get_open_orders()
            exchange_orders = exchange_response.get("data", [])
            
            # Also get trigger orders
            trigger_response = trade_client.get_trigger_orders()
            trigger_orders = trigger_response.get("data", []) if trigger_response else []
            
            # Combine all exchange orders
            all_exchange_orders = exchange_orders + trigger_orders
            exchange_order_ids = {order.get('order_id') for order in all_exchange_orders if order.get('order_id')}
            
            logger.info(f"Found {len(exchange_order_ids)} open orders on exchange")
            
        except Exception as e:
            logger.error(f"Error fetching orders from exchange: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Cannot verify orders - exchange API call failed: {str(e)}"
            )
        
        # Check each database order
        stale_orders = []
        valid_orders = []
        
        for db_order in db_orders:
            order_id = db_order.exchange_order_id
            if order_id in exchange_order_ids:
                valid_orders.append({
                    "order_id": order_id,
                    "symbol": db_order.symbol,
                    "side": db_order.side.value if hasattr(db_order.side, 'value') else str(db_order.side),
                    "status": db_order.status.value if hasattr(db_order.status, 'value') else str(db_order.status)
                })
            else:
                stale_orders.append({
                    "order_id": order_id,
                    "symbol": db_order.symbol,
                    "side": db_order.side.value if hasattr(db_order.side, 'value') else str(db_order.side),
                    "order_type": db_order.order_type,
                    "price": float(db_order.price) if db_order.price else None,
                    "quantity": float(db_order.quantity) if db_order.quantity else None,
                    "status": db_order.status.value if hasattr(db_order.status, 'value') else str(db_order.status)
                })
        
        # Mark stale orders as CANCELLED
        cleaned_count = 0
        if stale_orders:
            for order_info in stale_orders:
                order = db.query(ExchangeOrder).filter(
                    ExchangeOrder.exchange_order_id == order_info["order_id"]
                ).first()
                
                if order:
                    order.status = OrderStatusEnum.CANCELLED
                    order.exchange_update_time = datetime.now(timezone.utc)
                    cleaned_count += 1
                    logger.info(f"✅ Marked order {order_info['order_id']} ({order_info['symbol']}) as CANCELLED")
            
            db.commit()
            logger.info(f"Successfully marked {cleaned_count} orders as CANCELLED")
        
        return {
            "ok": True,
            "message": f"Verification complete. {len(valid_orders)} valid orders, {len(stale_orders)} stale orders found.",
            "valid_orders": len(valid_orders),
            "stale_orders": len(stale_orders),
            "cleaned_up": cleaned_count,
            "stale_order_details": stale_orders,
            "valid_order_details": valid_orders
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error verifying stale orders")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/history")
def get_order_history(
    limit: int = 100,  # Default to 100 orders per page
    offset: int = 0,   # Default to start from beginning
    db: Session = Depends(get_db),
    # Temporarily disable authentication for local testing
    # current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Get order history (executed orders) from database with pagination"""
    try:
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        
        if db is None:
            logger.warning("Database not available, returning empty history")
            return {
                "ok": True,
                "exchange": "CRYPTO_COM",
                "orders": [],
                "count": 0,
                "total": 0,
                "limit": limit,
                "offset": offset
            }
        
        # Limit maximum page size to prevent very large responses
        limit = min(limit, 500)  # Max 500 orders per request
        limit = max(limit, 1)    # Min 1 order per request
        offset = max(offset, 0)  # Ensure non-negative offset
        
        logger.info(f"get_order_history called - fetching from database (limit={limit}, offset={offset})")
        
        # RESTORED v4.0: Get executed orders: FILLED, CANCELLED, REJECTED, EXPIRED
        # Use COALESCE to handle NULL exchange_update_time (fallback to updated_at)
        # This ensures ALL executed orders are returned, even if exchange_update_time is NULL
        executed_statuses = [OrderStatusEnum.FILLED, OrderStatusEnum.CANCELLED, OrderStatusEnum.REJECTED, OrderStatusEnum.EXPIRED]
        from sqlalchemy import func
        query = db.query(ExchangeOrder).filter(ExchangeOrder.status.in_(executed_statuses)).order_by(
            func.coalesce(ExchangeOrder.exchange_update_time, ExchangeOrder.updated_at).desc()
        )
            
        # Optimize total count query - only do it for first page to avoid timeout
        # For subsequent pages, estimate based on results
        total_count = None
        all_orders = None
        
        try:
            if offset == 0 and limit <= 200:
                # Get exact count only for first page with reasonable limit
                # Use a timeout-safe approach: get count in a separate try/except
                try:
                    total_count = db.query(ExchangeOrder).filter(ExchangeOrder.status.in_(executed_statuses)).count()
                    logger.debug(f"Got exact count: {total_count}")
                except Exception as count_err:
                    logger.warning(f"Count query failed, will estimate: {count_err}")
                    total_count = None
                
                # Get orders for first page
                all_orders = query.offset(offset).limit(limit).all()
                
                # If count failed, estimate based on results
                if total_count is None:
                    # Check if there might be more results
                    check_more = query.offset(limit).limit(1).first()
                    if check_more:
                        # There are more results, estimate at least limit + 1
                        total_count = limit + 1
                    else:
                        # This might be all results, use limit as estimate
                        total_count = len(all_orders)
            else:
                # For subsequent pages, avoid count() to prevent timeout
                # Fetch limit+1 to check if there are more results
                all_orders = query.offset(offset).limit(limit + 1).all()
                
                if len(all_orders) > limit:
                    # There are more results, estimate total
                    all_orders = all_orders[:limit]  # Keep only limit results
                    total_count = offset + limit + 1  # Estimate: at least this many
                else:
                    # This might be the last page
                    total_count = offset + len(all_orders)
                    
        except Exception as query_err:
            # If query fails, try simple approach
            logger.warning(f"Query optimization failed, using simple query: {query_err}")
            all_orders = query.offset(offset).limit(limit).all()
            # Estimate total
            if offset == 0:
                total_count = len(all_orders) + (limit if len(all_orders) == limit else 0)
            else:
                total_count = offset + len(all_orders) + (limit if len(all_orders) == limit else 0)
        
        # Convert to API format
        orders = []
        for order in all_orders:
            # Get creation time (prefer exchange_create_time, fallback to created_at)
            create_time = order.exchange_create_time or order.created_at
            create_timestamp_ms = None
            create_datetime_str = "N/A"
            if create_time:
                try:
                    create_timestamp_ms = int(create_time.timestamp() * 1000)
                    # Ensure datetime is timezone-aware (UTC)
                    if create_time.tzinfo is None:
                        create_time = create_time.replace(tzinfo=timezone.utc)
                    create_datetime_str = create_time.isoformat()
                except (AttributeError, ValueError, OSError) as e:
                    logger.debug(f"Error formatting create_time for order {order.exchange_order_id}: {e}")
            
            # Get update time (prefer exchange_update_time, fallback to updated_at)
            update_time = order.exchange_update_time or order.updated_at
            update_timestamp_ms = None
            update_datetime_str = "N/A"
            if update_time:
                try:
                    update_timestamp_ms = int(update_time.timestamp() * 1000)
                    # Ensure datetime is timezone-aware (UTC)
                    if update_time.tzinfo is None:
                        update_time = update_time.replace(tzinfo=timezone.utc)
                    update_datetime_str = update_time.isoformat()
                except (AttributeError, ValueError, OSError) as e:
                    logger.debug(f"Error formatting update_time for order {order.exchange_order_id}: {e}")
            
            orders.append({
                "order_id": order.exchange_order_id,
                "client_oid": order.client_oid,
                "instrument_name": order.symbol,
                "side": order.side.value if hasattr(order.side, 'value') else str(order.side),
                "order_type": order.order_type or "LIMIT",
                "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
                "quantity": str(float(order.quantity)) if order.quantity else "0",
                "price": str(float(order.price)) if order.price else "0",
                "avg_price": str(float(order.avg_price)) if order.avg_price else None,
                "cumulative_quantity": str(float(order.cumulative_quantity)) if order.cumulative_quantity else "0",
                "cumulative_value": str(float(order.cumulative_value)) if order.cumulative_value else "0",
                "create_time": create_timestamp_ms,
                "update_time": update_timestamp_ms,
                "create_datetime": create_datetime_str,  # Human-readable datetime string
                "update_datetime": update_datetime_str,  # Human-readable datetime string
            })
        
        logger.info(f"Retrieved {len(orders)} orders from database (total: {total_count})")
        
        # Calculate has_more: if we got a full page and total_count suggests more, or if we got limit+1 (which was trimmed)
        has_more = False
        if total_count is not None:
            has_more = (offset + len(orders)) < total_count
        else:
            # If total_count is None, check if we got a full page (might indicate more)
            # But be conservative - only set has_more if we got exactly limit results
            has_more = len(orders) >= limit
        
        return {
            "ok": True,
            "exchange": "CRYPTO_COM",
            "orders": orders,
            "count": len(orders),
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": has_more
        }
    except Exception as e:
        logger.exception("Error getting order history")
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/orders/{order_id}")
def get_order_details(
    order_id: str,
    db: Session = Depends(get_db),
    # Temporarily disable authentication for local testing
    # current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Get detailed information about a specific order, including parent/child relationships"""
    try:
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        
        # Find the order
        order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == order_id
        ).first()
        
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found in database")
        
        # Build order details
        order_details = {
            "order_id": order.exchange_order_id,
            "symbol": order.symbol,
            "side": order.side.value if hasattr(order.side, 'value') else str(order.side),
            "order_type": order.order_type,
            "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
            "order_role": order.order_role,
            "price": float(order.price) if order.price else None,
            "quantity": float(order.quantity) if order.quantity else None,
            "avg_price": float(order.avg_price) if order.avg_price else None,
            "cumulative_quantity": float(order.cumulative_quantity) if order.cumulative_quantity else None,
            "cumulative_value": float(order.cumulative_value) if order.cumulative_value else None,
            "exchange_create_time": order.exchange_create_time.isoformat() if order.exchange_create_time else None,
            "exchange_update_time": order.exchange_update_time.isoformat() if order.exchange_update_time else None,
            "created_at": order.created_at.isoformat() if order.created_at else None,
            "updated_at": order.updated_at.isoformat() if order.updated_at else None,
            "parent_order_id": order.parent_order_id,
            "oco_group_id": order.oco_group_id,
            "trade_signal_id": order.trade_signal_id,
        }
        
        # Get parent order if exists
        if order.parent_order_id:
            parent = db.query(ExchangeOrder).filter(
                ExchangeOrder.exchange_order_id == order.parent_order_id
            ).first()
            if parent:
                order_details["parent_order"] = {
                    "order_id": parent.exchange_order_id,
                    "symbol": parent.symbol,
                    "side": parent.side.value if hasattr(parent.side, 'value') else str(parent.side),
                    "order_type": parent.order_type,
                    "status": parent.status.value if hasattr(parent.status, 'value') else str(parent.status),
                    "price": float(parent.price) if parent.price else None,
                    "avg_price": float(parent.avg_price) if parent.avg_price else None,
                    "quantity": float(parent.quantity) if parent.quantity else None,
                    "exchange_create_time": parent.exchange_create_time.isoformat() if parent.exchange_create_time else None,
                    "exchange_update_time": parent.exchange_update_time.isoformat() if parent.exchange_update_time else None,
                }
                order_details["origin"] = f"SL/TP order (role: {order.order_role or 'unknown'}) created for parent order {order.parent_order_id}"
            else:
                order_details["origin"] = f"SL/TP order (role: {order.order_role or 'unknown'}) but parent order {order.parent_order_id} not found"
        else:
            order_details["origin"] = "Manual or primary order (no parent_order_id)"
        
        # Get child orders (SL/TP orders created for this order)
        children = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == order_id
        ).all()
        
        if children:
            order_details["child_orders"] = []
            for child in children:
                order_details["child_orders"].append({
                    "order_id": child.exchange_order_id,
                    "symbol": child.symbol,
                    "side": child.side.value if hasattr(child.side, 'value') else str(child.side),
                    "order_type": child.order_type,
                    "order_role": child.order_role,
                    "status": child.status.value if hasattr(child.status, 'value') else str(child.status),
                    "price": float(child.price) if child.price else None,
                    "quantity": float(child.quantity) if child.quantity else None,
                })
        
        # Get related orders in same OCO group
        if order.oco_group_id:
            related = db.query(ExchangeOrder).filter(
                ExchangeOrder.oco_group_id == order.oco_group_id,
                ExchangeOrder.exchange_order_id != order_id
            ).all()
            
            if related:
                order_details["oco_related_orders"] = []
                for related_order in related:
                    order_details["oco_related_orders"].append({
                        "order_id": related_order.exchange_order_id,
                        "symbol": related_order.symbol,
                        "side": related_order.side.value if hasattr(related_order.side, 'value') else str(related_order.side),
                        "order_type": related_order.order_type,
                        "order_role": related_order.order_role,
                        "status": related_order.status.value if hasattr(related_order.status, 'value') else str(related_order.status),
                        "price": float(related_order.price) if related_order.price else None,
                    })
        
        return {
            "ok": True,
            "order": order_details
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting order details for {order_id}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/sync")
def sync_order_status(
    current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Sync order statuses by checking open orders and updating their status"""
    try:
        logger.info("Order sync started")
        
        # Get all open orders from Crypto.com
        result = trade_client.get_open_orders()
        open_orders = result.get('data', [])
        
        # Save/update all open orders in database
        synced_count = 0
        for order in open_orders:
            try:
                order_history_db.upsert_order(order)
                synced_count += 1
            except Exception as e:
                logger.error(f"Error syncing order {order.get('order_id')}: {e}")
        
        logger.info(f"Synced {synced_count} orders")
        
        return {
            "ok": True,
            "exchange": "CRYPTO_COM",
            "synced_count": synced_count,
            "total_open_orders": len(open_orders)
        }
    except Exception as e:
        logger.exception("Error syncing order status")
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/orders/sync-history")
def sync_order_history_manual(
    db: Session = Depends(get_db),
    current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Manually trigger sync of order history from Crypto.com exchange"""
    try:
        logger.info("Manual order history sync started")
        from app.services.exchange_sync import exchange_sync_service
        
        # Trigger order history sync
        exchange_sync_service.sync_order_history(db, page_size=200)
        
        logger.info("Manual order history sync completed")
        
        return {
            "ok": True,
            "message": "Order history sync completed",
            "exchange": "CRYPTO_COM"
        }
    except Exception as e:
        logger.exception("Error syncing order history")
        db.rollback()
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/orders/{order_id}/sync-from-exchange")
def sync_order_from_exchange(
    order_id: str,
    db: Session = Depends(get_db),
    current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Force sync a specific order from Crypto.com exchange to update its data (including timestamps)"""
    try:
        from app.models.exchange_order import ExchangeOrder
        from app.services.exchange_sync import exchange_sync_service
        from app.services.brokers.crypto_com_trade import trade_client
        
        if db is None:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Find the order in database
        order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == order_id
        ).first()
        
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found in database")
        
        logger.info(f"Syncing order {order_id} from Crypto.com exchange...")
        
        # Get order details from Crypto.com API
        try:
            # Try to get order from order history API
            order_history = trade_client.get_order_history(page_size=200, page=0)
            
            if not order_history or 'data' not in order_history:
                raise HTTPException(status_code=404, detail=f"Order {order_id} not found in Crypto.com order history")
            
            # Find the specific order in the history
            order_data = None
            for o in order_history.get('data', []):
                if str(o.get('order_id', '')) == order_id:
                    order_data = o
                    break
            
            if not order_data:
                raise HTTPException(status_code=404, detail=f"Order {order_id} not found in Crypto.com order history")
            
            # Parse timestamps from Crypto.com
            from datetime import datetime, timezone
            create_time = None
            update_time = None
            
            if order_data.get('create_time'):
                try:
                    create_time = datetime.fromtimestamp(order_data['create_time'] / 1000, tz=timezone.utc)
                except:
                    pass
            
            if order_data.get('update_time'):
                try:
                    update_time = datetime.fromtimestamp(order_data['update_time'] / 1000, tz=timezone.utc)
                except:
                    pass
            
            # Update order with data from Crypto.com
            if update_time:
                order.exchange_update_time = update_time
                logger.info(f"✅ Updated exchange_update_time for order {order_id} to {update_time} from Crypto.com")
            elif create_time:
                order.exchange_update_time = create_time
                logger.info(f"✅ Updated exchange_update_time for order {order_id} to {create_time} (from create_time) from Crypto.com")
            
            if create_time:
                order.exchange_create_time = create_time
                logger.info(f"✅ Updated exchange_create_time for order {order_id} to {create_time} from Crypto.com")
            
            # Update other fields from Crypto.com
            if order_data.get('price'):
                order.price = float(order_data.get('price', 0))
            if order_data.get('avg_price'):
                order.avg_price = float(order_data.get('avg_price', 0))
            if order_data.get('quantity'):
                order.quantity = float(order_data.get('quantity', 0))
            if order_data.get('cumulative_quantity'):
                order.cumulative_quantity = float(order_data.get('cumulative_quantity', 0))
            if order_data.get('cumulative_value'):
                order.cumulative_value = float(order_data.get('cumulative_value', 0))
            
            order.updated_at = datetime.now(timezone.utc)
            
            db.commit()
            
            logger.info(f"✅ Successfully synced order {order_id} from Crypto.com")
            
            return {
                "ok": True,
                "message": f"Order {order_id} synced from Crypto.com successfully",
                "order": {
                    "order_id": order_id,
                    "symbol": order.symbol,
                    "exchange_update_time": order.exchange_update_time.isoformat() if order.exchange_update_time else None,
                    "exchange_create_time": order.exchange_create_time.isoformat() if order.exchange_create_time else None,
                }
            }
            
        except HTTPException:
            raise
        except Exception as api_err:
            logger.exception(f"Error getting order {order_id} from Crypto.com API")
            raise HTTPException(status_code=502, detail=f"Error syncing from Crypto.com: {str(api_err)}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error syncing order {order_id} from exchange")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/orders/{order_id}")
def delete_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Delete an order from the database by order_id"""
    try:
        from app.models.exchange_order import ExchangeOrder
        
        if db is None:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Find the order
        order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == order_id
        ).first()
        
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        
        # Get order details for logging
        symbol = order.symbol
        side = order.side.value if hasattr(order.side, 'value') else str(order.side)
        status = order.status.value if hasattr(order.status, 'value') else str(order.status)
        
        # Delete the order
        db.delete(order)
        db.commit()
        
        logger.info(f"Deleted order {order_id}: {symbol} {side} {status}")
        
        return {
            "ok": True,
            "message": f"Order {order_id} deleted successfully",
            "deleted_order": {
                "order_id": order_id,
                "symbol": symbol,
                "side": side,
                "status": status
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting order {order_id}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/orders/{order_id}/update-time")
def update_order_time(
    order_id: str,
    update_time: Optional[str] = Body(None, description="New update time in ISO format (e.g., '2025-12-15T11:32:33+08:00')"),
    create_time: Optional[str] = Body(None, description="New create time in ISO format"),
    db: Session = Depends(get_db),
    current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Update the timestamp(s) of an order"""
    try:
        from app.models.exchange_order import ExchangeOrder
        from datetime import datetime
        
        if db is None:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Find the order
        order = db.query(ExchangeOrder).filter(
            ExchangeOrder.exchange_order_id == order_id
        ).first()
        
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        
        updated_fields = []
        
        # Update exchange_update_time if provided
        if update_time:
            try:
                # Parse ISO format datetime string
                if update_time.endswith('GMT+8') or update_time.endswith('GMT-8'):
                    # Handle format like "12/15/2025, 11:32:33 AM GMT+8"
                    try:
                        from dateutil import parser
                        dt = parser.parse(update_time)
                    except ImportError:
                        # Fallback: parse manually
                        # Format: "12/15/2025, 11:32:33 AM GMT+8"
                        import re
                        match = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4}),\s+(\d{1,2}):(\d{2}):(\d{2})\s+(AM|PM)\s+GMT([+-]\d+)', update_time)
                        if match:
                            month, day, year, hour, minute, second, am_pm, tz_offset = match.groups()
                            hour = int(hour)
                            if am_pm == 'PM' and hour != 12:
                                hour += 12
                            elif am_pm == 'AM' and hour == 12:
                                hour = 0
                            dt = datetime(int(year), int(month), int(day), hour, int(minute), int(second), tzinfo=timezone.utc)
                        else:
                            raise ValueError(f"Could not parse date format: {update_time}")
                else:
                    # Try ISO format
                    dt = datetime.fromisoformat(update_time.replace('Z', '+00:00'))
                
                # Ensure timezone aware
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                
                order.exchange_update_time = dt
                updated_fields.append("exchange_update_time")
                logger.info(f"Updated exchange_update_time for order {order_id} to {dt}")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid update_time format: {str(e)}")
        
        # Update exchange_create_time if provided
        if create_time:
            try:
                # Parse ISO format datetime string
                if create_time.endswith('GMT+8') or create_time.endswith('GMT-8'):
                    # Handle format like "12/15/2025, 11:32:33 AM GMT+8"
                    try:
                        from dateutil import parser
                        dt = parser.parse(create_time)
                    except ImportError:
                        # Fallback: parse manually
                        import re
                        match = re.match(r'(\d{1,2})/(\d{1,2})/(\d{4}),\s+(\d{1,2}):(\d{2}):(\d{2})\s+(AM|PM)\s+GMT([+-]\d+)', create_time)
                        if match:
                            month, day, year, hour, minute, second, am_pm, tz_offset = match.groups()
                            hour = int(hour)
                            if am_pm == 'PM' and hour != 12:
                                hour += 12
                            elif am_pm == 'AM' and hour == 12:
                                hour = 0
                            dt = datetime(int(year), int(month), int(day), hour, int(minute), int(second), tzinfo=timezone.utc)
                        else:
                            raise ValueError(f"Could not parse date format: {create_time}")
                else:
                    # Try ISO format
                    dt = datetime.fromisoformat(create_time.replace('Z', '+00:00'))
                
                # Ensure timezone aware
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                
                order.exchange_create_time = dt
                updated_fields.append("exchange_create_time")
                logger.info(f"Updated exchange_create_time for order {order_id} to {dt}")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Invalid create_time format: {str(e)}")
        
        if not updated_fields:
            raise HTTPException(status_code=400, detail="At least one of update_time or create_time must be provided")
        
        # Update updated_at timestamp
        order.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        
        logger.info(f"Updated timestamps for order {order_id}: {', '.join(updated_fields)}")
        
        return {
            "ok": True,
            "message": f"Order {order_id} timestamps updated successfully",
            "updated_fields": updated_fields,
            "order": {
                "order_id": order_id,
                "symbol": order.symbol,
                "exchange_update_time": order.exchange_update_time.isoformat() if order.exchange_update_time else None,
                "exchange_create_time": order.exchange_create_time.isoformat() if order.exchange_create_time else None,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating order time for {order_id}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/orders/by-criteria")
def delete_order_by_criteria(
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    price: Optional[float] = None,
    quantity: Optional[float] = None,
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Delete orders matching specific criteria (symbol, side, price, quantity, date)"""
    try:
        from app.models.exchange_order import ExchangeOrder
        from sqlalchemy import and_
        from datetime import datetime
        
        if db is None:
            raise HTTPException(status_code=503, detail="Database not available")
        
        # Build query with filters
        query = db.query(ExchangeOrder)
        filters = []
        
        if symbol:
            filters.append(ExchangeOrder.symbol == symbol.upper())
        if side:
            filters.append(ExchangeOrder.side == side.upper())
        if price is not None:
            # Match price within 0.01% tolerance
            filters.append(ExchangeOrder.price.between(price * 0.9999, price * 1.0001))
        if quantity is not None:
            # Match quantity within 0.01% tolerance
            filters.append(ExchangeOrder.quantity.between(quantity * 0.9999, quantity * 1.0001))
        if date:
            try:
                # Parse date string (format: "12/15/2025, 11:32:33 AM GMT+8")
                date_obj = datetime.strptime(date, "%m/%d/%Y, %I:%M:%S %p GMT%z")
                # Match orders on the same day
                filters.append(
                    func.date(ExchangeOrder.exchange_update_time) == date_obj.date()
                )
            except:
                logger.warning(f"Could not parse date: {date}")
        
        if not filters:
            raise HTTPException(status_code=400, detail="At least one criteria must be provided")
        
        # Find matching orders
        orders = query.filter(and_(*filters)).all()
        
        if not orders:
            return {
                "ok": True,
                "message": "No orders found matching criteria",
                "deleted_count": 0,
                "deleted_orders": []
            }
        
        # Get order details before deletion
        deleted_orders = []
        for order in orders:
            deleted_orders.append({
                "order_id": order.exchange_order_id,
                "symbol": order.symbol,
                "side": order.side.value if hasattr(order.side, 'value') else str(order.side),
                "status": order.status.value if hasattr(order.status, 'value') else str(order.status),
                "price": float(order.price) if order.price else None,
                "quantity": float(order.quantity) if order.quantity else None
            })
        
        # Delete all matching orders
        for order in orders:
            db.delete(order)
        
        db.commit()
        
        logger.info(f"Deleted {len(orders)} order(s) matching criteria: symbol={symbol}, side={side}, price={price}, quantity={quantity}, date={date}")
        
        return {
            "ok": True,
            "message": f"Deleted {len(orders)} order(s) matching criteria",
            "deleted_count": len(orders),
            "deleted_orders": deleted_orders
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting orders by criteria")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/orders/quick")
def quick_order(
    request: QuickOrderRequest
    # Temporarily disable authentication for local testing
    # current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Create a quick LIMIT order from dashboard with automatic SL/TP when filled"""
    from app.database import SessionLocal
    from app.models.watchlist import WatchlistItem
    
    # Validate inputs
    if request.side.upper() not in ["BUY", "SELL"]:
        raise HTTPException(status_code=400, detail="side must be 'BUY' or 'SELL'")
    
    if request.price <= 0:
        raise HTTPException(status_code=400, detail="price must be greater than 0")
    
    if request.amount_usd <= 0:
        raise HTTPException(status_code=400, detail="amount_usd must be greater than 0")
    
    # Log the order details
    logger.info(f"Creating {request.side} MARKET order for {request.symbol}: amount_usd={request.amount_usd}")
    
    from app.utils.live_trading import get_live_trading_status
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        live_trading = get_live_trading_status(db)
    finally:
        db.close()
    
    # Force dry_run if LIVE_TRADING is not explicitly enabled
    # This prevents accidental real trades
    dry_run_mode = not live_trading
    
    try:
        # Place MARKET order
        # For BUY: use notional (amount in USD)
        # For SELL: calculate qty from amount_usd / price
        side_upper = request.side.upper()
        
        # CRITICAL: Determine correct leverage for this symbol to prevent error 306
        from app.services.margin_decision_helper import decide_trading_mode, log_margin_decision, DEFAULT_CONFIGURED_LEVERAGE
        
        trading_decision = decide_trading_mode(
            symbol=request.symbol,
            configured_leverage=DEFAULT_CONFIGURED_LEVERAGE,
            user_wants_margin=request.use_margin
        )
        
        # Log the decision for debugging
        log_margin_decision(request.symbol, trading_decision, DEFAULT_CONFIGURED_LEVERAGE)
        
        # Use the decision's leverage (will be None for SPOT, or correct leverage for MARGIN)
        final_is_margin = trading_decision.use_margin
        final_leverage = trading_decision.leverage
        
        if side_upper == "BUY":
            # BUY market order: use notional (amount in USD)
            result = trade_client.place_market_order(
                symbol=request.symbol,
                side=side_upper,
                notional=request.amount_usd,
                is_margin=final_is_margin,
                leverage=final_leverage,  # Use dynamic leverage (e.g., 5x for ADA_USDT, 10x for BTC_USDT)
                dry_run=dry_run_mode
            )
            # Calculate estimated quantity for logging (actual qty will be determined by market price)
            estimated_qty = request.amount_usd / request.price
        else:  # SELL
            # SELL market order: calculate quantity from amount_usd / price
            qty = request.amount_usd / request.price
            
            # Round quantity based on price - use reasonable precision
            if request.price >= 100:
                qty = round(qty, 4)
            elif request.price >= 1:
                qty = round(qty, 6)
            else:
                qty = round(qty, 8)
            
            # Ensure minimum quantity
            if qty <= 0:
                raise HTTPException(status_code=400, detail="Calculated quantity is too small")
            
            result = trade_client.place_market_order(
                symbol=request.symbol,
                side=side_upper,
                qty=qty,
                is_margin=final_is_margin,  # Use decision from above
                leverage=final_leverage,  # Use dynamic leverage from decision
                dry_run=dry_run_mode
            )
            estimated_qty = qty
        
        # Check for errors in the result
        if "error" in result:
            error_msg = result["error"]
            
            # Log the full error for debugging
            logger.error(f"Order creation failed: {error_msg}")
            
            # Always include the exact API error message in the response
            # The error_msg already contains formatted message from crypto_com_trade.py
            # which includes code and message from Crypto.com API
            raise HTTPException(
                status_code=400,
                detail=error_msg  # Show exact error message from API
            )
        
        # Get order_id from result
        order_id = result.get("order_id") or result.get("client_order_id")
        if not order_id:
            raise HTTPException(status_code=500, detail="Order placed but no order_id returned")
        
        # Send Telegram notification when order is created
        try:
            from app.services.telegram_notifier import telegram_notifier
            # For market orders, price is unknown at creation (will be filled at market price)
            # For BUY: pass amount_usd as quantity (for display purposes in Telegram)
            # For SELL: pass estimated_qty
            telegram_qty = request.amount_usd if side_upper == "BUY" else estimated_qty
            telegram_notifier.send_order_created(
                symbol=request.symbol,
                side=request.side.upper(),
                price=0,  # Market price will be determined at execution
                quantity=telegram_qty,
                order_id=str(order_id),
                margin=final_is_margin,  # Use decision from above
                leverage=final_leverage,  # Use dynamic leverage from decision
                dry_run=dry_run_mode,
                order_type="MARKET"  # Specify MARKET order type
            )
            logger.info(f"Sent Telegram notification for created order: {order_id}")
        except Exception as telegram_err:
            logger.warning(f"Failed to send Telegram notification for order creation: {telegram_err}")
        
        # Save order to database
        try:
            # For MARKET orders, check if they were immediately filled
            # Crypto.com may return status "FILLED" or "CANCELLED" immediately for market orders
            # Check the result status and cumulative_quantity to determine actual status
            result_status = result.get("status", "").upper()
            cumulative_qty = float(result.get("cumulative_quantity", 0) or 0)
            
            # Determine actual status
            if result_status in ["FILLED", "filled"]:
                db_status = "FILLED"
            elif result_status in ["CANCELLED", "CANCELED", "cancelled", "canceled"]:
                # If cancelled but has cumulative_quantity, it was actually filled before being cancelled
                if cumulative_qty > 0:
                    db_status = "FILLED"  # Was filled before being cancelled
                else:
                    db_status = "CANCELLED"
            else:
                db_status = "OPEN"  # Default for unknown status
            
            order_data = {
                "order_id": str(order_id),
                "client_oid": str(result.get("client_order_id", order_id)),
                "instrument_name": request.symbol,
                "order_type": "MARKET",
                "side": request.side.upper(),
                "status": db_status,  # Use determined status
                "quantity": str(estimated_qty),
                "price": str(result.get("avg_price", "0")) if result.get("avg_price") else "0",  # Use avg_price if available
                "avg_price": str(result.get("avg_price")) if result.get("avg_price") else None,
                "cumulative_quantity": str(result.get("cumulative_quantity")) if result.get("cumulative_quantity") else str(estimated_qty),
                "cumulative_value": str(result.get("cumulative_value")) if result.get("cumulative_value") else None,
                "create_time": int(time.time() * 1000),
                "update_time": int(time.time() * 1000),
            }
            order_history_db.upsert_order(order_data)
            logger.info(f"Quick MARKET order saved to database: {order_id} with status: {db_status}")
        except Exception as e:
            logger.error(f"Error saving order to database: {e}")
        
        # Get coin configuration from watchlist for SL/TP parameters (if needed later)
        # The watchlist item is not required for quick orders
        # Post-trade SL/TP will be handled by exchange_sync when it detects FILLED status
        
        logger.info(f"Quick MARKET order placed: {request.symbol} {request.side.upper()} {estimated_qty} (amount_usd={request.amount_usd})")
        
        return {
            "ok": True,
            "dry_run": dry_run_mode,
            "exchange": "CRYPTO_COM",
            "symbol": request.symbol,
            "side": request.side.upper(),
            "type": "MARKET",  # Changed from LIMIT to MARKET
            "order_id": order_id,
            "qty": estimated_qty,
            "price": 0,  # Market orders don't have price at creation
            "amount_usd": request.amount_usd,
            "result": result
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error placing quick order")
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/orders/tp-sl-values")
def get_tp_sl_order_values(
    db: Session = Depends(get_db),
    # Temporarily disable authentication for local testing
    # current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Get total USD values of TP/SL orders grouped by base currency"""
    try:
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        from sqlalchemy import or_
        from collections import defaultdict
        
        if db is None:
            logger.warning("Database not available, returning empty TP/SL values")
            return {}
        
        # Get open TP/SL orders
        open_statuses = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]
        
        # TP orders: TAKE_PROFIT, TAKE_PROFIT_LIMIT, or order_role = TAKE_PROFIT
        tp_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.status.in_(open_statuses),
            or_(
                ExchangeOrder.order_type.in_(['TAKE_PROFIT', 'TAKE_PROFIT_LIMIT']),
                ExchangeOrder.order_role == 'TAKE_PROFIT'
            )
        ).all()
        
        # SL orders: STOP_LOSS, STOP_LOSS_LIMIT, STOP_LIMIT, or order_role = STOP_LOSS
        sl_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.status.in_(open_statuses),
            or_(
                ExchangeOrder.order_type.in_(['STOP_LOSS', 'STOP_LOSS_LIMIT', 'STOP_LIMIT']),
                ExchangeOrder.order_role == 'STOP_LOSS'
            )
        ).all()
        
        # Group by base currency and calculate total USD value
        tp_values = defaultdict(float)
        sl_values = defaultdict(float)
        
        # Process TP orders
        for order in tp_orders:
            if order.symbol and order.price and order.quantity:
                # Extract base currency from symbol (e.g., "BTC_USDT" -> "BTC")
                base_currency = order.symbol.split('_')[0].upper() if '_' in order.symbol else order.symbol.upper()
                # Calculate USD value: quantity * price
                try:
                    qty = float(order.quantity)
                    price = float(order.price)
                    usd_value = qty * price
                    tp_values[base_currency] += usd_value
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error calculating TP value for {order.symbol}: {e}")
        
        # Process SL orders
        for order in sl_orders:
            if order.symbol and order.price and order.quantity:
                # Extract base currency from symbol
                base_currency = order.symbol.split('_')[0].upper() if '_' in order.symbol else order.symbol.upper()
                # Calculate USD value: quantity * price
                try:
                    qty = float(order.quantity)
                    price = float(order.price)
                    usd_value = qty * price
                    sl_values[base_currency] += usd_value
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error calculating SL value for {order.symbol}: {e}")
        
        # Combine into result format
        result = {}
        all_currencies = set(list(tp_values.keys()) + list(sl_values.keys()))
        
        for currency in all_currencies:
            result[currency] = {
                'tp_value_usd': round(tp_values.get(currency, 0.0), 2),
                'sl_value_usd': round(sl_values.get(currency, 0.0), 2)
            }
        
        logger.info(f"Calculated TP/SL values for {len(result)} currencies")
        return result
        
    except Exception as e:
        logger.exception("Error calculating TP/SL order values")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/orders/create-sl-tp-for-last-order")
def create_sl_tp_for_last_order(
    symbol: str,
    db: Session = Depends(get_db),
    # Temporarily disable authentication for local testing
    # current_user = None if _should_disable_auth() else Depends(get_current_user)
):
    """Create SL/TP orders for the last filled order of a symbol that doesn't have SL/TP"""
    try:
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
        from app.services.exchange_sync import exchange_sync_service
        
        logger.info(f"Creating SL/TP for last order of {symbol}")
        
        # Find the last filled BUY order for the symbol
        last_order = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == symbol,
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.order_type.in_(["MARKET", "LIMIT"])
        ).order_by(ExchangeOrder.exchange_update_time.desc()).first()
        
        if not last_order:
            raise HTTPException(
                status_code=404,
                detail=f"No filled BUY orders found for {symbol}"
            )
        
        # Check if this order already has SL/TP orders
        existing_sl_tp = db.query(ExchangeOrder).filter(
            ExchangeOrder.parent_order_id == last_order.exchange_order_id,
            ExchangeOrder.order_type.in_(["STOP_LIMIT", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"]),
            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
        ).all()
        
        if existing_sl_tp:
            return {
                "ok": True,
                "message": f"Order {last_order.exchange_order_id} already has {len(existing_sl_tp)} SL/TP order(s)",
                "order_id": last_order.exchange_order_id,
                "existing_sl_tp": [
                    {
                        "order_id": o.exchange_order_id,
                        "order_type": o.order_type,
                        "status": o.status.value
                    } for o in existing_sl_tp
                ]
            }
        
        # Get filled price and quantity
        filled_price = float(last_order.avg_price) if last_order.avg_price else float(last_order.price) if last_order.price else None
        filled_qty = float(last_order.cumulative_quantity) if last_order.cumulative_quantity else float(last_order.quantity) if last_order.quantity else None
        
        if not filled_price or not filled_qty:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot create SL/TP: invalid price ({filled_price}) or quantity ({filled_qty})"
            )
        
        logger.info(f"Creating SL/TP for order {last_order.exchange_order_id}: price={filled_price}, qty={filled_qty}")
        
        # Use the same logic as exchange_sync._create_sl_tp_for_filled_order
        exchange_sync_service._create_sl_tp_for_filled_order(
            db=db,
            symbol=symbol,
            side=last_order.side.value,  # "BUY"
            filled_price=filled_price,
            filled_qty=filled_qty,
            order_id=last_order.exchange_order_id
        )
        
        logger.info(f"✅ SL/TP orders created successfully for order {last_order.exchange_order_id}")
        
        return {
            "ok": True,
            "message": f"SL/TP orders created successfully for order {last_order.exchange_order_id}",
            "order_id": last_order.exchange_order_id,
            "symbol": symbol,
            "filled_price": filled_price,
            "filled_qty": filled_qty
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating SL/TP for last order of {symbol}")
        raise HTTPException(status_code=502, detail=str(e))


