"""Dashboard state endpoint - returns portfolio, balances, and dashboard data"""
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from app.database import get_db, table_has_column, engine as db_engine
import logging
import time
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from app.models.watchlist import WatchlistItem
from app.services.open_orders_cache import get_open_orders_cache
from app.services.open_orders import (
    calculate_portfolio_order_metrics,
    serialize_unified_order,
)

router = APIRouter()
log = logging.getLogger("app.dashboard")


_soft_delete_supported_cache: Optional[bool] = None


def _soft_delete_supported(db: Optional[Session]) -> bool:
    """Determine once whether the current database supports is_deleted."""
    global _soft_delete_supported_cache
    if _soft_delete_supported_cache is not None:
        return _soft_delete_supported_cache
    
    bind = None
    if db is not None:
        try:
            bind = db.get_bind()
        except Exception:
            bind = getattr(db, "bind", None)
    bind = bind or db_engine
    table_name = getattr(getattr(WatchlistItem, "__table__", None), "name", None) or getattr(
        WatchlistItem, "__tablename__", "watchlist_items"
    )
    _soft_delete_supported_cache = bool(
        bind and table_has_column(bind, table_name, "is_deleted")
    )
    if not _soft_delete_supported_cache:
        log.warning("Soft delete column is_deleted not detected on table %s; falling back to hard deletes", table_name)
    return _soft_delete_supported_cache


def _filter_active_watchlist(query, db: Optional[Session]):
    """Apply is_deleted filter when the column exists."""
    if _soft_delete_supported(db):
        return query.filter(WatchlistItem.is_deleted == False)
    return query


def _mark_item_deleted(item: WatchlistItem):
    """Reset trading flags and mark the item as deleted."""
    if hasattr(item, "is_deleted"):
        item.is_deleted = True
    if hasattr(item, "trade_enabled"):
        item.trade_enabled = False
    if hasattr(item, "trade_on_margin"):
        item.trade_on_margin = False
    if hasattr(item, "alert_enabled"):
        item.alert_enabled = False
    if hasattr(item, "trade_amount_usd"):
        item.trade_amount_usd = None
    if hasattr(item, "skip_sl_tp_reminder"):
        item.skip_sl_tp_reminder = True


def _serialize_watchlist_item(item: WatchlistItem) -> Dict[str, Any]:
    """Convert WatchlistItem SQLAlchemy object into JSON-serializable dict."""
    if not item:
        return {}
    
    def _iso(dt):
        return dt.isoformat() if dt else None
    
    return {
        "id": item.id,
        "symbol": (item.symbol or "").upper(),
        "exchange": item.exchange,
        "alert_enabled": item.alert_enabled,
        "trade_enabled": item.trade_enabled,
        "trade_amount_usd": item.trade_amount_usd,
        "trade_on_margin": item.trade_on_margin,
        "sl_tp_mode": item.sl_tp_mode,
        "min_price_change_pct": item.min_price_change_pct,
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
        "res_down": item.res_down,
        "order_status": item.order_status,
        "order_date": _iso(item.order_date),
        "purchase_price": item.purchase_price,
        "quantity": item.quantity,
        "sold": item.sold,
        "sell_price": item.sell_price,
        "notes": item.notes,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at) if hasattr(item, "updated_at") else None,
        "signals": item.signals,
        "skip_sl_tp_reminder": item.skip_sl_tp_reminder,
        "is_deleted": getattr(item, "is_deleted", False),
        "deleted": bool(getattr(item, "is_deleted", False)),
    }


def _apply_watchlist_updates(item: WatchlistItem, data: Dict[str, Any]) -> None:
    """Apply incoming partial updates to a WatchlistItem."""
    for field, value in data.items():
        if not hasattr(item, field):
            continue
        if field == "symbol" and value:
            value = value.upper()
        setattr(item, field, value)

@router.get("/dashboard/snapshot")
def get_dashboard_snapshot_endpoint(
    db: Session = Depends(get_db)
):
    """
    Get dashboard snapshot from cache (fast endpoint).
    
    This endpoint returns the latest cached dashboard state immediately.
    It does NOT trigger a full recomputation - that happens in background.
    
    This is a lightweight read-only operation that only queries the database cache.
    
    Returns:
        {
            "data": { ... full dashboard payload ... },
            "last_updated_at": "2025-11-18T12:34:56Z",
            "stale_seconds": 17,
            "stale": false
        }
    """
    try:
        from app.services.dashboard_snapshot import get_dashboard_snapshot
        # This is a fast read-only operation - no heavy computation
        return get_dashboard_snapshot(db)
    except Exception as e:
        log.error(f"Error getting dashboard snapshot: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/state")
