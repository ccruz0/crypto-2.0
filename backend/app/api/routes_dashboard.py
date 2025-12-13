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
from app.services.portfolio_cache import get_portfolio_summary
from app.services.portfolio_reconciliation import reconcile_portfolio_balances
from app.utils.live_trading import get_live_trading_status

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
        "buy_alert_enabled": getattr(item, "buy_alert_enabled", False),
        "sell_alert_enabled": getattr(item, "sell_alert_enabled", False),
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
        "signals": item.signals if hasattr(item, 'signals') else None,  # Manual signals from dashboard: {"buy": true/false, "sell": true/false}
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
        snapshot = get_dashboard_snapshot(db)
        if not snapshot:
            log.warning("Dashboard snapshot returned None/empty - returning fallback")
            # Return empty snapshot structure to prevent frontend errors
            return {
                "data": {
                    "source": "empty",
                    "total_usd_value": 0.0,
                    "balances": [],
                    "open_orders": [],
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
                    "errors": ["No snapshot available yet"]
                },
                "last_updated_at": None,
                "stale_seconds": None,
                "stale": True,
                "empty": True
            }
        return snapshot
    except Exception as e:
        log.error(f"Error getting dashboard snapshot: {e}", exc_info=True)
        # Return error response instead of raising exception to prevent frontend crashes
        return {
            "data": {
                "source": "error",
                "total_usd_value": 0.0,
                "balances": [],
                "open_orders": [],
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
                "errors": [f"Snapshot error: {str(e)}"]
            },
            "last_updated_at": None,
            "stale_seconds": None,
            "stale": True,
            "empty": True
        }


