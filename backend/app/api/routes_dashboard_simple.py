from fastapi import APIRouter, HTTPException, Depends, Body
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional
import logging

from app.database import get_db
from app.models.watchlist import WatchlistItem
from app.schemas.watchlist import WatchlistItemUpdate
from app.deps.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)):
    """Get all watchlist items"""
    try:
        items = db.query(WatchlistItem).all()
        return [
            {
                "id": item.id,
                "symbol": item.symbol,
                "exchange": item.exchange,
                "alert_enabled": item.alert_enabled,
                "trade_enabled": item.trade_enabled,
                "trade_amount_usd": item.trade_amount_usd,
                "trade_on_margin": item.trade_on_margin,
                "sl_tp_mode": item.sl_tp_mode,
                "sl_percentage": item.sl_percentage,
                "tp_percentage": item.tp_percentage,
                "sl_price": item.sl_price,
                "tp_price": item.tp_price,
                "buy_target": item.buy_target,
                "take_profit": item.take_profit,
                "stop_loss": item.stop_loss,
                "price": item.price,
                "rsi": item.rsi,
                "atr": item.atr,
                "ma50": item.ma50,
                "ma200": item.ma200,
                "ema10": item.ema10,
                "res_up": item.res_up,
                "res_down": item.res_down
            }
            for item in items
        ]
    except Exception as e:
        logger.error(f"Error in dashboard endpoint: {e}")
        return []

@router.post("/dashboard")
def add_to_dashboard(
    item: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Add new watchlist item"""
    try:
        symbol = item.get("symbol", "").upper()
        if not symbol:
            raise HTTPException(status_code=400, detail="symbol is required")
        
        # Check if item already exists
        existing = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol).first()
        if existing:
            raise HTTPException(status_code=400, detail=f"Watchlist item for {symbol} already exists")
        
        # Create new watchlist item
        watchlist_item = WatchlistItem(
            symbol=symbol,
            exchange=item.get("exchange", "CRYPTO_COM"),
            alert_enabled=item.get("alert_enabled", False),
            trade_enabled=item.get("trade_enabled", False),
            trade_amount_usd=item.get("trade_amount_usd"),
            trade_on_margin=item.get("trade_on_margin", False),
            sl_tp_mode=item.get("sl_tp_mode", "conservative"),
            sl_percentage=item.get("sl_percentage"),
            tp_percentage=item.get("tp_percentage"),
            sl_price=item.get("sl_price"),  # IMPORTANT: Save sl_price from dashboard
            tp_price=item.get("tp_price"),  # IMPORTANT: Save tp_price from dashboard
            buy_target=item.get("buy_target"),
            take_profit=item.get("take_profit"),
            stop_loss=item.get("stop_loss")
        )
        
        db.add(watchlist_item)
        db.commit()
        db.refresh(watchlist_item)
        
        logger.info(f"Created watchlist item for {symbol}")
        
        return {
            "id": watchlist_item.id,
            "symbol": watchlist_item.symbol,
            "exchange": watchlist_item.exchange,
            "alert_enabled": watchlist_item.alert_enabled,
            "trade_enabled": watchlist_item.trade_enabled,
            "trade_amount_usd": watchlist_item.trade_amount_usd,
            "sl_price": watchlist_item.sl_price,
            "tp_price": watchlist_item.tp_price
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating watchlist item: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/dashboard/{item_id}")
def update_dashboard_item(
    item_id: int,
    item: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Update watchlist item - IMPORTANT: This saves sl_price and tp_price from dashboard"""
    try:
        watchlist_item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
        
        if not watchlist_item:
            raise HTTPException(status_code=404, detail=f"Watchlist item {item_id} not found")
        
        # Update all provided fields
        if "symbol" in item:
            watchlist_item.symbol = item["symbol"].upper()
        if "exchange" in item:
            watchlist_item.exchange = item["exchange"]
        if "alert_enabled" in item:
            watchlist_item.alert_enabled = item["alert_enabled"]
        if "trade_enabled" in item:
            watchlist_item.trade_enabled = item["trade_enabled"]
        if "trade_amount_usd" in item:
            watchlist_item.trade_amount_usd = item["trade_amount_usd"]
        if "trade_on_margin" in item:
            watchlist_item.trade_on_margin = item["trade_on_margin"]
        if "sl_tp_mode" in item:
            watchlist_item.sl_tp_mode = item["sl_tp_mode"]
        if "min_price_change_pct" in item:
            value = item["min_price_change_pct"]
            # Explicitly handle empty string, None, or 0 as None
            if value == "" or value is None:
                watchlist_item.min_price_change_pct = None
            else:
                watchlist_item.min_price_change_pct = float(value) if value is not None else None
        if "sl_percentage" in item:
            value = item["sl_percentage"]
            # Explicitly handle empty string, None, or 0 as None
            if value == "" or value is None:
                watchlist_item.sl_percentage = None
            else:
                watchlist_item.sl_percentage = float(value) if value is not None else None
        if "tp_percentage" in item:
            value = item["tp_percentage"]
            # Explicitly handle empty string, None, or 0 as None
            if value == "" or value is None:
                watchlist_item.tp_percentage = None
            else:
                watchlist_item.tp_percentage = float(value) if value is not None else None
        
        # IMPORTANT: Save sl_price and tp_price from dashboard (these are the values shown in the UI)
        if "sl_price" in item:
            watchlist_item.sl_price = item["sl_price"]
            logger.info(f"Updated sl_price for {watchlist_item.symbol}: {item['sl_price']}")
        if "tp_price" in item:
            watchlist_item.tp_price = item["tp_price"]
            logger.info(f"Updated tp_price for {watchlist_item.symbol}: {item['tp_price']}")
        
        if "buy_target" in item:
            watchlist_item.buy_target = item["buy_target"]
        if "take_profit" in item:
            watchlist_item.take_profit = item["take_profit"]
        if "stop_loss" in item:
            watchlist_item.stop_loss = item["stop_loss"]
        
        db.commit()
        db.refresh(watchlist_item)
        
        logger.info(f"Updated watchlist item {item_id} ({watchlist_item.symbol})")
        
        return {
            "id": watchlist_item.id,
            "symbol": watchlist_item.symbol,
            "exchange": watchlist_item.exchange,
            "alert_enabled": watchlist_item.alert_enabled,
            "trade_enabled": watchlist_item.trade_enabled,
            "trade_amount_usd": watchlist_item.trade_amount_usd,
            "sl_price": watchlist_item.sl_price,
            "tp_price": watchlist_item.tp_price
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating watchlist item {item_id}: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/dashboard/{item_id}")
def delete_dashboard_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Delete watchlist item (soft delete - sets is_deleted = True)"""
    try:
        watchlist_item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
        
        if not watchlist_item:
            raise HTTPException(status_code=404, detail=f"Watchlist item {item_id} not found")
        
        symbol = watchlist_item.symbol
        
        # Soft delete: set is_deleted = True instead of physically deleting
        try:
            watchlist_item.is_deleted = True
            db.commit()
            logger.info(f"Soft deleted watchlist item {item_id} ({symbol}) - is_deleted=True")
        except AttributeError:
            # Column doesn't exist yet - fall back to physical delete
            logger.warning(f"is_deleted column not found, using physical delete for {item_id} ({symbol})")
            db.delete(watchlist_item)
            db.commit()
            logger.info(f"Physically deleted watchlist item {item_id} ({symbol})")
        
        return {"ok": True, "message": f"Deleted watchlist item for {symbol}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting watchlist item {item_id}: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