async def get_dashboard_state(
    db: Session = Depends(get_db)
):
    """
    Get dashboard state including portfolio balances, open orders, and signals.
    RESTORED v4.0 behavior: Loads portfolio from portfolio_cache.
    CONVERTED TO ASYNC: Uses asyncio.to_thread to prevent worker blocking.
    """
    start_time = time.time()
    log.info("Starting dashboard state fetch")
    
    try:
        # Load portfolio data from cache (v4.0 behavior)
        # Execute in thread pool to prevent blocking the worker
        from app.services.portfolio_cache import get_portfolio_summary
        
        portfolio_start = time.time()
        portfolio_summary = await asyncio.to_thread(get_portfolio_summary, db)
        portfolio_elapsed = time.time() - portfolio_start
        log.info(f"Portfolio summary loaded in {portfolio_elapsed:.3f}s")
        
        # Extract balances from portfolio summary
        balances_list = portfolio_summary.get("balances", [])
        total_usd_value = portfolio_summary.get("total_usd", 0.0)
        last_updated = portfolio_summary.get("last_updated")
        
        # Log raw data for debugging
        log.debug(f"Raw portfolio_summary: balances={len(balances_list)}, total_usd={total_usd_value}, last_updated={last_updated}")
        
        # Get unified open orders from cache and serialize
        unified_orders_start = time.time()
        cached_open_orders = get_open_orders_cache()
        unified_open_orders = cached_open_orders.get("orders", []) or []
        open_orders_list = [serialize_unified_order(order) for order in unified_open_orders]
        unified_orders_elapsed = time.time() - unified_orders_start
        log.info(f"[PERF] get_unified_open_orders took {unified_orders_elapsed:.3f} seconds")
        
        open_orders_summary = {
            "orders": open_orders_list,
            "last_updated": cached_open_orders.get("last_updated").isoformat()
            if cached_open_orders.get("last_updated")
            else None,
        }
        
        # Calculate portfolio order metrics
        metrics_start = time.time()
        order_metrics = calculate_portfolio_order_metrics(unified_open_orders)
        metrics_elapsed = time.time() - metrics_start
        log.info(f"[PERF] calculate_portfolio_order_metrics took {metrics_elapsed:.3f} seconds")
        open_position_counts = {
            symbol: int(metrics.get("open_orders_count", 0) or 0)
            for symbol, metrics in order_metrics.items()
        }

        # Format portfolio assets (v4.0 format)
        # Filter: include all balances with balance > 0 OR usd_value > 0 (v4.0 behavior)
        portfolio_assets = []
        market_prices: Dict[str, float] = {}
        for balance in balances_list:
            balance_amount = balance.get("balance", 0.0)
            usd_value = balance.get("usd_value", 0.0)
            
            # v4.0 filter: include if balance > 0 OR usd_value > 0
            if balance_amount > 0 or usd_value > 0:
                base_currency = balance.get("currency", balance.get("asset", "")).upper()
                metrics = order_metrics.get(base_currency, {})
                open_orders_count = int(metrics.get("open_orders_count", 0) or 0)

                tp_price = metrics.get("tp")
                sl_price = metrics.get("sl")

                # Ensure all numeric values are JSON-serializable (float, not Decimal)
                portfolio_assets.append({
                    "currency": balance.get("currency", ""),
                    "balance": float(balance_amount) if balance_amount is not None else 0.0,
                    "usd_value": float(usd_value) if usd_value is not None else 0.0,
                    "open_orders_count": open_orders_count,
                    "tp": float(tp_price) if tp_price is not None else None,
                    "sl": float(sl_price) if sl_price is not None else None,
                })
                
                if open_orders_count or tp_price or sl_price:
                    log.info(
                        "[PORTFOLIO] %s: open_orders=%s, tp=%s, sl=%s",
                        base_currency,
                        open_orders_count,
                        f"{float(tp_price):.2f}" if tp_price else None,
                        f"{float(sl_price):.2f}" if sl_price else None,
                    )
        
        # Log portfolio data for debugging
        log.info(f"Portfolio loaded: {len(portfolio_assets)} assets, total_usd=${total_usd_value:,.2f}")
        if portfolio_assets:
            first_10_symbols = [a["currency"] for a in portfolio_assets[:10]]
            log.info(f"First 10 symbols: {first_10_symbols}")
        else:
            log.warning("⚠️ No portfolio assets found - portfolio.assets is empty")
        
        log.info(f"Open orders (unified) loaded: {len(open_orders_list)} orders")
        elapsed = time.time() - start_time
        log.info(f"✅ Dashboard state returned in {elapsed:.3f}s: {len(portfolio_assets)} assets, {len(open_orders_list)} orders")
        
        # Log detailed diagnostics if portfolio is empty
        if len(portfolio_assets) == 0:
            log.warning("⚠️ DIAGNOSTIC: Portfolio assets is empty")
            log.warning(f"   - balances_list length: {len(balances_list)}")
            log.warning(f"   - portfolio_summary keys: {list(portfolio_summary.keys())}")
            if balances_list:
                log.warning(f"   - First 3 balances: {balances_list[:3]}")
            else:
                log.warning("   - balances_list is empty - checking if portfolio cache needs update")
                # Check if we should trigger a cache update
                try:
                    from app.services.portfolio_cache import update_portfolio_cache
                    log.info("   - Attempting to update portfolio cache...")
                    update_result = await asyncio.to_thread(update_portfolio_cache, db)
                    if update_result.get("success"):
                        log.info("   - Portfolio cache updated successfully, retrying get_portfolio_summary")
                        portfolio_summary = await asyncio.to_thread(get_portfolio_summary, db)
                        balances_list = portfolio_summary.get("balances", [])
                        total_usd_value = portfolio_summary.get("total_usd", 0.0)
                        last_updated = portfolio_summary.get("last_updated")
                        
                        # Re-process balances
                        portfolio_assets = []
                        for balance in balances_list:
                            balance_amount = balance.get("balance", 0.0)
                            usd_value = balance.get("usd_value", 0.0)
                            if balance_amount > 0 or usd_value > 0:
                                currency = balance.get("currency", "")
                                portfolio_assets.append({
                                    "currency": currency,
                                    "balance": balance_amount,
                                    "usd_value": usd_value
                                })

                                try:
                                    if currency and balance_amount and usd_value:
                                        market_prices[currency.upper()] = float(usd_value) / float(balance_amount)
                                except (TypeError, ValueError, ZeroDivisionError):
                                    pass
                        log.info(f"   - After cache update: {len(portfolio_assets)} assets loaded")
                    else:
                        log.error(f"   - Portfolio cache update failed: {update_result.get('error')}")
                except Exception as update_err:
                    log.error(f"   - Error updating portfolio cache: {update_err}", exc_info=True)
        
        return {
            "source": "portfolio_cache",
            "total_usd_value": total_usd_value,
            "balances": portfolio_assets,  # For backward compatibility
            "fast_signals": [],  # Signals are loaded separately by frontend
            "slow_signals": [],
            "open_orders": open_orders_list,
            "open_position_counts": open_position_counts,
            "open_orders_summary": open_orders_summary,
            "last_sync": last_updated,
            "portfolio_last_updated": last_updated,
            "portfolio": {
                "assets": portfolio_assets,  # Main portfolio data (v4.0 format)
                "total_value_usd": total_usd_value,
                "exchange": "Crypto.com Exchange"
            },
            "bot_status": {
                "is_running": True,
                "status": "running",
                "reason": None
            },
            "partial": False,
            "errors": []
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        log.error(f"❌ Error in dashboard state after {elapsed:.3f}s: {e}", exc_info=True)
        # Return empty but valid response on error (don't break frontend)
        return {
            "source": "error",
            "total_usd_value": 0.0,
            "balances": [],
            "fast_signals": [],
            "slow_signals": [],
            "open_orders": [],
            "open_orders_summary": [],
            "last_sync": None,
            "portfolio_last_updated": None,
            "portfolio": {
                "assets": [],
                "total_value_usd": 0.0,
                "exchange": "Crypto.com Exchange"
            },
            "bot_status": {
                "is_running": True,
                "status": "running",
                "reason": None
            },
            "partial": True,
            "errors": [str(e)]
        }


@router.get("/dashboard/open-orders-summary")
def get_open_orders_summary():
    """Return the cached unified open orders."""
    cache = get_open_orders_cache()
    orders = [serialize_unified_order(order) for order in cache.get("orders", [])]
    last_updated = cache.get("last_updated")
    return {
        "orders": orders,
        "last_updated": last_updated.isoformat() if last_updated else None,
    }


@router.get("/dashboard")
def list_watchlist_items(db: Session = Depends(get_db)):
    """Return watchlist items (limited to 100, deduplicated by symbol)."""
    try:
        query = db.query(WatchlistItem).order_by(WatchlistItem.created_at.desc())
        query = _filter_active_watchlist(query, db)
        try:
            items = query.limit(200).all()
        except Exception as query_err:
            if "undefined column" in str(query_err).lower():
                log.warning("Watchlist query failed due to missing column, retrying without filter: %s", query_err)
                db.rollback()
                items = db.query(WatchlistItem).order_by(WatchlistItem.created_at.desc()).limit(200).all()
            else:
                raise
        
        seen = set()
        result = []
        for item in items:
            symbol = (item.symbol or "").upper()
            if symbol in seen:
                continue
            seen.add(symbol)
            result.append(_serialize_watchlist_item(item))
            if len(result) >= 100:
                break
        return result
    except Exception as e:
        log.exception("Error fetching dashboard items")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dashboard")
def create_watchlist_item(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """Create a new watchlist item."""
    symbol = (payload.get("symbol") or "").upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")
    
    item = WatchlistItem(
        symbol=symbol,
        exchange=payload.get("exchange") or "CRYPTO_COM",
        alert_enabled=payload.get("alert_enabled", True),
        trade_enabled=payload.get("trade_enabled", False),
        trade_amount_usd=payload.get("trade_amount_usd"),
        trade_on_margin=payload.get("trade_on_margin", False),
        sl_tp_mode=payload.get("sl_tp_mode"),
        min_price_change_pct=payload.get("min_price_change_pct"),
        sl_percentage=payload.get("sl_percentage"),
        tp_percentage=payload.get("tp_percentage"),
        sl_price=payload.get("sl_price"),
        tp_price=payload.get("tp_price"),
        buy_target=payload.get("buy_target"),
        take_profit=payload.get("take_profit"),
        stop_loss=payload.get("stop_loss"),
        price=payload.get("price"),
        rsi=payload.get("rsi"),
        atr=payload.get("atr"),
        ma50=payload.get("ma50"),
        ma200=payload.get("ma200"),
        ema10=payload.get("ema10"),
        res_up=payload.get("res_up"),
        res_down=payload.get("res_down"),
        order_status=payload.get("order_status"),
        order_date=payload.get("order_date"),
        purchase_price=payload.get("purchase_price"),
        quantity=payload.get("quantity"),
        sold=payload.get("sold"),
        sell_price=payload.get("sell_price"),
        notes=payload.get("notes"),
        signals=payload.get("signals"),
        skip_sl_tp_reminder=payload.get("skip_sl_tp_reminder", False),
        is_deleted=False,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _serialize_watchlist_item(item)


@router.put("/dashboard/{item_id}")
def update_watchlist_item(
    item_id: int,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """Update an existing watchlist item."""
    item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    
    _apply_watchlist_updates(item, payload)
    db.commit()
    db.refresh(item)
    return _serialize_watchlist_item(item)


@router.delete("/dashboard/{item_id}")
def delete_watchlist_item(item_id: int, db: Session = Depends(get_db)):
    """Soft delete a watchlist item."""
    item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    
    try:
        if _soft_delete_supported(db) and hasattr(item, "is_deleted"):
            _mark_item_deleted(item)
            db.commit()
        else:
            db.delete(item)
            db.commit()
    except Exception as soft_err:
        db.rollback()
        log.exception("Error deleting watchlist item")
        raise HTTPException(status_code=500, detail=str(soft_err))
    return {"ok": True}


@router.get("/dashboard/symbol/{symbol}")
def get_watchlist_item_by_symbol(symbol: str, db: Session = Depends(get_db)):
    """Get a watchlist item by symbol."""
    symbol = (symbol or "").upper()
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.symbol == symbol)
        .order_by(WatchlistItem.created_at.desc())
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return _serialize_watchlist_item(item)


@router.delete("/dashboard/symbol/{symbol}")
def delete_watchlist_item_by_symbol(symbol: str, db: Session = Depends(get_db)):
    """Delete watchlist item by symbol."""
    symbol = (symbol or "").upper()
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.symbol == symbol)
        .order_by(WatchlistItem.created_at.desc())
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    
    try:
        if _soft_delete_supported(db) and hasattr(item, "is_deleted"):
            _mark_item_deleted(item)
            db.commit()
        else:
            db.delete(item)
            db.commit()
    except Exception as err:
        db.rollback()
        log.exception("Error deleting watchlist item by symbol")
        raise HTTPException(status_code=500, detail=str(err))
    return {"ok": True}