async def _compute_dashboard_state(db: Session) -> dict:
    """
    Core function to compute dashboard state.
    This can be called directly without FastAPI dependencies.
    
    Args:
        db: Database session (required)
    
    Returns:
        dict: Dashboard state
    """
    start_time = time.time()
    log.info("Starting dashboard state fetch")
    
    try:
        # Load portfolio data from cache (v4.0 behavior)
        # Execute in thread pool to prevent blocking the worker
        
        portfolio_start = time.time()
        # Portfolio data is sourced from PortfolioBalance rows populated by portfolio_cache.update_portfolio_cache().
        # get_portfolio_summary normalizes currencies and deduplicates balances per symbol so the frontend sees canonical assets.
        portfolio_summary = await asyncio.to_thread(get_portfolio_summary, db)
        portfolio_elapsed = time.time() - portfolio_start
        log.info(f"Portfolio summary loaded in {portfolio_elapsed:.3f}s")
        
        # Extract balances from portfolio summary
        balances_list = portfolio_summary.get("balances", [])
        # Use total_usd from portfolio_summary (correctly calculated as assets - borrowed)
        # Bug 3 Fix: portfolio_cache correctly calculates total_usd = total_assets_usd - total_borrowed_usd
        # We should use that value instead of incorrectly recalculating it
        total_usd_value = portfolio_summary.get("total_usd", 0.0)
        total_assets_usd = portfolio_summary.get("total_assets_usd", 0.0)
        total_borrowed_usd = portfolio_summary.get("total_borrowed_usd", 0.0)
        last_updated = portfolio_summary.get("last_updated")
        
        # Log raw data for debugging
        log.debug(f"Raw portfolio_summary: balances={len(balances_list)}, total_usd={total_usd_value}, last_updated={last_updated}")
        
        # Get unified open orders from cache and merge with database orders
        unified_orders_start = time.time()
        cached_open_orders = get_open_orders_cache()
        unified_open_orders = cached_open_orders.get("orders", []) or []
        
        # Also fetch orders from database (like /api/orders/open does)
        # This ensures all orders (including database-only orders) are shown
        try:
            from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
            from sqlalchemy import func
            from datetime import timezone as tz
            
            open_statuses = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]
            
            # Include all open orders AND all SL/TP orders (regardless of status)
            # to show all potential orders that might be active on exchange
            from sqlalchemy import or_
            
            db_orders = db.query(ExchangeOrder).filter(
                or_(
                    # Standard open orders (ACTIVE, NEW, PARTIALLY_FILLED)
                    ExchangeOrder.status.in_(open_statuses),
                    # OR all SL/TP orders (might be active on exchange even if marked CANCELLED)
                    ExchangeOrder.order_role.in_(['STOP_LOSS', 'TAKE_PROFIT']),
                    # OR orders with trigger types (STOP_LIMIT, TAKE_PROFIT_LIMIT, etc.)
                    ExchangeOrder.order_type.in_(['STOP_LIMIT', 'TAKE_PROFIT_LIMIT', 'STOP_LOSS', 'TAKE_PROFIT'])
                )
            ).order_by(
                func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at).desc()
            ).limit(500).all()
            
            # Convert database orders to UnifiedOpenOrder format and merge with cached orders
            # Use order_id to deduplicate (cached orders take priority)
            cached_order_ids = {order.order_id for order in unified_open_orders}
            
            for db_order in db_orders:
                if db_order.exchange_order_id not in cached_order_ids:
                    # Convert ExchangeOrder to UnifiedOpenOrder
                    from app.services.open_orders import UnifiedOpenOrder, _format_timestamp
                    from decimal import Decimal
                    
                    create_time = db_order.exchange_create_time or db_order.created_at
                    update_time = db_order.exchange_update_time or db_order.updated_at
                    
                    # ExchangeOrder doesn't have trigger_price field, only price and trigger_condition
                    # Determine if this is a trigger order based on order_type or order_role
                    is_trigger_order = (
                        db_order.order_type and any(
                            trigger_type in db_order.order_type.upper()
                            for trigger_type in ['TRIGGER', 'STOP', 'TAKE_PROFIT', 'STOP_LIMIT', 'TAKE_PROFIT_LIMIT']
                        )
                    ) or db_order.order_role in ['STOP_LOSS', 'TAKE_PROFIT']
                    
                    db_unified = UnifiedOpenOrder(
                        order_id=str(db_order.exchange_order_id),
                        symbol=db_order.symbol or "",
                        side=db_order.side.value if hasattr(db_order.side, 'value') else str(db_order.side),
                        order_type=db_order.order_type or "LIMIT",
                        status=db_order.status.value if hasattr(db_order.status, 'value') else str(db_order.status),
                        price=Decimal(str(db_order.price)) if db_order.price else None,
                        trigger_price=Decimal(str(db_order.trigger_condition)) if db_order.trigger_condition else None,  # Use trigger_condition as trigger_price
                        quantity=Decimal(str(db_order.quantity)) if db_order.quantity else Decimal("0"),
                        is_trigger=is_trigger_order,
                        trigger_type=db_order.order_role if db_order.order_role else None,
                        client_oid=db_order.client_oid,
                        created_at=_format_timestamp(create_time),
                        updated_at=_format_timestamp(update_time),
                        source="database",
                        metadata={},
                    )
                    unified_open_orders.append(db_unified)
                    cached_order_ids.add(db_unified.order_id)
                    
                    log.debug(f"Added database order {db_order.exchange_order_id} to dashboard state")
            
            # Also check SQLite order_history_db for compatibility (like /api/orders/open does)
            try:
                from app.services.order_history_db import order_history_db
                sqlite_orders = order_history_db.get_orders_by_status(['ACTIVE', 'NEW', 'PARTIALLY_FILLED'], limit=100)
                
                for sqlite_order in sqlite_orders:
                    order_id = sqlite_order.get('order_id')
                    if order_id and order_id not in cached_order_ids:
                        # Convert SQLite order dict to UnifiedOpenOrder format
                        from app.services.open_orders import UnifiedOpenOrder, _normalize_symbol, _safe_decimal, _format_timestamp
                        from decimal import Decimal
                        
                        order_id_str = str(order_id)
                        symbol = _normalize_symbol(sqlite_order.get('instrument_name') or sqlite_order.get('symbol'))
                        side = (sqlite_order.get('side') or 'BUY').upper()
                        order_type = (sqlite_order.get('order_type') or sqlite_order.get('type') or 'LIMIT').upper()
                        status = (sqlite_order.get('status') or 'NEW').upper()
                        
                        sqlite_unified = UnifiedOpenOrder(
                            order_id=order_id_str,
                            symbol=symbol,
                            side=side,
                            order_type=order_type,
                            status=status,
                            price=_safe_decimal(sqlite_order.get('price')),
                            trigger_price=_safe_decimal(sqlite_order.get('trigger_price') or sqlite_order.get('stop_price')),
                            quantity=_safe_decimal(sqlite_order.get('quantity')) or Decimal("0"),
                            is_trigger=False,
                            client_oid=sqlite_order.get('client_oid'),
                            created_at=_format_timestamp(sqlite_order.get('create_time') or sqlite_order.get('created_at')),
                            updated_at=_format_timestamp(sqlite_order.get('update_time') or sqlite_order.get('updated_at')),
                            source="sqlite",
                            metadata=sqlite_order,
                        )
                        unified_open_orders.append(sqlite_unified)
                        cached_order_ids.add(sqlite_unified.order_id)
                        log.debug(f"Added SQLite order {order_id_str} to dashboard state")
            except Exception as sqlite_err:
                log.debug(f"Error getting orders from SQLite: {sqlite_err}")
                
        except Exception as db_err:
            log.warning(f"Error merging database orders: {db_err}")
            # Continue with cached orders only if database merge fails
        
        open_orders_list = [serialize_unified_order(order) for order in unified_open_orders]
        unified_orders_elapsed = time.time() - unified_orders_start
        log.info(f"[PERF] get_unified_open_orders (with DB merge) took {unified_orders_elapsed:.3f} seconds, total orders: {len(open_orders_list)}")
        
        # Safely get last_updated with null-safety
        last_updated_value = cached_open_orders.get("last_updated")
        last_updated_iso = None
        if last_updated_value:
            # Check if it's already a datetime object
            if hasattr(last_updated_value, 'isoformat'):
                last_updated_iso = last_updated_value.isoformat()
            elif isinstance(last_updated_value, str):
                # Already a string, use as-is
                last_updated_iso = last_updated_value
        
        open_orders_summary = {
            "orders": open_orders_list,
            "last_updated": last_updated_iso,
        }
        
        # Calculate portfolio order metrics
        metrics_start = time.time()
        order_metrics = calculate_portfolio_order_metrics(unified_open_orders)
        metrics_elapsed = time.time() - metrics_start
        log.info(f"[PERF] calculate_portfolio_order_metrics took {metrics_elapsed:.3f} seconds")
        
        # Count only TP (Take Profit) orders as "open orders"
        # Group TP orders by base symbol
        # IMPORTANT: Only count ACTIVE orders (NEW, ACTIVE, PARTIALLY_FILLED, PENDING)
        # Exclude CANCELLED, FILLED, REJECTED, EXPIRED orders
        # Note: PENDING is used by some exchanges/APIs as equivalent to ACTIVE
        tp_orders_by_symbol: Dict[str, int] = {}
        active_statuses = {"NEW", "ACTIVE", "PARTIALLY_FILLED", "PENDING"}
        for order in unified_open_orders:
            order_type = (order.order_type or "").upper()
            order_status = (order.status or "").upper()
            if "TAKE_PROFIT" in order_type and order_status in active_statuses:
                base_symbol = order.base_symbol
                if base_symbol:
                    tp_orders_by_symbol[base_symbol] = tp_orders_by_symbol.get(base_symbol, 0) + 1
        
        # If cache is empty, also check database for TP orders
        if not tp_orders_by_symbol:
            from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
            from app.services.open_orders import _extract_base_symbol
            
            open_statuses = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]
            db_tp_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.status.in_(open_statuses),
                ExchangeOrder.order_type.like('%TAKE_PROFIT%')
            ).all()
            
            for order in db_tp_orders:
                symbol = order.symbol or ""
                base_symbol = _extract_base_symbol(symbol)
                if base_symbol:
                    tp_orders_by_symbol[base_symbol] = tp_orders_by_symbol.get(base_symbol, 0) + 1
        
        open_position_counts = tp_orders_by_symbol
        
        # Format portfolio assets (v4.0 format)
        # Filter: include all balances with balance > 0 OR usd_value > 0 (v4.0 behavior)
        portfolio_assets = []
        market_prices: Dict[str, float] = {}
        for balance in balances_list:
            balance_amount = balance.get("balance", 0.0)
            usd_value = balance.get("usd_value", 0.0)
            
            # v4.0 filter: include if balance > 0 OR usd_value > 0
            if balance_amount > 0 or usd_value > 0:
                currency = balance.get("currency", balance.get("asset", "")).upper()
                # Extract base currency (e.g., "AAVE" from "AAVE_USDT" or just "AAVE")
                base_currency = currency.split("_")[0] if "_" in currency else currency
                
                # Search for metrics using multiple strategies to handle symbol variants
                # This ensures we find metrics whether they're indexed by base_symbol or full symbol
                # Example: Balance "AAVE" needs to match orders "AAVE_USDT" or "AAVE_USD"
                metrics = {}
                
                # Strategy 1: Try base_currency (metrics are typically indexed by base_symbol)
                # This handles cases where orders are "AAVE_USDT" but metrics indexed by "AAVE"
                if base_currency in order_metrics:
                    metrics = order_metrics[base_currency]
                
                # Strategy 2: Try full currency name if it differs from base
                # This handles cases where metrics might be indexed by full symbol
                if not metrics and currency != base_currency and currency in order_metrics:
                    metrics = order_metrics[currency]
                
                # Strategy 3: Try common variants (USDT/USD) for all coins
                # This handles cases where balance is "AAVE" but orders are "AAVE_USDT" or "AAVE_USD"
                if not metrics:
                    for variant in [f"{base_currency}_USDT", f"{base_currency}_USD"]:
                        if variant in order_metrics:
                            metrics = order_metrics[variant]
                            log.debug(f"Found metrics for {currency} using variant {variant}")
                            break
                
                # Count only TP (Take Profit) orders as "open orders"
                # Search for TP orders count using same symbol variant strategy
                tp_count = 0
                
                # Try to get TP count using base_currency
                if base_currency in open_position_counts:
                    tp_count = open_position_counts[base_currency]
                
                # Try full currency name if different from base
                if tp_count == 0 and currency != base_currency and currency in open_position_counts:
                    tp_count = open_position_counts[currency]
                
                # Try common variants (USDT/USD)
                if tp_count == 0:
                    for variant in [f"{base_currency}_USDT", f"{base_currency}_USD"]:
                        if variant in open_position_counts:
                            tp_count = open_position_counts[variant]
                            break
                
                # Also count TP orders directly from unified_open_orders if not found in counts
                if tp_count == 0:
                    # Count TP orders for this symbol and variants
                    symbol_variants = [currency, base_currency]
                    if "_" not in currency:
                        symbol_variants.extend([f"{base_currency}_USDT", f"{base_currency}_USD"])
                    else:
                        if currency.endswith("_USDT"):
                            symbol_variants.append(currency.replace("_USDT", "_USD"))
                        elif currency.endswith("_USD"):
                            symbol_variants.append(currency.replace("_USD", "_USDT"))
                    
                    for order in unified_open_orders:
                        order_symbol = (order.symbol or "").upper()
                        order_type = (order.order_type or "").upper()
                        order_status = (order.status or "").upper()
                        # Only count ACTIVE TP orders (exclude CANCELLED, FILLED, etc.)
                        if (order_symbol in [v.upper() for v in symbol_variants] 
                            and "TAKE_PROFIT" in order_type 
                            and order_status in active_statuses):
                            tp_count += 1
                
                # open_orders_count = count of TP orders only
                open_orders_count = tp_count

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
                        # Bug 3 Fix: Use total_usd from portfolio_summary (correctly calculated)
                        total_usd_value = portfolio_summary.get("total_usd", 0.0)
                        total_assets_usd = portfolio_summary.get("total_assets_usd", 0.0)
                        total_borrowed_usd = portfolio_summary.get("total_borrowed_usd", 0.0)
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
                "reason": None,
                "live_trading_enabled": get_live_trading_status(db),
                "mode": "LIVE" if get_live_trading_status(db) else "DRY_RUN"
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
                "reason": None,
                "live_trading_enabled": get_live_trading_status(db) if db else False,
                "mode": "LIVE" if (get_live_trading_status(db) if db else False) else "DRY_RUN"
            },
            "partial": True,
            "errors": [str(e)]
        }


@router.get("/dashboard/state")
async def get_dashboard_state(
    db: Session = Depends(get_db)
):
    """
    FastAPI route handler for /dashboard/state endpoint.
    Delegates to _compute_dashboard_state to avoid circular dependencies.
    """
    log.info("[DASHBOARD_STATE_DEBUG] GET /api/dashboard/state received")
    try:
        result = await _compute_dashboard_state(db)
        # FIX: Check portfolio.assets (v4.0 format) instead of portfolio.balances
        # portfolio.balances doesn't exist - balances is at top level for backward compatibility
        # portfolio.assets is the main portfolio data structure
        portfolio_assets = result.get("portfolio", {}).get("assets", [])
        has_portfolio = bool(portfolio_assets and len(portfolio_assets) > 0)
        log.info(f"[DASHBOARD_STATE_DEBUG] response_status=200 has_portfolio={has_portfolio} assets_count={len(portfolio_assets) if portfolio_assets else 0}")
        return result
    except Exception as e:
        log.error(f"[DASHBOARD_STATE_DEBUG] response_status=500 error={str(e)}", exc_info=True)
        raise


@router.get("/dashboard/open-orders-summary")
def get_open_orders_summary():
    """Return the cached unified open orders."""
    cache = get_open_orders_cache()
    cached_orders = cache.get("orders", [])
    
    # If cache is empty, try to get orders from the same source as /dashboard/state
    if not cached_orders:
        log.warning("Open orders cache is empty, attempting to get from exchange_sync...")
        try:
            from app.services.exchange_sync import ExchangeSyncService
            from app.database import SessionLocal
            sync_service = ExchangeSyncService()
            db = SessionLocal()
            try:
                # Trigger a sync to populate the cache
                sync_service.sync_open_orders(db)
                db.commit()
                # Re-read from cache after sync
                cache = get_open_orders_cache()
                cached_orders = cache.get("orders", [])
                log.info(f"Synced {len(cached_orders)} orders to cache")
            finally:
                db.close()
        except Exception as e:
            log.error(f"Failed to sync orders for open-orders-summary: {e}", exc_info=True)
    
    orders = [serialize_unified_order(order) for order in cached_orders]
    last_updated = cache.get("last_updated")
    return {
        "orders": orders,
        "last_updated": last_updated.isoformat() if last_updated else None,
    }


@router.get("/dashboard")
def list_watchlist_items(db: Session = Depends(get_db)):
    """Return watchlist items (limited to 100, deduplicated by symbol)."""
    log.info("[DASHBOARD_STATE_DEBUG] GET /api/dashboard received")
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
        log.info(f"[DASHBOARD_STATE_DEBUG] response_status=200 items_count={len(result)}")
        return result
    except Exception as e:
        log.error(f"[DASHBOARD_STATE_DEBUG] response_status=500 error={str(e)}", exc_info=True)
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
        # BEHAVIOR CHANGE: Default alert_enabled to False (was True previously)
        # This prevents unwanted alerts for coins added via API.
        # To enable alerts, the caller MUST explicitly set alert_enabled=True in the request payload.
        # This is a security/safety measure to prevent alert spam from accidentally added coins.
        alert_enabled=payload.get("alert_enabled", False),
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
    
    # Track what was updated for the message
    updates = []
    alert_enabled_old_value = None  # Store old value for logging after verification
    alert_enabled_was_updated = False  # Track if alert_enabled update was attempted
    
    if "trade_enabled" in payload:
        old_value = item.trade_enabled
        new_value = payload["trade_enabled"]
        if old_value != new_value:
            updates.append(f"TRADE: {'YES' if new_value else 'NO'}")
    
    if "alert_enabled" in payload:
        alert_enabled_old_value = item.alert_enabled  # May be None if NULL in DB
        new_value = payload["alert_enabled"]
        # Check if value actually changed (handle None as False for comparison)
        old_value_for_comparison = alert_enabled_old_value if alert_enabled_old_value is not None else False
        new_value_for_comparison = new_value if new_value is not None else False
        if old_value_for_comparison != new_value_for_comparison:
            updates.append(f"ALERT: {'YES' if new_value else 'NO'}")
            alert_enabled_was_updated = True
            # Log will be written after successful update verification (see below)
    
    if "buy_alert_enabled" in payload:
        old_value = getattr(item, "buy_alert_enabled", False)
        new_value = payload["buy_alert_enabled"]
        if old_value != new_value:
            updates.append(f"BUY alert: {'YES' if new_value else 'NO'}")
    
    if "sell_alert_enabled" in payload:
        old_value = getattr(item, "sell_alert_enabled", False)
        new_value = payload["sell_alert_enabled"]
        if old_value != new_value:
            updates.append(f"SELL alert: {'YES' if new_value else 'NO'}")
    
    _apply_watchlist_updates(item, payload)
    db.commit()
    db.refresh(item)
    
    # CRITICAL: Verify alert_enabled was actually saved to database
    # Only verify if alert_enabled was actually changed (old_value != new_value)
    if "alert_enabled" in payload and alert_enabled_old_value is not None:
        expected_value = payload["alert_enabled"]
        # Only verify and log if the value actually changed
        if alert_enabled_old_value != expected_value:
            db.refresh(item)  # Ensure we have latest from DB
            actual_value = item.alert_enabled
            if actual_value != expected_value:
                log.error(f"❌ SYNC ERROR: alert_enabled mismatch for {item.symbol} ({item_id}): "
                         f"Expected {expected_value}, but DB has {actual_value}. "
                         f"Attempting to fix...")
                item.alert_enabled = expected_value
                db.commit()
                db.refresh(item)
                log.info(f"✅ Fixed alert_enabled sync issue for {item.symbol}")
            else:
                # Log successful update only after verification confirms it was saved correctly
                log.info(f"✅ Updated alert_enabled for {item.symbol} ({item_id}): {alert_enabled_old_value} -> {expected_value}")
    
    result = _serialize_watchlist_item(item)
    
    # Add success message if updates were made
    if updates:
        result["message"] = f"✅ Updated {item.symbol}: {', '.join(updates)}"
        log.info(f"✅ Updated watchlist item {item.symbol} ({item_id}): {', '.join(updates)}")
    
    return result


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
    """Get a watchlist item by symbol (includes deleted items)."""
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


@router.put("/dashboard/symbol/{symbol}/restore")
def restore_watchlist_item_by_symbol(symbol: str, db: Session = Depends(get_db)):
    """Restore a deleted watchlist item by symbol (set is_deleted=False)."""
    symbol = (symbol or "").upper()
    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.symbol == symbol)
        .order_by(WatchlistItem.created_at.desc())
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    
    # Check if already active
    is_deleted = getattr(item, "is_deleted", False)
    if not is_deleted:
        return {
            "ok": True,
            "message": f"{symbol} is already active (not deleted)",
            "item": _serialize_watchlist_item(item)
        }
    
    # Restore the item
    try:
        if _soft_delete_supported(db) and hasattr(item, "is_deleted"):
            item.is_deleted = False
            # Optionally restore some default settings
            if not item.alert_enabled:
                item.alert_enabled = False
            db.commit()
            db.refresh(item)
            log.info(f"✅ Restored watchlist item {symbol} (ID: {item.id})")
            return {
                "ok": True,
                "message": f"{symbol} has been restored",
                "item": _serialize_watchlist_item(item)
            }
        else:
            raise HTTPException(status_code=400, detail="Soft delete not supported on this database")
    except Exception as err:
        db.rollback()
        log.exception(f"Error restoring watchlist item {symbol}")
        raise HTTPException(status_code=500, detail=str(err))


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


@router.get("/dashboard/alert-stats")
def get_alert_stats(db: Session = Depends(get_db)):
    """
    Get statistics about alert statuses across all watchlist items.
    
    Returns:
    {
        "total_items": int,
        "buy_alerts_enabled": int,
        "sell_alerts_enabled": int,
        "both_alerts_enabled": int,
        "trade_enabled": int,
        "buy_alert_coins": [str],
        "sell_alert_coins": [str],
        "both_alert_coins": [str],
        "trade_coins": [str]
    }
    """
    try:
        # Get all active watchlist items (not deleted)
        items = _filter_active_watchlist(
            db.query(WatchlistItem),
            db
        ).all()
        
        if not items:
            return {
                "total_items": 0,
                "buy_alerts_enabled": 0,
                "sell_alerts_enabled": 0,
                "both_alerts_enabled": 0,
                "trade_enabled": 0,
                "buy_alert_coins": [],
                "sell_alert_coins": [],
                "both_alert_coins": [],
                "trade_coins": []
            }
        
        total = len(items)
        buy_alerts_yes = 0
        sell_alerts_yes = 0
        both_alerts_yes = 0
        trade_yes = 0
        
        buy_alert_coins = []
        sell_alert_coins = []
        both_alert_coins = []
        trade_coins = []
        
        for item in items:
            symbol = (item.symbol or "").upper()
            has_buy = getattr(item, "buy_alert_enabled", False)
            has_sell = getattr(item, "sell_alert_enabled", False)
            has_trade = item.trade_enabled
            
            if has_buy:
                buy_alerts_yes += 1
                buy_alert_coins.append(symbol)
            
            if has_sell:
                sell_alerts_yes += 1
                sell_alert_coins.append(symbol)
            
            if has_buy and has_sell:
                both_alerts_yes += 1
                both_alert_coins.append(symbol)
            
            if has_trade:
                trade_yes += 1
                trade_coins.append(symbol)
        
        return {
            "total_items": total,
            "buy_alerts_enabled": buy_alerts_yes,
            "sell_alerts_enabled": sell_alerts_yes,
            "both_alerts_enabled": both_alerts_yes,
            "trade_enabled": trade_yes,
            "buy_alert_coins": sorted(buy_alert_coins),
            "sell_alert_coins": sorted(sell_alert_coins),
            "both_alert_coins": sorted(both_alert_coins),
            "trade_coins": sorted(trade_coins)
        }
        
    except Exception as e:
        log.error(f"Error getting alert stats: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/dashboard/bulk-update-alerts")
def bulk_update_alerts(
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """
    Bulk update all watchlist items:
    - Set buy_alert_enabled and sell_alert_enabled to specified values
    - Set trade_enabled to specified value
    
    Request body:
    {
        "buy_alerts": true,  # Default: true
        "sell_alerts": true,  # Default: true
        "trade_enabled": false  # Default: false
    }
    
    Default behavior: Enable all BUY/SELL alerts, disable all TRADE
    """
    try:
        buy_alerts = payload.get("buy_alerts", True)
        sell_alerts = payload.get("sell_alerts", True)
        trade_enabled = payload.get("trade_enabled", False)
        
        # Get all active watchlist items (not deleted)
        items = _filter_active_watchlist(
            db.query(WatchlistItem),
            db
        ).all()
        
        if not items:
            return {
                "ok": True,
                "updated_count": 0,
                "message": "No watchlist items found"
            }
        
        updated_count = 0
        for item in items:
            changed = False
            
            # Update BUY alert
            if hasattr(item, "buy_alert_enabled") and item.buy_alert_enabled != buy_alerts:
                item.buy_alert_enabled = buy_alerts
                changed = True
            
            # Update SELL alert
            if hasattr(item, "sell_alert_enabled") and item.sell_alert_enabled != sell_alerts:
                item.sell_alert_enabled = sell_alerts
                changed = True
            
            # Update TRADE
            if item.trade_enabled != trade_enabled:
                item.trade_enabled = trade_enabled
                changed = True
            
            if changed:
                updated_count += 1
        
        db.commit()
        
        log.info(f"Bulk update completed: {updated_count} items updated")
        log.info(f"  - buy_alert_enabled: {buy_alerts}")
        log.info(f"  - sell_alert_enabled: {sell_alerts}")
        log.info(f"  - trade_enabled: {trade_enabled}")
        
        return {
            "ok": True,
            "updated_count": updated_count,
            "total_items": len(items),
            "buy_alert_enabled": buy_alerts,
            "sell_alert_enabled": sell_alerts,
            "trade_enabled": trade_enabled,
            "message": f"Updated {updated_count} watchlist items"
        }
        
    except Exception as e:
        db.rollback()
        log.error(f"Error in bulk update: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/expected-take-profit")
def get_expected_take_profit_summary_endpoint(db: Session = Depends(get_db)):
    """
    Get expected take profit summary for all symbols with open positions.
    Returns summary data per symbol: net_qty, position_value, covered_qty, uncovered_qty, total_expected_profit.
    """
    try:
        from app.services.expected_take_profit import get_expected_take_profit_summary
        from app.services.portfolio_cache import get_portfolio_summary
        
        # Get portfolio assets (from balances format)
        portfolio_summary = get_portfolio_summary(db)
        if not portfolio_summary:
            log.warning("Expected TP: portfolio_summary is None, returning empty summary")
            return {
                "summary": [],
                "total_symbols": 0,
                "last_updated": None,
            }
        portfolio_balances = portfolio_summary.get("balances", []) if portfolio_summary else []
        log.info(f"Expected TP: Got {len(portfolio_balances)} portfolio balances")
        
        # Convert balances format to assets format for the service
        portfolio_assets = [
            {
                "coin": bal.get("currency", "").upper(),
                "balance": bal.get("balance", 0),
                "value_usd": bal.get("usd_value", 0),
            }
            for bal in portfolio_balances
            if bal.get("balance", 0) > 0
        ]
        log.info(f"Expected TP: Processing {len(portfolio_assets)} assets with positive balance")
        
        # Build market prices dict from portfolio data
        market_prices: Dict[str, float] = {}
        for asset in portfolio_assets:
            symbol = asset.get("coin", "").upper()
            balance = asset.get("balance", 0)
            value_usd = asset.get("value_usd", 0)
            if balance > 0:
                market_prices[symbol] = float(value_usd) / float(balance)
        
        # Get expected take profit summary
        log.info(f"Expected TP: Calling get_expected_take_profit_summary with {len(portfolio_assets)} assets")
        summary = get_expected_take_profit_summary(db, portfolio_assets, market_prices)
        log.info(f"Expected TP: Summary returned {len(summary)} symbols: {list(summary.keys())}")
        
        # Convert to list and sort by position_value descending
        summary_list = list(summary.values())
        summary_list.sort(key=lambda x: x.get("position_value", 0), reverse=True)
        log.info(f"Expected TP: Summary list has {len(summary_list)} items after conversion")
        
        # Handle last_updated - can be timestamp (float) or datetime
        last_updated = portfolio_summary.get("last_updated")
        if last_updated:
            if isinstance(last_updated, (int, float)):
                from datetime import datetime, timezone
                last_updated = datetime.fromtimestamp(last_updated, tz=timezone.utc).isoformat()
            elif hasattr(last_updated, 'isoformat'):
                last_updated = last_updated.isoformat()
            else:
                last_updated = None
        
        return {
            "summary": summary_list,
            "total_symbols": len(summary_list),
            "last_updated": last_updated,
        }
    except Exception as e:
        log.error(f"Error getting expected take profit summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/expected-take-profit/{symbol}")
def get_expected_take_profit_details_endpoint(symbol: str, db: Session = Depends(get_db)):
    """
    Get detailed expected take profit data for a specific symbol.
    Returns matched lots with TP orders and uncovered quantity.
    """
    try:
        from app.services.expected_take_profit import get_expected_take_profit_details
        from app.services.portfolio_cache import get_portfolio_summary
        
        symbol = symbol.upper()
        
        # Get current price from portfolio
        portfolio_summary = get_portfolio_summary(db)
        portfolio_assets = portfolio_summary.get("assets", [])
        portfolio_balances = portfolio_summary.get("balances", [])
        
        current_price = 0.0
        balance = 0.0
        
        # Try assets format first
        for asset in portfolio_assets:
            coin = asset.get("coin", "").upper()
            if coin == symbol or coin == symbol.split('_')[0]:
                balance = asset.get("balance", 0)
                value_usd = asset.get("value_usd", 0)
                if balance > 0 and value_usd > 0:
                    current_price = float(value_usd) / float(balance)
                    break
        
        # Try balances format if not found
        if current_price <= 0:
            for bal in portfolio_balances:
                currency = bal.get("currency", "").upper()
                if currency == symbol or currency == symbol.split('_')[0]:
                    balance = bal.get("balance", 0)
                    value_usd = bal.get("usd_value", 0) or bal.get("value_usd", 0)
                    if balance > 0 and value_usd > 0:
                        current_price = float(value_usd) / float(balance)
                        break
        
        # Get detailed data (pass balance and portfolio_summary for virtual lot creation)
        details = get_expected_take_profit_details(db, symbol, current_price, balance, portfolio_summary)
        
        # Add uncovered quantity entry if exists
        if details.get("uncovered_qty", 0) > 0:
            details["uncovered_entry"] = {
                "symbol": symbol,
                "uncovered_qty": details["uncovered_qty"],
                "label": f"No matching active take profit orders for {details['uncovered_qty']:.8f} {symbol.split('_')[0]}",
                "is_uncovered": True,
            }
        
        return details
    except Exception as e:
        log.error(f"Error getting expected take profit details for {symbol}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/diagnostics/portfolio-reconciliation", tags=["diagnostics"])
def diagnostics_portfolio_reconciliation(db: Session = Depends(get_db)):
    """Compare live Crypto.com balances vs cached PortfolioBalance rows."""
    return reconcile_portfolio_balances(db)
