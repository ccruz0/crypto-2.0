"""Dashboard state endpoint - returns portfolio, balances, and dashboard data"""

from fastapi import APIRouter, Depends, HTTPException, Body, Request, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import get_db, table_has_column, engine as db_engine
import logging
import time
import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple
import json
from app.models.watchlist import WatchlistItem
from app.models.watchlist_master import WatchlistMaster
from app.services.watchlist_selector import (
    deduplicate_watchlist_items,
    get_canonical_watchlist_item,
    select_preferred_watchlist_item,
)
from app.services.watchlist_master_seed import ensure_master_table_seeded
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
    # Prefer filtering by model attribute (safer than relying on cached schema detection).
    # If the column doesn't exist in a legacy DB, callers already catch "undefined column"
    # and retry without the filter.
    if hasattr(WatchlistItem, "is_deleted"):
        return query.filter(WatchlistItem.is_deleted == False)
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


def _serialize_watchlist_item(item: WatchlistItem, market_data: Optional[Any] = None, db: Optional[Session] = None) -> Dict[str, Any]:
    """Convert WatchlistItem SQLAlchemy object into JSON-serializable dict.
    
    Args:
        item: WatchlistItem to serialize
        market_data: Optional MarketData object to enrich the item with computed values
        db: Optional database session for calculating TP/SL from strategy
    """
    if not item:
        return {}
    
    def _iso(dt):
        return dt.isoformat() if dt else None
    
    # Ensure default values for fields that should always have values
    # These fields should never be None in the API response
    default_sl_tp_mode = item.sl_tp_mode if item.sl_tp_mode else "conservative"
    default_order_status = item.order_status if item.order_status else "PENDING"
    default_exchange = item.exchange if item.exchange else "CRYPTO_COM"
    
    serialized = {
        "id": item.id,
        "symbol": (item.symbol or "").upper(),
        "exchange": default_exchange,  # Always ensure exchange has a value
        # CRITICAL: Return exact DB values for boolean fields (no defaults)
        # If DB is False, return False. If DB is None, return None (not False).
        "alert_enabled": item.alert_enabled,
        "buy_alert_enabled": getattr(item, "buy_alert_enabled", None),
        "sell_alert_enabled": getattr(item, "sell_alert_enabled", None),
        "trade_enabled": item.trade_enabled,
        # REGRESSION GUARD: trade_amount_usd must be returned exactly as stored in DB
        # - If DB is NULL, API must return null (NOT 10, NOT 0, NOT any default)
        # - If DB is 10.0, API must return 10.0 (NOT 11, NOT mutated)
        # - This field is the single source of truth - no defaults/mutations allowed
        # - Any change that adds defaults here will break the consistency guarantee
        "trade_amount_usd": item.trade_amount_usd,
        "trade_on_margin": item.trade_on_margin,
        "sl_tp_mode": default_sl_tp_mode,  # Always ensure sl_tp_mode has a value
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
        "order_status": default_order_status,  # Always ensure order_status has a value
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
    
    # Enrich with MarketData if provided (ALWAYS prefer live computed values over DB values)
    # MarketData contains the live computed values (price, rsi, ma50, ma200, ema10, atr, volume fields)
    # while DB values may be stale, so we should always prefer market_data when available
    current_price = serialized["price"]
    current_atr = serialized["atr"]
    
    # Track if MarketData was missing or incomplete for logging
    market_data_missing_fields = []
    
    if market_data:
        if market_data.price is not None:
            serialized["price"] = market_data.price
            current_price = market_data.price
        if market_data.rsi is not None:
            serialized["rsi"] = market_data.rsi
        if market_data.ma50 is not None:
            serialized["ma50"] = market_data.ma50
        if market_data.ma200 is not None:
            serialized["ma200"] = market_data.ma200
        if market_data.ema10 is not None:
            serialized["ema10"] = market_data.ema10
        if market_data.atr is not None:
            serialized["atr"] = market_data.atr
            current_atr = market_data.atr
        if market_data.res_up is not None:
            serialized["res_up"] = market_data.res_up
        if market_data.res_down is not None:
            serialized["res_down"] = market_data.res_down
        # Volume fields from MarketData
        if market_data.volume_ratio is not None:
            serialized["volume_ratio"] = market_data.volume_ratio
        if market_data.current_volume is not None:
            serialized["current_volume"] = market_data.current_volume
        if market_data.avg_volume is not None:
            serialized["avg_volume"] = market_data.avg_volume
        if market_data.volume_24h is not None:
            serialized["volume_24h"] = market_data.volume_24h
        
        # Check which critical fields are still missing after enrichment
        if serialized["price"] is None:
            market_data_missing_fields.append("price")
        if serialized["rsi"] is None:
            market_data_missing_fields.append("rsi")
        if serialized["ma50"] is None:
            market_data_missing_fields.append("ma50")
        if serialized["ma200"] is None:
            market_data_missing_fields.append("ma200")
        if serialized["ema10"] is None:
            market_data_missing_fields.append("ema10")
    else:
        # MarketData not found - log warning for monitoring
        market_data_missing_fields = ["price", "rsi", "ma50", "ma200", "ema10", "atr"]
        log.debug(f"⚠️ MarketData not found for {item.symbol} - technical indicators will be None")
    
    # Log warning if critical fields are missing (helps identify MarketData update issues)
    if market_data_missing_fields and log.isEnabledFor(logging.WARNING):
        log.warning(
            f"⚠️ {item.symbol}: MarketData missing fields: {', '.join(market_data_missing_fields)}. "
            f"Ensure market_updater process is running to populate MarketData table."
        )
    
    # CRITICAL: Calculate TP/SL from strategy settings if they're blank
    # This ensures all watchlist items have TP/SL values based on their strategy configuration
    if (serialized["sl_price"] is None or serialized["tp_price"] is None) and current_price and current_price > 0:
        calculated_sl, calculated_tp = _calculate_tp_sl_from_strategy(
            symbol=item.symbol,
            price=current_price,
            atr=current_atr,
            watchlist_item=item,
            db=db
        )
        
        # Only populate if calculated values are available and current values are None
        needs_commit = False
        if calculated_sl is not None and serialized["sl_price"] is None:
            serialized["sl_price"] = calculated_sl
            if db and item.sl_price is None:
                item.sl_price = calculated_sl
                needs_commit = True
            log.debug(f"Populated sl_price for {item.symbol} from strategy: {calculated_sl}")
        
        if calculated_tp is not None and serialized["tp_price"] is None:
            serialized["tp_price"] = calculated_tp
            if db and item.tp_price is None:
                item.tp_price = calculated_tp
                needs_commit = True
            log.debug(f"Populated tp_price for {item.symbol} from strategy: {calculated_tp}")
        
        # Save calculated values to database if they were missing
        if needs_commit and db:
            try:
                db.add(item)
                db.commit()
                db.refresh(item)
                log.info(f"✅ Populated missing SL/TP for {item.symbol} from strategy: SL={item.sl_price}, TP={item.tp_price}")
            except Exception as e:
                db.rollback()
                log.error(f"Error saving calculated SL/TP for {item.symbol}: {e}", exc_info=True)
    
    # CRITICAL: Add resolved strategy information to API response
    # This ensures frontend can display the correct strategy and tooltip matches dropdown
    # Must always resolve strategy - if resolver fails, log error but still attempt resolution
    strategy_type = None
    risk_approach = None
    try:
        from app.services.strategy_profiles import resolve_strategy_profile
        strategy_type, risk_approach = resolve_strategy_profile(
            symbol=item.symbol,
            db=db,
            watchlist_item=item
        )
    except Exception as e:
        log.error(f"Failed to resolve strategy for {item.symbol}: {e}", exc_info=True)
        # Try to get at least risk from DB directly
        if item.sl_tp_mode:
            from app.services.strategy_profiles import _normalize_approach, RiskApproach
            risk_approach = _normalize_approach(item.sl_tp_mode)
    
    # Add strategy fields to response
    serialized["strategy_preset"] = strategy_type.value if strategy_type else None
    serialized["strategy_risk"] = risk_approach.value if risk_approach else None
    # Create canonical strategy key for comparison (e.g., "swing-conservative")
    if strategy_type and risk_approach:
        serialized["strategy_key"] = f"{strategy_type.value}-{risk_approach.value}"
    else:
        serialized["strategy_key"] = None
        # Log warning if strategy should be resolvable but isn't
        if item.sl_tp_mode:
            log.warning(f"Strategy resolution incomplete for {item.symbol}: preset={strategy_type}, risk={risk_approach}, sl_tp_mode={item.sl_tp_mode}")
    
    return serialized


def _serialize_watchlist_master(item: WatchlistMaster, db: Optional[Session] = None) -> Dict[str, Any]:
    """Convert WatchlistMaster SQLAlchemy object into JSON-serializable dict.
    
    This is the new serialization function that reads from the master table (source of truth).
    It includes per-field update timestamps for UI display.
    
    Args:
        item: WatchlistMaster to serialize
        db: Optional database session for calculating TP/SL from strategy
    """
    if not item:
        return {}
    
    def _iso(dt):
        return dt.isoformat() if dt else None
    
    # Parse signals JSON if present
    signals = None
    if item.signals:
        try:
            import json
            signals = json.loads(item.signals) if isinstance(item.signals, str) else item.signals
        except (json.JSONDecodeError, TypeError):
            signals = None
    
    # Get field update timestamps
    field_updated_at = item.get_field_updated_at()
    
    serialized = {
        "id": item.id,
        "symbol": (item.symbol or "").upper(),
        "exchange": item.exchange or "CRYPTO_COM",
        "alert_enabled": item.alert_enabled if item.alert_enabled is not None else False,
        "buy_alert_enabled": item.buy_alert_enabled if item.buy_alert_enabled is not None else False,
        "sell_alert_enabled": item.sell_alert_enabled if item.sell_alert_enabled is not None else False,
        "trade_enabled": item.trade_enabled if item.trade_enabled is not None else False,
        "trade_amount_usd": item.trade_amount_usd,
        "trade_on_margin": item.trade_on_margin if item.trade_on_margin is not None else False,
        "sl_tp_mode": item.sl_tp_mode or "conservative",
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
        "volume_ratio": item.volume_ratio,
        "current_volume": item.current_volume,
        "avg_volume": item.avg_volume,
        "volume_24h": item.volume_24h,
        "order_status": item.order_status or "PENDING",
        "order_date": _iso(item.order_date),
        "purchase_price": item.purchase_price,
        "quantity": item.quantity,
        "sold": item.sold if item.sold is not None else False,
        "sell_price": item.sell_price,
        "notes": item.notes,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
        "signals": signals,
        "skip_sl_tp_reminder": item.skip_sl_tp_reminder if item.skip_sl_tp_reminder is not None else False,
        "is_deleted": item.is_deleted if item.is_deleted is not None else False,
        "deleted": bool(item.is_deleted if item.is_deleted is not None else False),
        # Include per-field update timestamps for UI
        "field_updated_at": field_updated_at,
    }
    
    # Calculate TP/SL from strategy if needed (same logic as before)
    if (serialized["sl_price"] is None or serialized["tp_price"] is None) and serialized["price"] and serialized["price"] > 0:
        calculated_sl, calculated_tp = _calculate_tp_sl_from_strategy(
            symbol=item.symbol,
            price=serialized["price"],
            atr=serialized["atr"],
            watchlist_item=None,  # We don't have WatchlistItem here, but we can get sl_tp_mode from master
            db=db
        )
        
        if calculated_sl is not None and serialized["sl_price"] is None:
            serialized["sl_price"] = calculated_sl
            if db:
                item.sl_price = calculated_sl
                item.set_field_updated_at('sl_price')
        
        if calculated_tp is not None and serialized["tp_price"] is None:
            serialized["tp_price"] = calculated_tp
            if db:
                item.tp_price = calculated_tp
                item.set_field_updated_at('tp_price')
        
        if db and (calculated_sl is not None or calculated_tp is not None):
            try:
                db.commit()
                db.refresh(item)
            except Exception as e:
                db.rollback()
                log.error(f"Error saving calculated SL/TP for {item.symbol}: {e}", exc_info=True)
    
    return serialized


def _get_market_data_for_symbol(db: Session, symbol: str) -> Optional[Any]:
    """Get MarketData for a single symbol.
    
    Args:
        db: Database session
        symbol: Symbol to fetch MarketData for (case-insensitive)
    
    Returns:
        MarketData object if found, None otherwise
    """
    try:
        from app.models.market_price import MarketData
        import sqlalchemy.exc
        
        # Normalize symbol to uppercase for consistency
        symbol_upper = symbol.upper() if symbol else ""
        if not symbol_upper:
            return None
            
        return db.query(MarketData).filter(MarketData.symbol == symbol_upper).first()
    except sqlalchemy.exc.SQLAlchemyError as e:
        log.warning(f"Database error fetching MarketData for {symbol}: {e}")
        return None
    except Exception as e:
        log.error(f"Unexpected error fetching MarketData for {symbol}: {e}", exc_info=True)
        return None


def _calculate_tp_sl_from_strategy(
    symbol: str,
    price: Optional[float],
    atr: Optional[float],
    watchlist_item: Optional[WatchlistItem] = None,
    db: Optional[Session] = None
) -> Tuple[Optional[float], Optional[float]]:
    """
    Calculate TP/SL prices from strategy settings in trading_config.json.
    
    This function calculates sl_price and tp_price based on:
    1. Strategy rules from trading_config.json (preset + risk mode)
    2. Current price and ATR from MarketData
    3. Strategy settings: sl.atrMult, sl.pct, tp.rr, tp.pct
    
    Args:
        symbol: Symbol to calculate TP/SL for
        price: Current price (from MarketData)
        atr: ATR value (from MarketData)
        watchlist_item: Optional WatchlistItem to get sl_tp_mode override
        db: Optional database session for resolving strategy profile
    
    Returns:
        Tuple of (sl_price, tp_price) or (None, None) if calculation not possible
    """
    if price is None or price <= 0:
        return None, None
    
    try:
        from app.services.strategy_profiles import resolve_strategy_profile
        from app.services.config_loader import load_config
        
        # Resolve strategy profile (preset + risk mode)
        strategy_type, risk_approach = resolve_strategy_profile(
            symbol, db=db, watchlist_item=watchlist_item
        )
        
        # Get strategy rules from config
        cfg = load_config()
        preset_key = strategy_type.value.lower()
        risk_key = risk_approach.value.capitalize()
        
        # Get rules from presets (new format with rules structure)
        presets = cfg.get("presets", {})
        preset_data = presets.get(preset_key, {})
        
        if not preset_data or "rules" not in preset_data:
            log.debug(f"No rules found for {symbol} preset={preset_key}, risk={risk_key}")
            return None, None
        
        rules = preset_data.get("rules", {}).get(risk_key, {})
        if not rules:
            log.debug(f"No rules found for {symbol} preset={preset_key}, risk={risk_key}")
            return None, None
        
        sl_config = rules.get("sl", {})
        tp_config = rules.get("tp", {})
        
        # Calculate SL price
        sl_price = None
        if sl_config.get("atrMult") and atr is not None and atr > 0:
            # Use ATR multiplier: SL = price - (atrMult * ATR)
            atr_mult = sl_config.get("atrMult", 1.5)
            sl_price = price - (atr_mult * atr)
            log.debug(f"Calculated SL for {symbol}: {sl_price} = {price} - ({atr_mult} * {atr})")
        elif sl_config.get("atrMult") and (atr is None or atr <= 0):
            # ATR not available but strategy uses atrMult - use fallback percentage
            # Estimate percentage based on typical ATR (usually 1-3% of price for most coins)
            # Use a conservative estimate: atrMult * 2% of price
            atr_mult = sl_config.get("atrMult", 1.5)
            estimated_atr_pct = atr_mult * 2.0  # 2% per ATR multiplier unit
            sl_price = price * (1 - estimated_atr_pct / 100)
            log.debug(f"Calculated SL for {symbol} (ATR fallback): {sl_price} = {price} * (1 - {estimated_atr_pct}/100) [ATR unavailable, using fallback]")
        elif sl_config.get("pct"):
            # Use percentage: SL = price * (1 - pct/100)
            sl_pct = sl_config.get("pct", 0.5)
            sl_price = price * (1 - sl_pct / 100)
            log.debug(f"Calculated SL for {symbol}: {sl_price} = {price} * (1 - {sl_pct}/100)")
        
        # Calculate TP price
        tp_price = None
        if tp_config.get("rr") and sl_price is not None:
            # Use risk:reward ratio: TP = price + (rr * (price - sl_price))
            rr = tp_config.get("rr", 1.5)
            tp_price = price + (rr * (price - sl_price))
            log.debug(f"Calculated TP for {symbol}: {tp_price} = {price} + ({rr} * ({price} - {sl_price}))")
        elif tp_config.get("pct"):
            # Use percentage: TP = price * (1 + pct/100)
            tp_pct = tp_config.get("pct", 0.8)
            tp_price = price * (1 + tp_pct / 100)
            log.debug(f"Calculated TP for {symbol}: {tp_price} = {price} * (1 + {tp_pct}/100)")
        
        # Round to reasonable precision
        if sl_price is not None:
            sl_price = round(sl_price, 2) if sl_price >= 100 else round(sl_price, 4)
        if tp_price is not None:
            tp_price = round(tp_price, 2) if tp_price >= 100 else round(tp_price, 4)
        
        return sl_price, tp_price
        
    except Exception as e:
        log.warning(f"Error calculating TP/SL from strategy for {symbol}: {e}", exc_info=True)
        return None, None


def _apply_watchlist_updates(item: WatchlistItem, data: Dict[str, Any]) -> None:
    """Apply incoming partial updates to a WatchlistItem."""
    # Boolean fields that should never be None - convert None to False
    boolean_fields = {
        "alert_enabled", "buy_alert_enabled", "sell_alert_enabled",
        "trade_enabled", "trade_on_margin", "sold", "skip_sl_tp_reminder"
    }
    
    for field, value in data.items():
        # Avoid accidental restores/soft-delete changes via generic update endpoint.
        # Use the dedicated DELETE/restore endpoints for is_deleted transitions.
        if field == "is_deleted":
            continue
        if not hasattr(item, field):
            continue
        if field == "symbol" and value:
            value = value.upper()
        # CRITICAL: Prevent NULL values for boolean fields
        # If frontend sends null/undefined, convert to False to maintain data integrity
        if field in boolean_fields and value is None:
            value = False
        # Log updates for trade_amount_usd and trade_on_margin for debugging
        if field in ("trade_amount_usd", "trade_on_margin"):
            old_val = getattr(item, field, None)
            log.info(f"[_apply_watchlist_updates] {getattr(item, 'symbol', 'UNKNOWN')}.{field}: {old_val} → {value}")
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
        # CRITICAL: Crypto.com Margin "Wallet Balance" = NET Wallet Balance (collateral - borrowed)
        # Backend returns values explicitly:
        # - total_usd: NET Wallet Balance (collateral - borrowed) - matches Crypto.com "Wallet Balance"
        # - total_assets_usd: GROSS raw assets (before haircut and borrowed) - informational only
        # - total_collateral_usd: Collateral value after haircuts - informational only
        # - total_borrowed_usd: Total borrowed amounts (shown separately, NOT added to totals)
        total_assets_usd = portfolio_summary.get("total_assets_usd", 0.0)  # GROSS raw assets
        total_collateral_usd = portfolio_summary.get("total_collateral_usd", 0.0)  # Collateral after haircuts
        total_borrowed_usd = portfolio_summary.get("total_borrowed_usd", 0.0)  # Borrowed (separate)
        total_usd_value = portfolio_summary.get("total_usd", 0.0)  # NET Wallet Balance - matches Crypto.com "Wallet Balance"
        last_updated = portfolio_summary.get("last_updated")
        
        # Log raw data for debugging
        log.debug(f"Raw portfolio_summary: balances={len(balances_list)}, total_usd={total_usd_value}, last_updated={last_updated}")
        
        # Get unified open orders from cache - Crypto.com API is the source of truth
        unified_orders_start = time.time()
        cached_open_orders = get_open_orders_cache()
        unified_open_orders = cached_open_orders.get("orders", []) or []
        
        # Log Crypto.com API response for debugging
        cached_order_ids = {order.order_id for order in unified_open_orders}
        cached_symbols = {order.symbol for order in unified_open_orders}
        log.info(f"[OPEN_ORDERS] Crypto.com API returned {len(unified_open_orders)} open orders. Order IDs: {sorted(cached_order_ids)[:10]}... Symbols: {sorted(cached_symbols)}")
        
        # CRITICAL FIX: Only show orders that exist in Crypto.com API response
        # Do NOT merge database orders that don't exist in Crypto.com - they are stale/ghost orders
        # The cache is populated by exchange_sync.py from Crypto.com API, so it's the source of truth
        
        # Verify database orders against Crypto.com cache and log any ghost orders
        try:
            from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
            from sqlalchemy import func
            from datetime import timezone as tz
            
            open_statuses = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]
            
            # Check database for orders that claim to be open but aren't in Crypto.com response
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
            
            # Log database orders for debugging
            db_order_ids = {str(order.exchange_order_id) for order in db_orders}
            db_symbols = {order.symbol for order in db_orders if order.symbol}
            log.info(f"[OPEN_ORDERS] Database has {len(db_orders)} orders with open status. Order IDs: {sorted(db_order_ids)[:10]}... Symbols: {sorted(db_symbols)}")
            
            # Detect and log ghost orders (in database but not in Crypto.com)
            ghost_orders = []
            for db_order in db_orders:
                order_id_str = str(db_order.exchange_order_id)
                if order_id_str not in cached_order_ids:
                    ghost_orders.append({
                        "order_id": order_id_str,
                        "symbol": db_order.symbol,
                        "status": db_order.status.value if hasattr(db_order.status, 'value') else str(db_order.status),
                        "side": db_order.side.value if hasattr(db_order.side, 'value') else str(db_order.side),
                    })
            
            if ghost_orders:
                log.warning(f"[GHOST_ORDERS] Detected {len(ghost_orders)} ghost orders in database that don't exist in Crypto.com: {ghost_orders[:5]}")
                # Log each ghost order once per dashboard load
                for ghost in ghost_orders[:10]:  # Limit to first 10 to avoid log spam
                    log.warning(f"[GHOST_ORDER] Dropping ghost order: {ghost['order_id']} ({ghost['symbol']}) - status={ghost['status']}, side={ghost['side']} - NOT in Crypto.com API response")
                
        except Exception as db_err:
            log.warning(f"Error checking database for ghost orders: {db_err}")
            # Continue with cached orders only if database check fails
        
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
        
        # Track order IDs from cache to avoid duplicates when merging with database
        cached_tp_order_ids: set = set()
        
        for order in unified_open_orders:
            order_type = (order.order_type or "").upper()
            order_status = (order.status or "").upper()
            if "TAKE_PROFIT" in order_type and order_status in active_statuses:
                base_symbol = order.base_symbol
                if base_symbol:
                    tp_orders_by_symbol[base_symbol] = tp_orders_by_symbol.get(base_symbol, 0) + 1
                    # Track this order ID to avoid counting it again from database
                    if order.order_id:
                        cached_tp_order_ids.add(str(order.order_id))
        
        # Always check database for TP orders to ensure we have complete data
        # This is important because the cache might not have all TP orders
        from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
        from app.services.open_orders import _extract_base_symbol
        
        open_statuses = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]
        db_tp_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.status.in_(open_statuses),
            ExchangeOrder.order_type.like('%TAKE_PROFIT%')
        ).all()
        
        for order in db_tp_orders:
            # Skip if this order was already counted from cache
            order_id_str = str(order.exchange_order_id) if order.exchange_order_id else None
            if order_id_str and order_id_str in cached_tp_order_ids:
                continue
                
            symbol = order.symbol or ""
            base_symbol = _extract_base_symbol(symbol)
            if base_symbol:
                # Add to count (avoiding duplicates from cache)
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
                currency = balance.get("currency", "")
                # Frontend expects 'asset' field (DashboardBalance interface)
                # Also include currency/coin for backward compatibility
                portfolio_assets.append({
                    "asset": currency,  # Frontend DashboardBalance expects 'asset' field
                    "currency": currency,
                    "coin": currency,  # Add coin field for frontend compatibility
                    "balance": float(balance_amount) if balance_amount is not None else 0.0,
                    "total": float(balance_amount) if balance_amount is not None else 0.0,  # Frontend expects 'total'
                    "free": float(balance.get("available", balance_amount)) if balance_amount is not None else 0.0,  # Frontend expects 'free'
                    "locked": float(balance.get("reserved", 0)) if balance_amount is not None else 0.0,  # Frontend expects 'locked'
                    "usd_value": float(usd_value) if usd_value is not None else 0.0,
                    "market_value": float(usd_value) if usd_value is not None else 0.0,  # Also include market_value for compatibility
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
                        error_msg = update_result.get('error', 'Unknown error')
                        # Check if this is an authentication error
                        if update_result.get('auth_error') or '40101' in error_msg or 'Authentication' in error_msg:
                            log.error(f"   - Portfolio cache update failed: {error_msg}")
                            log.warning("   - ⚠️ Authentication error detected - will not retry immediately. Check API credentials and IP whitelist.")
                        else:
                            log.error(f"   - Portfolio cache update failed: {error_msg}")
                except Exception as update_err:
                    error_str = str(update_err)
                    if '40101' in error_str or 'Authentication' in error_str:
                        log.error(f"   - Error updating portfolio cache (authentication): {update_err}")
                        log.warning("   - ⚠️ Authentication error - check API credentials and IP whitelist")
                    else:
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
                "total_value_usd": total_usd_value,  # NET Wallet Balance - matches Crypto.com "Wallet Balance"
                "total_assets_usd": total_assets_usd,  # GROSS raw assets (before haircut and borrowed)
                "total_collateral_usd": total_collateral_usd,  # Collateral after haircuts (informational)
                "total_borrowed_usd": total_borrowed_usd,  # Borrowed amounts (shown separately)
                "exchange": "Crypto.com Exchange"
            },
            # Invariant: Total Value shown to users must equal Crypto.com Margin "Wallet Balance" (NET).
            # This is enforced by using total_usd from portfolio_summary, which is calculated as:
            # total_usd = total_assets_usd - total_borrowed_usd (NET equity)
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
    """Return watchlist items from WatchlistItem table (single source of truth).
    
    This endpoint reads ONLY from watchlist_items table, ensuring the UI
    displays exactly what is stored in the database with zero discrepancies.
    No defaults or mutations are applied - returns exact DB values.
    """
    import os
    
    log.info("[DASHBOARD_STATE_DEBUG] GET /api/dashboard received (using watchlist_items table)")
    try:
        # Query watchlist_items table directly (single source of truth)
        try:
            items = db.query(WatchlistItem).filter(
                WatchlistItem.is_deleted == False
            ).order_by(WatchlistItem.created_at.desc()).limit(200).all()
            
            # QUERY_RESULT: Log all fetched rows for ALGO_USDT specifically
            algo_db_rows = [item for item in items if item.symbol == "ALGO_USDT"]
            log.info(f"[QUERY_RESULT] Total rows fetched: {len(items)}, ALGO_USDT rows: {len(algo_db_rows)}")
            for item in algo_db_rows:
                log.info(f"[QUERY_RESULT] ALGO_USDT: id={item.id} trade_amount_usd={item.trade_amount_usd} trade_enabled={item.trade_enabled} alert_enabled={item.alert_enabled} is_deleted={getattr(item, 'is_deleted', None)}")
            
            # Track all DB IDs for guard check
            db_ids_by_symbol: Dict[str, set] = {}
            for item in items:
                symbol_key = (item.symbol or "").upper()
                if symbol_key not in db_ids_by_symbol:
                    db_ids_by_symbol[symbol_key] = set()
                db_ids_by_symbol[symbol_key].add(item.id)
                
        except Exception as query_err:
            log.warning(f"Watchlist items query failed: {query_err}, rolling back transaction")
            db.rollback()
            # Fallback: try without filter if column doesn't exist
            if "undefined column" in str(query_err).lower() or "no such column" in str(query_err).lower():
                log.warning("Retrying watchlist items query without is_deleted filter")
                items = db.query(WatchlistItem).order_by(WatchlistItem.created_at.desc()).limit(200).all()
                db_ids_by_symbol = {}
                for item in items:
                    symbol_key = (item.symbol or "").upper()
                    if symbol_key not in db_ids_by_symbol:
                        db_ids_by_symbol[symbol_key] = set()
                    db_ids_by_symbol[symbol_key].add(item.id)
            else:
                raise
        
        # CRITICAL: Deduplicate by symbol to ensure one row per symbol (same logic as verification scripts)
        # Use select_preferred_watchlist_item to pick canonical row when duplicates exist
        items_by_symbol: Dict[str, List[WatchlistItem]] = {}
        for item in items:
            symbol_key = (item.symbol or "").upper()
            if symbol_key not in items_by_symbol:
                items_by_symbol[symbol_key] = []
            items_by_symbol[symbol_key].append(item)
        
        # Select canonical item for each symbol (ensures API and verification scripts use same row)
        canonical_items = []
        for symbol_key, symbol_items in items_by_symbol.items():
            if len(symbol_items) > 1:
                log.debug(f"Found {len(symbol_items)} rows for {symbol_key}, selecting canonical row")
            canonical_item = select_preferred_watchlist_item(symbol_items, symbol_key)
            if canonical_item:
                canonical_items.append(canonical_item)
        
        result = []
        for item in canonical_items:
            # Get market data for enrichment (price, rsi, etc.) but don't mutate trade_amount_usd
            market_data = _get_market_data_for_symbol(db, item.symbol)
            serialized = _serialize_watchlist_item(item, market_data=market_data, db=db)
            
            # GUARD: Detect phantom IDs - if serialized id not in DB query results, log error and drop item
            symbol_key = (item.symbol or "").upper()
            if symbol_key in db_ids_by_symbol and serialized.get("id") not in db_ids_by_symbol[symbol_key]:
                log.error(f"[PHANTOM_ID_DETECTED] Symbol {symbol_key}: serialized id={serialized.get('id')} not in DB query results {db_ids_by_symbol[symbol_key]}. Dropping inconsistent item.")
                continue
            
            result.append(serialized)
            
            # SERIALIZED_RESULT: Log final serialized data for ALGO_USDT
            if item.symbol == "ALGO_USDT":
                log.info(f"[SERIALIZED_RESULT] ALGO_USDT: id={serialized.get('id')} trade_amount_usd={serialized.get('trade_amount_usd')} strategy_key={serialized.get('strategy_key')}")
            
            if len(result) >= 100:
                break
        
        # Add build fingerprint to response
        git_sha = os.getenv("ATP_GIT_SHA", "unknown")
        build_time = os.getenv("ATP_BUILD_TIME", "unknown")
        
        log.info(f"[DASHBOARD_STATE_DEBUG] response_status=200 items_count={len(result)} (from watchlist_items table, deduplicated) [commit={git_sha[:8]}]")
        
        # Return list directly (frontend expects array)
        # Note: FastAPI will serialize the list to JSON automatically
        # Build fingerprint is added via middleware or response model (see main.py)
        return result
    except Exception as e:
        log.error(f"[DASHBOARD_STATE_DEBUG] response_status=500 error={str(e)}", exc_info=True)
        log.exception("Error fetching dashboard items from watchlist_items table")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/dashboard/symbol/{symbol}")
def update_watchlist_item_by_symbol(
    symbol: str,
    payload: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db)
):
    """Update a watchlist item in WatchlistItem table (single source of truth).
    
    This endpoint writes directly to watchlist_items table.
    Returns the updated item from a fresh DB read (no mutations).
    
    REGRESSION GUARD: This function MUST update WatchlistItem, NOT WatchlistMaster.
    Changing this to update WatchlistMaster will break the "DB is truth" guarantee.
    See tests/test_watchlist_regression_guard.py for regression tests.
    """
    symbol = (symbol or "").upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")
    
    try:
        # Get or create WatchlistItem row (single source of truth)
        exchange = (payload.get("exchange") or "CRYPTO_COM").upper()
        item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.exchange == exchange,
            WatchlistItem.is_deleted == False
        ).first()
        
        if not item:
            # Create new WatchlistItem if it doesn't exist
            item = WatchlistItem(
                symbol=symbol,
                exchange=exchange,
                is_deleted=False
            )
            db.add(item)
        
        # Track which fields were updated
        updated_fields = []
        
        # Update fields from payload - CRITICAL: No defaults, exact values only
        updatable_fields = {
            "buy_target", "take_profit", "stop_loss",
            "trade_enabled", "trade_amount_usd", "trade_on_margin",
            "alert_enabled", "buy_alert_enabled", "sell_alert_enabled",
            "sl_tp_mode", "min_price_change_pct", "alert_cooldown_minutes",
            "sl_percentage", "tp_percentage", "sl_price", "tp_price",
            "notes", "skip_sl_tp_reminder",
            "order_status", "order_date", "purchase_price", "quantity",
            "sold", "sell_price",
            "price", "rsi", "atr", "ma50", "ma200", "ema10",
            "res_up", "res_down",
        }
        
        for field in updatable_fields:
            if field in payload:
                old_value = getattr(item, field, None)
                new_value = payload[field]
                
                # Handle boolean fields - convert None to False for booleans only
                if field in ["trade_enabled", "trade_on_margin", "alert_enabled", 
                            "buy_alert_enabled", "sell_alert_enabled", "sold", 
                            "skip_sl_tp_reminder"]:
                    new_value = bool(new_value) if new_value is not None else False
                
                # CRITICAL: For trade_amount_usd, allow None/null explicitly (no default)
                # Only update if value actually changed
                if old_value != new_value:
                    setattr(item, field, new_value)
                    updated_fields.append(field)
                    log.debug(f"Updated {symbol}.{field}: {old_value} -> {new_value}")
        
        # Handle signals (JSON field)
        if "signals" in payload:
            signals_value = payload["signals"]
            if signals_value is not None:
                item.signals = json.dumps(signals_value) if not isinstance(signals_value, str) else signals_value
            else:
                item.signals = None
            updated_fields.append('signals')
        
        # Update exchange if provided
        if "exchange" in payload:
            item.exchange = (payload["exchange"] or "CRYPTO_COM").upper()
        
        if updated_fields:
            db.commit()
            # CRITICAL: Refresh from DB to get exact stored values (no mutations)
            db.refresh(item)
            log.info(f"✅ Updated watchlist_items for {symbol}: {', '.join(updated_fields)}")
        else:
            log.debug(f"No fields updated for {symbol}")
            # Still refresh to return current DB state
            db.refresh(item)
        
        # Reset throttle state if alert/trade/config fields changed
        throttle_reset_fields = {
            "alert_enabled", "buy_alert_enabled", "sell_alert_enabled",
            "trade_enabled", "min_price_change_pct", "trade_amount_usd", "sl_tp_mode"
        }
        if any(field in updated_fields for field in throttle_reset_fields):
            try:
                from app.services.strategy_profiles import resolve_strategy_profile
                from app.services.signal_throttle import (
                    build_strategy_key,
                    reset_throttle_state,
                    set_force_next_signal,
                    compute_config_hash,
                )
                
                # Resolve strategy
                strategy_type, risk_approach = resolve_strategy_profile(symbol, db, item)
                strategy_key = build_strategy_key(strategy_type, risk_approach)
                
                # Get current price
                current_price = getattr(item, "price", None)
                if not current_price or current_price <= 0:
                    market_data = _get_market_data_for_symbol(db, symbol)
                    if market_data:
                        current_price = getattr(market_data, "price", None)
                
                # Compute config hash
                config_hash = compute_config_hash({
                    "alert_enabled": item.alert_enabled,
                    "buy_alert_enabled": getattr(item, "buy_alert_enabled", False),
                    "sell_alert_enabled": getattr(item, "sell_alert_enabled", False),
                    "trade_enabled": item.trade_enabled,
                    "strategy_id": None,
                    "strategy_name": item.sl_tp_mode,
                    "min_price_change_pct": item.min_price_change_pct,
                    "trade_amount_usd": item.trade_amount_usd,
                })
                
                # Build change reason
                changed_fields_list = [f for f in updated_fields if f in throttle_reset_fields]
                change_reason = f"Dashboard update: {', '.join(changed_fields_list)}"
                
                # Reset throttle state
                reset_throttle_state(
                    db,
                    symbol=symbol,
                    strategy_key=strategy_key,
                    side=None,  # Reset both BUY and SELL
                    current_price=current_price,
                    parameter_change_reason=change_reason,
                    config_hash=config_hash,
                )
                log.info(f"🔄 [DASHBOARD_UPDATE] Reset throttle state for {symbol} (strategy: {strategy_key}, price: {current_price})")
                
                # Set force_next_signal for both sides if any alert/trade field was enabled
                alert_or_trade_enabled = (
                    item.alert_enabled or
                    getattr(item, "buy_alert_enabled", False) or
                    getattr(item, "sell_alert_enabled", False) or
                    item.trade_enabled
                )
                if alert_or_trade_enabled:
                    set_force_next_signal(db, symbol=symbol, strategy_key=strategy_key, side="BUY", enabled=True)
                    set_force_next_signal(db, symbol=symbol, strategy_key=strategy_key, side="SELL", enabled=True)
                    log.info(f"⚡ [DASHBOARD_UPDATE] Set force_next_signal for {symbol} BUY/SELL - next evaluation will bypass throttle")
            except Exception as throttle_err:
                log.warning(f"⚠️ [DASHBOARD_UPDATE] Failed to reset throttle state for {symbol}: {throttle_err}", exc_info=True)
        
        # Return serialized item from fresh DB read
        market_data = _get_market_data_for_symbol(db, item.symbol)
        serialized_item = _serialize_watchlist_item(item, market_data=market_data, db=db)
        
        return {
            "ok": True,
            "message": f"Updated {len(updated_fields)} field(s) for {symbol}",
            "item": serialized_item,
            "updated_fields": updated_fields
        }
        
    except Exception as e:
        db.rollback()
        log.error(f"Error updating watchlist_items for {symbol}: {e}", exc_info=True)
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

    exchange = (payload.get("exchange") or "CRYPTO_COM").upper()

    # CRITICAL: Prevent duplicates.
    # If a row already exists for (symbol, exchange), treat this as an upsert/restore instead of inserting a new row.
    existing_rows = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.symbol == symbol, WatchlistItem.exchange == exchange)
        .order_by(WatchlistItem.id.desc())
        .all()
    )
    existing_item = select_preferred_watchlist_item(existing_rows, symbol) if existing_rows else None

    # Normalize boolean fields: convert explicit nulls to False to avoid NULLs in DB
    boolean_fields = [
        "alert_enabled",
        "buy_alert_enabled",
        "sell_alert_enabled",
        "trade_enabled",
        "trade_on_margin",
        "sold",
        "is_deleted",
        "skip_sl_tp_reminder",
    ]
    for field in boolean_fields:
        if field in payload and payload[field] is None:
            payload[field] = False

    if existing_item:
        # Restore if needed
        if hasattr(existing_item, "is_deleted"):
            existing_item.is_deleted = False
        # Always enforce normalized identity fields
        existing_item.symbol = symbol
        existing_item.exchange = exchange

        # Apply only fields explicitly provided to avoid accidentally overwriting existing settings.
        updatable_fields = {
            "alert_enabled",
            "buy_alert_enabled",
            "sell_alert_enabled",
            "trade_enabled",
            "trade_amount_usd",
            "trade_on_margin",
            "sl_tp_mode",
            "min_price_change_pct",
            "alert_cooldown_minutes",
            "sl_percentage",
            "tp_percentage",
            "sl_price",
            "tp_price",
            "buy_target",
            "take_profit",
            "stop_loss",
            "price",
            "rsi",
            "atr",
            "ma50",
            "ma200",
            "ema10",
            "res_up",
            "res_down",
            "order_status",
            "order_date",
            "purchase_price",
            "quantity",
            "sold",
            "sell_price",
            "notes",
            "signals",
            "skip_sl_tp_reminder",
        }
        # Track parameter changes for throttle state reset
        throttle_parameter_changes = []
        strategy_parameter_changes = []
        
        for field in updatable_fields:
            if field in payload and hasattr(existing_item, field):
                old_value = getattr(existing_item, field)
                new_value = payload[field]
                
                # CRITICAL: Protect user-set values from being overwritten with None
                # Only allow None for fields that the user explicitly wants to clear
                # For critical user-set fields, preserve existing values if new_value is None
                user_set_fields = {"trade_amount_usd", "sl_percentage", "tp_percentage", "sl_price", "tp_price"}
                if field in user_set_fields and new_value is None and old_value is not None:
                    # User has a value set, and frontend is trying to clear it
                    # Only clear if old_value is 0 or empty string (not a real user value)
                    if field == "trade_amount_usd":
                        if old_value != 0 and old_value != 0.0:
                            log.info(f"[WATCHLIST_PROTECT] Preserving user-set {field}={old_value} for {symbol} (frontend tried to clear)")
                            continue  # Skip this update, preserve existing value
                    elif field in {"sl_percentage", "tp_percentage"}:
                        if old_value != 0 and old_value != 0.0:
                            log.info(f"[WATCHLIST_PROTECT] Preserving user-set {field}={old_value} for {symbol} (frontend tried to clear)")
                            continue  # Skip this update, preserve existing value
                    elif field in {"sl_price", "tp_price"}:
                        if old_value != 0 and old_value != 0.0:
                            log.info(f"[WATCHLIST_PROTECT] Preserving user-set {field}={old_value} for {symbol} (frontend tried to clear)")
                            continue  # Skip this update, preserve existing value
                
                # Track changes to throttle-related parameters
                if field == "alert_cooldown_minutes" and old_value != new_value:
                    old_val_str = f"{old_value}" if old_value is not None else "default"
                    new_val_str = f"{new_value}" if new_value is not None else "default"
                    throttle_parameter_changes.append(f"alert_cooldown_minutes ({old_val_str} → {new_val_str})")
                elif field == "min_price_change_pct" and old_value != new_value:
                    old_val_str = f"{old_value}%" if old_value is not None else "default"
                    new_val_str = f"{new_value}%" if new_value is not None else "default"
                    throttle_parameter_changes.append(f"min_price_change_pct ({old_val_str} → {new_val_str})")
                # Track changes to strategy parameters (SL/TP percentages)
                # Note: sl_tp_mode changes are handled separately via strategy_changed detection
                elif field == "sl_percentage" and old_value != new_value:
                    old_val_str = f"{old_value}%" if old_value is not None else "default"
                    new_val_str = f"{new_value}%" if new_value is not None else "default"
                    strategy_parameter_changes.append(f"sl_percentage ({old_val_str} → {new_val_str})")
                elif field == "tp_percentage" and old_value != new_value:
                    old_val_str = f"{old_value}%" if old_value is not None else "default"
                    new_val_str = f"{new_value}%" if new_value is not None else "default"
                    strategy_parameter_changes.append(f"tp_percentage ({old_val_str} → {new_val_str})")
                
                # Log value changes for debugging
                if field in user_set_fields and old_value != new_value:
                    log.info(f"[WATCHLIST_UPDATE] {symbol}.{field}: {old_value} → {new_value}")
                
                setattr(existing_item, field, payload[field])
        
        # CRITICAL: Also update watchlist_master table (source of truth)
        try:
            master = db.query(WatchlistMaster).filter(
                WatchlistMaster.symbol == symbol,
                WatchlistMaster.exchange == exchange
            ).first()
            
            if master:
                # Update master table with same changes
                now = datetime.now(timezone.utc)
                for field in updatable_fields:
                    if field in payload and hasattr(master, field):
                        old_value = getattr(master, field, None)
                        new_value = payload[field]
                        if old_value != new_value:
                            setattr(master, field, new_value)
                            master.set_field_updated_at(field, now)
                if "signals" in payload:
                    import json
                    signals_value = payload["signals"]
                    master.signals = json.dumps(signals_value) if signals_value and not isinstance(signals_value, str) else signals_value
                    master.set_field_updated_at('signals', now)
                master.updated_at = now
            else:
                # Create master row if it doesn't exist
                master = WatchlistMaster(
                    symbol=symbol,
                    exchange=exchange,
                    is_deleted=False
                )
                # Copy all fields from existing_item
                for field in updatable_fields:
                    if hasattr(existing_item, field) and hasattr(master, field):
                        setattr(master, field, getattr(existing_item, field))
                if hasattr(existing_item, 'signals'):
                    import json
                    master.signals = json.dumps(existing_item.signals) if existing_item.signals and not isinstance(existing_item.signals, str) else existing_item.signals
                db.add(master)
        except Exception as master_err:
            log.warning(f"Error updating watchlist_master in POST /dashboard: {master_err}")

        db.commit()
        db.refresh(existing_item)
        
        # Reset throttle state if throttle or strategy parameters changed
        # But only if strategy fields (sl_tp_mode, preset, risk_mode) didn't change
        # (those are handled by strategy_changed check later)
        all_parameter_changes = throttle_parameter_changes + strategy_parameter_changes
        strategy_fields_in_payload = "sl_tp_mode" in payload or "preset" in payload or "risk_mode" in payload
        if all_parameter_changes and not strategy_fields_in_payload:
            try:
                from app.services.strategy_profiles import resolve_strategy_profile
                from app.services.signal_throttle import build_strategy_key, reset_throttle_state
                strategy_profile = resolve_strategy_profile(existing_item.symbol, db=db, watchlist_item=existing_item)
                strategy_key = build_strategy_key(
                    strategy_profile[0],  # strategy_type
                    strategy_profile[1]   # risk_approach
                )
                # Create a reason string with all changed parameters
                change_reason = ", ".join(all_parameter_changes)
                reset_throttle_state(
                    db, 
                    symbol=existing_item.symbol, 
                    strategy_key=strategy_key,
                    parameter_change_reason=change_reason
                )
                log.info(f"🔄 [PARAMS] Reset throttle state for {existing_item.symbol} - {change_reason}")
            except Exception as throttle_err:
                log.warning(f"⚠️ [PARAMS] Failed to reset throttle state for {existing_item.symbol}: {throttle_err}", exc_info=True)
        
        # Enrich with MarketData before returning
        md = _get_market_data_for_symbol(db, existing_item.symbol)
        return _serialize_watchlist_item(existing_item, market_data=md, db=db)

    # No existing row: create a new item.
    item = WatchlistItem(
        symbol=symbol,
        exchange=exchange,
        # BEHAVIOR CHANGE: Default alert_enabled to False (was True previously)
        # This prevents unwanted alerts for coins added via API.
        # To enable alerts, the caller MUST explicitly set alert_enabled=True in the request payload.
        # This is a security/safety measure to prevent alert spam from accidentally added coins.
        alert_enabled=payload.get("alert_enabled", False),
        buy_alert_enabled=payload.get("buy_alert_enabled", False),
        sell_alert_enabled=payload.get("sell_alert_enabled", False),
        trade_enabled=payload.get("trade_enabled", False),
        trade_amount_usd=payload.get("trade_amount_usd"),
        trade_on_margin=payload.get("trade_on_margin", False),
        sl_tp_mode=payload.get("sl_tp_mode"),
        min_price_change_pct=payload.get("min_price_change_pct"),
        alert_cooldown_minutes=payload.get("alert_cooldown_minutes"),
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
    
    # CRITICAL: Also create watchlist_master row (source of truth)
    try:
        master = WatchlistMaster(
            symbol=symbol,
            exchange=exchange,
            is_deleted=False,
            buy_target=item.buy_target,
            take_profit=item.take_profit,
            stop_loss=item.stop_loss,
            trade_enabled=item.trade_enabled or False,
            trade_amount_usd=item.trade_amount_usd,
            trade_on_margin=item.trade_on_margin or False,
            alert_enabled=item.alert_enabled or False,
            buy_alert_enabled=getattr(item, 'buy_alert_enabled', False) or False,
            sell_alert_enabled=getattr(item, 'sell_alert_enabled', False) or False,
            sl_tp_mode=item.sl_tp_mode or "conservative",
            min_price_change_pct=item.min_price_change_pct,
            alert_cooldown_minutes=item.alert_cooldown_minutes,
            sl_percentage=item.sl_percentage,
            tp_percentage=item.tp_percentage,
            sl_price=item.sl_price,
            tp_price=item.tp_price,
            notes=item.notes,
            signals=json.dumps(item.signals) if item.signals and not isinstance(item.signals, str) else (item.signals if item.signals else None),
            skip_sl_tp_reminder=item.skip_sl_tp_reminder or False,
            order_status=item.order_status or "PENDING",
            order_date=item.order_date,
            purchase_price=item.purchase_price,
            quantity=item.quantity,
            sold=item.sold or False,
            sell_price=item.sell_price,
            price=item.price,
            rsi=item.rsi,
            atr=item.atr,
            ma50=item.ma50,
            ma200=item.ma200,
            ema10=item.ema10,
            res_up=item.res_up,
            res_down=item.res_down,
        )
        db.add(master)
        db.commit()
        db.refresh(master)
        log.info(f"✅ Created watchlist_master row for {symbol}")
    except Exception as master_err:
        log.warning(f"Error creating watchlist_master in POST /dashboard: {master_err}")
        db.rollback()
        # Continue anyway - master table will be seeded on next GET request
    
    # Calculate and save TP/SL values if they're blank
    md = _get_market_data_for_symbol(db, item.symbol)
    if md and (item.sl_price is None or item.tp_price is None):
        current_price = md.price if md.price is not None else item.price
        current_atr = md.atr if md.atr is not None else item.atr
        
        if current_price and current_price > 0:
            calculated_sl, calculated_tp = _calculate_tp_sl_from_strategy(
                symbol=item.symbol,
                price=current_price,
                atr=current_atr,
                watchlist_item=item,
                db=db
            )
            
            # Save calculated values to database if they're None
            updated = False
            if calculated_sl is not None and item.sl_price is None:
                item.sl_price = calculated_sl
                updated = True
                log.debug(f"Saved calculated sl_price for new item {item.symbol}: {calculated_sl}")
            
            if calculated_tp is not None and item.tp_price is None:
                item.tp_price = calculated_tp
                updated = True
                log.debug(f"Saved calculated tp_price for new item {item.symbol}: {calculated_tp}")
            
            if updated:
                try:
                    db.commit()
                    db.refresh(item)
                except Exception as save_err:
                    log.warning(f"Failed to save calculated TP/SL for new item {item.symbol}: {save_err}")
                    db.rollback()
    
    # Enrich with MarketData before returning
    return _serialize_watchlist_item(item, market_data=md, db=db)


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

    # SAFETY: The dashboard sometimes sends is_deleted in the payload when toggling alerts.
    # If this hits a deleted duplicate row, flipping is_deleted=False can violate the
    # unique constraint (uq_watchlist_symbol_exchange_active). We:
    # - Never apply is_deleted via this endpoint (handled by dedicated endpoints)
    # - If the requested row is deleted but an active canonical row exists, we update the
    #   canonical row instead of restoring the duplicate.
    payload = dict(payload or {})
    requested_restore = ("is_deleted" in payload and payload.get("is_deleted") is False)
    payload.pop("is_deleted", None)

    # If the row we are updating is deleted, redirect the update to an active canonical row
    # for the same (symbol, exchange) to avoid constraint violations.
    try:
        symbol_upper = (getattr(item, "symbol", "") or "").upper()
        exchange_upper = (getattr(item, "exchange", "CRYPTO_COM") or "CRYPTO_COM").upper()
    except Exception:
        symbol_upper = None
        exchange_upper = None

    if symbol_upper and hasattr(item, "is_deleted") and getattr(item, "is_deleted", False):
        canonical = None
        try:
            q = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol_upper)
            if hasattr(WatchlistItem, "exchange") and exchange_upper:
                q = q.filter(WatchlistItem.exchange == exchange_upper)
            try:
                q = q.filter(WatchlistItem.is_deleted == False)
            except Exception:
                pass
            canonical = q.order_by(WatchlistItem.created_at.desc(), WatchlistItem.id.desc()).first()
        except Exception:
            canonical = None

        if canonical and canonical.id != item.id:
            log.warning(
                "[WATCHLIST_UPDATE_REDIRECT] Requested update for deleted duplicate id=%s symbol=%s exchange=%s -> canonical_id=%s",
                item.id,
                symbol_upper,
                exchange_upper,
                canonical.id,
            )
            item = canonical
            item_id = canonical.id
        elif requested_restore:
            # No active canonical row exists: allow restore explicitly requested by payload.
            # (Still safer to prefer the dedicated restore endpoint.)
            try:
                item.is_deleted = False
            except Exception:
                pass
    
    # CRITICAL: Normalize boolean fields - convert None to False to prevent NULL in database
    # This ensures data integrity even if frontend sends null/undefined values
    boolean_fields = ["alert_enabled", "buy_alert_enabled", "sell_alert_enabled", 
                      "trade_enabled", "trade_on_margin", "sold", "skip_sl_tp_reminder"]
    for field in boolean_fields:
        if field in payload and payload[field] is None:
            payload[field] = False
    
    # Track what was updated for the message
    updates = []
    alert_enabled_old_value = None  # Store old value for logging after verification
    alert_enabled_was_updated = False  # Track if alert_enabled update was attempted
    
    # Track old strategy before update to reset throttle state if strategy changes
    # CRITICAL: Strategy is determined by resolve_strategy_profile which reads from trading_config.json
    # We need to resolve the old strategy BEFORE the update to detect changes
    old_sl_tp_mode = item.sl_tp_mode if hasattr(item, 'sl_tp_mode') else None
    # Also check if preset/risk_mode are changing (frontend may send these instead of sl_tp_mode)
    old_preset = getattr(item, 'preset', None)
    old_risk_mode = getattr(item, 'risk_mode', None)
    
    # Resolve old strategy profile BEFORE update (strategy comes from trading_config.json, not just database)
    # Also check config file modification time to detect if config was recently updated
    old_strategy_profile = None
    old_strategy_key = None
    config_file_mtime_before = None
    try:
        from app.services.strategy_profiles import resolve_strategy_profile
        from app.services.signal_throttle import build_strategy_key
        from app.services.config_loader import CONFIG_PATH
        import os
        
        # Check config file modification time before update
        if CONFIG_PATH and CONFIG_PATH.exists():
            config_file_mtime_before = os.path.getmtime(CONFIG_PATH)
        
        old_strategy_profile = resolve_strategy_profile(item.symbol, db=db, watchlist_item=item)
        old_strategy_key = build_strategy_key(old_strategy_profile[0], old_strategy_profile[1])
    except Exception as old_strategy_err:
        log.debug(f"Could not resolve old strategy for {item.symbol}: {old_strategy_err}")
    
    strategy_changed = False
    
    # CRITICAL: Store old values BEFORE applying updates for config change detection
    # These are needed for the throttling reset logic (per ALERTAS_Y_ORDENES_NORMAS.md)
    trade_enabled_old_value = None
    if "trade_enabled" in payload:
        trade_enabled_old_value = item.trade_enabled
        old_value = item.trade_enabled
        new_value = payload["trade_enabled"]
        if old_value != new_value:
            updates.append(f"TRADE: {'YES' if new_value else 'NO'}")
            # Log when trade_enabled is being changed, especially when disabling
            if new_value is False and old_value is True:
                # Count how many coins currently have trade_enabled=True
                current_trade_enabled_count = db.query(WatchlistItem).filter(
                    WatchlistItem.trade_enabled == True,
                    WatchlistItem.is_deleted == False
                ).count()
                log.warning(
                    f"[TRADE_ENABLED_DISABLE] Disabling trade_enabled for {item.symbol}. "
                    f"Current count of trade_enabled=True coins: {current_trade_enabled_count}. "
                    f"This should only happen if user explicitly disables it."
                )
            elif new_value is True and old_value is False:
                # Count how many coins will have trade_enabled=True after this change
                current_trade_enabled_count = db.query(WatchlistItem).filter(
                    WatchlistItem.trade_enabled == True,
                    WatchlistItem.is_deleted == False
                ).count()
                log.info(
                    f"[TRADE_ENABLED_ENABLE] Enabling trade_enabled for {item.symbol}. "
                    f"Current count of trade_enabled=True coins: {current_trade_enabled_count}. "
                    f"After this change: {current_trade_enabled_count + 1}"
                )
    
    alert_enabled_old_value = None
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
    
    # Track old values for config change detection (needed for throttling reset)
    buy_alert_enabled_old_value = getattr(item, "buy_alert_enabled", False) if "buy_alert_enabled" in payload else None
    sell_alert_enabled_old_value = getattr(item, "sell_alert_enabled", False) if "sell_alert_enabled" in payload else None
    min_price_change_pct_old_value = getattr(item, "min_price_change_pct", None) if "min_price_change_pct" in payload else None
    trade_amount_usd_old_value = getattr(item, "trade_amount_usd", None) if "trade_amount_usd" in payload else None
    
    if "buy_alert_enabled" in payload:
        old_value = buy_alert_enabled_old_value
        new_value = payload["buy_alert_enabled"]
        if old_value != new_value:
            updates.append(f"BUY alert: {'YES' if new_value else 'NO'}")
    
    if "sell_alert_enabled" in payload:
        old_value = sell_alert_enabled_old_value
        new_value = payload["sell_alert_enabled"]
        if old_value != new_value:
            updates.append(f"SELL alert: {'YES' if new_value else 'NO'}")
    
    # Check if strategy (sl_tp_mode) is changing
    if "sl_tp_mode" in payload:
        new_sl_tp_mode = payload.get("sl_tp_mode")
        if old_sl_tp_mode != new_sl_tp_mode:
            strategy_changed = True
            updates.append(f"STRATEGY: {old_sl_tp_mode or 'default'} → {new_sl_tp_mode}")
    
    # Also check if preset or risk_mode are changing (frontend may send these separately)
    if "preset" in payload or "risk_mode" in payload:
        new_preset = payload.get("preset")
        new_risk_mode = payload.get("risk_mode")
        # If either preset or risk_mode changed, consider strategy changed
        if (new_preset is not None and new_preset != old_preset) or (new_risk_mode is not None and new_risk_mode != old_risk_mode):
            strategy_changed = True
            old_strategy_str = f"{old_preset or 'default'}-{old_risk_mode or 'default'}"
            new_strategy_str = f"{new_preset or old_preset or 'default'}-{new_risk_mode or old_risk_mode or 'default'}"
            updates.append(f"STRATEGY: {old_strategy_str} → {new_strategy_str}")
    
    # Log the update attempt for debugging
    log.info(f"[WATCHLIST_UPDATE] PUT /dashboard/{item_id} for {item.symbol}: updating fields {list(payload.keys())}")
    for key, value in payload.items():
        if key in {"trade_amount_usd", "sl_percentage", "tp_percentage", "sl_price", "tp_price"}:
            old_val = getattr(item, key, None)
            log.info(f"[WATCHLIST_UPDATE] {item.symbol}.{key}: {old_val} → {value}")
    
    _apply_watchlist_updates(item, payload)
    
    # If trade_enabled was changed, check count before and after commit
    trade_enabled_changed = "trade_enabled" in payload and trade_enabled_old_value != payload.get("trade_enabled")
    count_before = None
    if trade_enabled_changed:
        count_before = db.query(WatchlistItem).filter(
            WatchlistItem.trade_enabled == True,
            WatchlistItem.is_deleted == False
        ).count()
    
    try:
        db.commit()
        log.info(f"[WATCHLIST_UPDATE] Successfully committed update for {item.symbol}")
        
        # After commit, verify count didn't change unexpectedly
        if trade_enabled_changed:
            count_after = db.query(WatchlistItem).filter(
                WatchlistItem.trade_enabled == True,
                WatchlistItem.is_deleted == False
            ).count()
            new_trade_enabled_value = payload.get("trade_enabled")
            expected_change = 1 if new_trade_enabled_value else -1
            expected_count = (count_before or 0) + expected_change
            if count_after != expected_count:
                log.error(
                    f"[TRADE_ENABLED_COUNT_MISMATCH] PUT /dashboard/{item_id} for {item.symbol}: "
                    f"Unexpected count change! Before: {count_before}, After: {count_after}, "
                    f"Expected: {expected_count}. This suggests another coin was automatically disabled!"
                )
            else:
                log.info(
                    f"[TRADE_ENABLED_COUNT_VERIFIED] PUT /dashboard/{item_id} for {item.symbol}: "
                    f"Count verified. Before: {count_before}, After: {count_after}, Expected: {expected_count}"
                )
        
        # CRITICAL: Also update watchlist_master table (source of truth)
        try:
            symbol_upper = (item.symbol or "").upper()
            exchange_upper = (item.exchange or "CRYPTO_COM").upper()
            master = db.query(WatchlistMaster).filter(
                WatchlistMaster.symbol == symbol_upper,
                WatchlistMaster.exchange == exchange_upper
            ).first()
            
            if master:
                now = datetime.now(timezone.utc)
                for field, value in payload.items():
                    if field == "is_deleted":
                        continue
                    if hasattr(master, field):
                        old_value = getattr(master, field, None)
                        # CRITICAL: Handle numeric fields (trade_amount_usd) - compare properly including None vs 0
                        if field == "trade_amount_usd":
                            # Always update if value is provided (including 0 or None)
                            old_float = float(old_value) if old_value is not None else None
                            new_float = float(value) if value is not None else None
                            if old_float != new_float:
                                setattr(master, field, value)
                                master.set_field_updated_at(field, now)
                                log.info(f"[WATCHLIST_MASTER_UPDATE] {symbol_upper}.{field}: {old_value} → {value}")
                        elif field == "trade_on_margin":
                            # Handle boolean field - ensure proper comparison
                            old_bool = bool(old_value) if old_value is not None else False
                            new_bool = bool(value) if value is not None else False
                            if old_bool != new_bool:
                                setattr(master, field, value)
                                master.set_field_updated_at(field, now)
                                log.info(f"[WATCHLIST_MASTER_UPDATE] {symbol_upper}.{field}: {old_value} → {value}")
                        elif old_value != value:
                            setattr(master, field, value)
                            master.set_field_updated_at(field, now)
                if "signals" in payload:
                    import json
                    signals_value = payload["signals"]
                    master.signals = json.dumps(signals_value) if signals_value and not isinstance(signals_value, str) else signals_value
                    master.set_field_updated_at('signals', now)
                master.updated_at = now
                db.commit()
                log.debug(f"✅ Updated watchlist_master for {symbol_upper} via PUT /dashboard/{item_id}")
            else:
                # Master row doesn't exist - will be created by seeding on next GET request
                log.debug(f"watchlist_master row not found for {symbol_upper}, will be seeded on next GET request")
        except Exception as master_err:
            log.warning(f"Error updating watchlist_master in PUT /dashboard/{item_id}: {master_err}")
    except IntegrityError as ie:
        # Handle unique constraint when a deleted duplicate row is being restored implicitly.
        db.rollback()
        err_text = str(getattr(ie, "orig", ie))
        if "uq_watchlist_symbol_exchange_active" in err_text or "watchlist_symbol_exchange_active" in err_text:
            # Try to update canonical active row instead of restoring/updating a duplicate.
            if symbol_upper:
                q = db.query(WatchlistItem).filter(WatchlistItem.symbol == symbol_upper)
                if hasattr(WatchlistItem, "exchange") and exchange_upper:
                    q = q.filter(WatchlistItem.exchange == exchange_upper)
                try:
                    q = q.filter(WatchlistItem.is_deleted == False)
                except Exception:
                    pass
                canonical = q.order_by(WatchlistItem.created_at.desc(), WatchlistItem.id.desc()).first()
                if canonical:
                    log.warning(
                        "[WATCHLIST_UNIQUE_VIOLATION] Retrying update on canonical id=%s symbol=%s exchange=%s (requested_id=%s)",
                        canonical.id,
                        symbol_upper,
                        exchange_upper,
                        item_id,
                    )
                    _apply_watchlist_updates(canonical, payload)
                    db.commit()
                    
                    # Note: watchlist_master sync removed - WatchlistItem is now single source of truth
                    # Master table updates are no longer needed
                    
                    item = canonical
                    item_id = canonical.id
                else:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Duplicate active watchlist row exists for {symbol_upper}; cannot restore/update this row.",
                    )
            else:
                raise HTTPException(status_code=409, detail="Duplicate active watchlist row exists; update rejected.")
        else:
                raise

    db.refresh(item)
    
    # CANONICAL: Detect ANY configuration change that should trigger throttling reset
    # Per ALERTAS_Y_ORDENES_NORMAS.md section 3.4, these fields count as "cambio de configuración":
    # - alert_enabled, buy_alert_enabled, sell_alert_enabled
    # - trade_enabled
    # - strategy_id or strategy_name (strategy changes - handled separately below)
    # - min_price_change_pct
    # - trade_amount_usd
    # - Any other configuration field
    
    config_changed = False
    config_change_reasons = []
    
    # Check alert_enabled change (using old value captured BEFORE update)
    if "alert_enabled" in payload and alert_enabled_old_value is not None:
        new_value = payload.get("alert_enabled")
        old_comparison = alert_enabled_old_value if alert_enabled_old_value is not None else False
        new_comparison = new_value if new_value is not None else False
        if old_comparison != new_comparison:
            config_changed = True
            config_change_reasons.append(f"alert_enabled ({'YES' if old_comparison else 'NO'} → {'YES' if new_comparison else 'NO'})")
    
    # Check buy_alert_enabled change
    if "buy_alert_enabled" in payload and buy_alert_enabled_old_value is not None:
        new_value = payload.get("buy_alert_enabled")
        if buy_alert_enabled_old_value != new_value:
            config_changed = True
            config_change_reasons.append(f"buy_alert_enabled ({'YES' if buy_alert_enabled_old_value else 'NO'} → {'YES' if new_value else 'NO'})")
            # PHASE 0: Structured logging for UI toggle
            log.info(
                f"[UI_TOGGLE] {item.symbol} BUY alert toggle | "
                f"previous_state={'ENABLED' if buy_alert_enabled_old_value else 'DISABLED'} | "
                f"new_state={'ENABLED' if new_value else 'DISABLED'}"
            )
    
    # Check sell_alert_enabled change
    if "sell_alert_enabled" in payload and sell_alert_enabled_old_value is not None:
        new_value = payload.get("sell_alert_enabled")
        if sell_alert_enabled_old_value != new_value:
            config_changed = True
            config_change_reasons.append(f"sell_alert_enabled ({'YES' if sell_alert_enabled_old_value else 'NO'} → {'YES' if new_value else 'NO'})")
            # PHASE 0: Structured logging for UI toggle
            log.info(
                f"[UI_TOGGLE] {item.symbol} SELL alert toggle | "
                f"previous_state={'ENABLED' if sell_alert_enabled_old_value else 'DISABLED'} | "
                f"new_state={'ENABLED' if new_value else 'DISABLED'}"
            )
    
    # Check trade_enabled change
    if "trade_enabled" in payload and trade_enabled_old_value is not None:
        new_value = payload.get("trade_enabled")
        if trade_enabled_old_value != new_value:
            config_changed = True
            config_change_reasons.append(f"trade_enabled ({'YES' if trade_enabled_old_value else 'NO'} → {'YES' if new_value else 'NO'})")
    
    # Check min_price_change_pct change
    if "min_price_change_pct" in payload and min_price_change_pct_old_value is not None:
        new_value = payload.get("min_price_change_pct")
        if min_price_change_pct_old_value != new_value:
            config_changed = True
            config_change_reasons.append(f"min_price_change_pct ({min_price_change_pct_old_value} → {new_value})")
    
    # Check trade_amount_usd change
    if "trade_amount_usd" in payload and trade_amount_usd_old_value is not None:
        new_value = payload.get("trade_amount_usd")
        # Compare as floats to handle numeric comparison
        old_float = float(trade_amount_usd_old_value) if trade_amount_usd_old_value is not None else None
        new_float = float(new_value) if new_value is not None else None
        if old_float != new_float:
            config_changed = True
            config_change_reasons.append(f"trade_amount_usd (${trade_amount_usd_old_value} → ${new_value})")
    
    # Reset throttle state for ANY configuration change (per documentation)
    # NOTE: Strategy changes are handled separately below (they need special handling for old/new strategy keys)
    # This handles non-strategy config changes: alert flags, trade_enabled, min_price_change_pct, trade_amount_usd
    if config_changed and not strategy_changed:
        try:
            from app.services.strategy_profiles import resolve_strategy_profile
            from app.services.signal_throttle import (
                build_strategy_key,
                reset_throttle_state,
                set_force_next_signal,
                compute_config_hash,
            )
            from app.models.signal_throttle import SignalThrottleState
            
            # Get current strategy (after update)
            strategy_profile = resolve_strategy_profile(item.symbol, db=db, watchlist_item=item)
            strategy_key = build_strategy_key(
                strategy_profile[0],  # strategy_type
                strategy_profile[1]   # risk_approach
            )

            # Compute hash from whitelisted config fields to avoid spurious resets
            config_snapshot = {
                "alert_enabled": getattr(item, "alert_enabled", False),
                "buy_alert_enabled": getattr(item, "buy_alert_enabled", False),
                "sell_alert_enabled": getattr(item, "sell_alert_enabled", False),
                "trade_enabled": getattr(item, "trade_enabled", False),
                "strategy_id": getattr(item, "strategy_id", None),
                "strategy_name": getattr(item, "sl_tp_mode", None),
                "min_price_change_pct": getattr(item, "min_price_change_pct", None),
                "trade_amount_usd": getattr(item, "trade_amount_usd", None),
            }
            new_config_hash = compute_config_hash(config_snapshot)

            existing_hash = None
            try:
                existing_state = (
                    db.query(SignalThrottleState)
                    .filter(
                        SignalThrottleState.symbol == item.symbol,
                        SignalThrottleState.strategy_key == strategy_key,
                        SignalThrottleState.side == "BUY",
                    )
                    .first()
                ) or (
                    db.query(SignalThrottleState)
                    .filter(
                        SignalThrottleState.symbol == item.symbol,
                        SignalThrottleState.strategy_key == strategy_key,
                        SignalThrottleState.side == "SELL",
                    )
                    .first()
                )
                if existing_state:
                    existing_hash = getattr(existing_state, "config_hash", None)
            except Exception as hash_err:
                log.debug(f"Could not read existing config_hash for {item.symbol}: {hash_err}")

            if existing_hash and existing_hash == new_config_hash:
                log.info(f"ℹ️ [CONFIG_CHANGE] No throttle reset: config hash unchanged for {item.symbol}")
                config_changed = False
                config_change_reasons = []
                config_hash_to_store = existing_hash
            else:
                config_hash_to_store = new_config_hash
            
            if config_changed or config_hash_to_store != existing_hash:
                # CANONICAL: Reset throttle state for configuration change
                # baseline_price := current price, last_sent_at unchanged, force_next_signal=True
                change_reason_str = ", ".join(config_change_reasons)
                current_price = getattr(item, "price", None)
                reset_throttle_state(
                    db, 
                    symbol=item.symbol, 
                    strategy_key=strategy_key,
                    current_price=current_price,
                    parameter_change_reason=f"CONFIG_CHANGE: {change_reason_str}",
                    config_hash=config_hash_to_store,
                )
                log.info(f"🔄 [CONFIG_CHANGE] Reset throttle state for {item.symbol} due to config changes: {change_reason_str}")
                
                # CANONICAL: Set force_next_signal for both BUY and SELL to allow immediate bypass
                set_force_next_signal(db, symbol=item.symbol, strategy_key=strategy_key, side="BUY", enabled=True)
                set_force_next_signal(db, symbol=item.symbol, strategy_key=strategy_key, side="SELL", enabled=True)
                log.info(f"⚡ [CONFIG_CHANGE] Set force_next_signal=True for {item.symbol} BUY/SELL - next signals will bypass throttle")
                
            # Also clear order creation limitations (allows immediate order creation)
            try:
                from app.services.signal_monitor import signal_monitor_service
                signal_monitor_service.clear_order_creation_limitations(item.symbol)
                log.info(f"🔄 [CONFIG_CHANGE] Cleared order creation limitations for {item.symbol}")
            except Exception as clear_err:
                log.warning(f"⚠️ [CONFIG_CHANGE] Failed to clear order creation limitations for {item.symbol}: {clear_err}")
            
            # CANONICAL: Evaluate signals immediately after config change and send alerts if criteria are met
            # This ensures that if the new configuration allows an alert (signal active + flags enabled),
            # the alert is sent immediately without waiting for the next monitor cycle
            try:
                from app.services.signal_monitor import signal_monitor_service
                # Refresh item to get latest values
                db.refresh(item)
                # Evaluate signals and send alerts if criteria are met
                signal_monitor_service._check_signal_for_coin_sync(db, item)
                log.info(f"⚡ [CONFIG_CHANGE] Evaluated signals immediately for {item.symbol} after config change - alert sent if criteria met")
            except Exception as eval_err:
                log.warning(f"⚠️ [CONFIG_CHANGE] Failed to evaluate signals immediately for {item.symbol}: {eval_err}", exc_info=True)
                
        except Exception as throttle_err:
            log.warning(f"⚠️ [CONFIG_CHANGE] Failed to reset throttle state for {item.symbol}: {throttle_err}", exc_info=True)
    
    # CRITICAL: Also check if strategy changed by comparing resolved strategy profiles
    # This catches changes in trading_config.json (preset) that aren't in the database payload
    # The strategy is determined by resolve_strategy_profile which reads from trading_config.json
    new_strategy_profile = None
    new_strategy_key = None
    try:
        from app.services.strategy_profiles import resolve_strategy_profile
        from app.services.signal_throttle import build_strategy_key
        from app.services.config_loader import CONFIG_PATH
        import os
        
        # Check if config file was modified (indicates strategy might have changed)
        config_file_modified = False
        if config_file_mtime_before and CONFIG_PATH and CONFIG_PATH.exists():
            config_file_mtime_after = os.path.getmtime(CONFIG_PATH)
            if config_file_mtime_after > config_file_mtime_before:
                config_file_modified = True
                log.info(f"🔄 [STRATEGY] Config file modified for {item.symbol} - strategy may have changed")
        
        new_strategy_profile = resolve_strategy_profile(item.symbol, db=db, watchlist_item=item)
        new_strategy_key = build_strategy_key(new_strategy_profile[0], new_strategy_profile[1])
        
        # If old and new strategy keys are different, strategy changed
        if old_strategy_key and new_strategy_key and old_strategy_key != new_strategy_key:
            strategy_changed = True
            log.info(f"🔄 [STRATEGY] Detected strategy change for {item.symbol}: {old_strategy_key} → {new_strategy_key} (from config comparison)")
        # FALLBACK: If config file was modified, assume strategy changed (even if keys are same, config might have changed)
        elif not strategy_changed and config_file_modified:
            strategy_changed = True
            log.info(f"🔄 [STRATEGY] Config file modified for {item.symbol} - resetting throttle as safety measure")
        # FALLBACK: If we couldn't detect change via comparison, but payload contains strategy-related fields, assume strategy changed
        elif not strategy_changed and ("preset" in payload or "risk_mode" in payload or "sl_tp_mode" in payload):
            strategy_changed = True
            log.info(f"🔄 [STRATEGY] Assuming strategy change for {item.symbol} (strategy-related fields in payload) - resetting throttle as safety measure")
    except Exception as new_strategy_err:
        log.debug(f"Could not resolve new strategy for {item.symbol}: {new_strategy_err}")
    
    # When trade_enabled is toggled to YES, also enable alert flags (keep for backward compatibility)
    if "trade_enabled" in payload:
        new_value = payload.get("trade_enabled")
        
        # When trade_enabled is toggled to YES, also enable alert_enabled, buy_alert_enabled and sell_alert_enabled
        # CRITICAL: Use new_value directly (from payload) instead of item.trade_enabled
        # This ensures we enable alerts even if item.trade_enabled hasn't been refreshed yet
        if new_value:
            # CRITICAL: Enable alert_enabled (master switch) when trade is enabled
            # This is required for alerts to be sent (both alert_enabled AND buy_alert_enabled must be True)
            if not item.alert_enabled:
                item.alert_enabled = True
                log.info(f"⚡ [TRADE] Auto-enabled alert_enabled (master switch) for {item.symbol} (required for all alerts)")
            # CRITICAL: Enable buy_alert_enabled and sell_alert_enabled when trade is enabled
            # This ensures alerts are sent when signals are detected
            if not item.buy_alert_enabled:
                item.buy_alert_enabled = True
                log.info(f"⚡ [TRADE] Auto-enabled buy_alert_enabled for {item.symbol} (required for BUY alerts)")
            if not item.sell_alert_enabled:
                item.sell_alert_enabled = True
                log.info(f"⚡ [TRADE] Auto-enabled sell_alert_enabled for {item.symbol} (required for SELL alerts)")
            db.commit()
            db.refresh(item)
    
    # When strategy (sl_tp_mode) changes, reset throttle state for all strategies and set force_next_signal for new strategy
    if strategy_changed:
        try:
            from app.services.strategy_profiles import resolve_strategy_profile, _parse_preset
            from app.services.signal_throttle import build_strategy_key, reset_throttle_state, set_force_next_signal
            from app.models.signal_throttle import SignalThrottleState
            
            # Use the strategy keys we already resolved above (before and after update)
            # If we didn't resolve them above, try to resolve now
            if not old_strategy_key and old_strategy_profile:
                old_strategy_key = build_strategy_key(old_strategy_profile[0], old_strategy_profile[1])
            
            if not new_strategy_key and new_strategy_profile:
                new_strategy_key = build_strategy_key(
                    new_strategy_profile[0],  # strategy_type
                    new_strategy_profile[1]   # risk_approach
                )
            
            # If still no keys, resolve them now
            if not old_strategy_key:
                try:
                    # Try to get old strategy from old_sl_tp_mode, preset, or risk_mode
                    if old_sl_tp_mode or old_preset or old_risk_mode:
                        # Create a temporary watchlist item with old values to resolve strategy
                        old_item = type('obj', (object,), {
                            'sl_tp_mode': old_sl_tp_mode,
                            'preset': old_preset,
                            'risk_mode': old_risk_mode
                        })()
                        old_strategy_profile = resolve_strategy_profile(item.symbol, db=db, watchlist_item=old_item)
                        old_strategy_key = build_strategy_key(old_strategy_profile[0], old_strategy_profile[1])
                except Exception as parse_err:
                    log.debug(f"Could not resolve old strategy (sl_tp_mode={old_sl_tp_mode}, preset={old_preset}, risk_mode={old_risk_mode}): {parse_err}")
            
            if not new_strategy_key:
                new_strategy_profile = resolve_strategy_profile(item.symbol, db=db, watchlist_item=item)
                new_strategy_key = build_strategy_key(
                    new_strategy_profile[0],  # strategy_type
                    new_strategy_profile[1]   # risk_approach
                )
            
            # Reset throttle state for old strategy (if different from new)
            if old_strategy_key and old_strategy_key != new_strategy_key:
                reset_throttle_state(
                    db, 
                    symbol=item.symbol, 
                    strategy_key=old_strategy_key,
                    parameter_change_reason=f"strategy changed (old: {old_strategy_key})"
                )
                log.info(f"🔄 [STRATEGY] Reset throttle state for {item.symbol} old strategy: {old_strategy_key}")
            
            # Also reset throttle state for new strategy to ensure clean slate
            strategy_change_reason = f"strategy changed ({old_strategy_key or 'unknown'} → {new_strategy_key})"
            reset_throttle_state(
                db, 
                symbol=item.symbol, 
                strategy_key=new_strategy_key,
                parameter_change_reason=strategy_change_reason
            )
            log.info(f"🔄 [STRATEGY] Reset throttle state for {item.symbol} new strategy: {new_strategy_key}")
            
            # Set force_next_signal for new strategy to allow immediate signals
            set_force_next_signal(db, symbol=item.symbol, strategy_key=new_strategy_key, side="BUY", enabled=True)
            set_force_next_signal(db, symbol=item.symbol, strategy_key=new_strategy_key, side="SELL", enabled=True)
            log.info(f"⚡ [STRATEGY] Set force_next_signal for {item.symbol} BUY/SELL with new strategy {new_strategy_key} - next evaluation will bypass throttle")
            
            # CRITICAL: Clear order creation limitations in SignalMonitorService
            # This clears last_order_price, orders_count tracking, order_creation_locks, and alert state
            # so that orders can be created immediately when new strategy signals are detected
            try:
                from app.services.signal_monitor import signal_monitor_service
                signal_monitor_service.clear_order_creation_limitations(item.symbol)
                log.info(f"🔄 [STRATEGY] Cleared order creation limitations for {item.symbol} - orders can be created immediately")
            except Exception as clear_err:
                log.warning(f"⚠️ [STRATEGY] Failed to clear order creation limitations for {item.symbol}: {clear_err}", exc_info=True)
            
            # CANONICAL: Evaluate signals immediately after strategy change and send alerts if criteria are met
            # This ensures that if the new strategy allows an alert (signal active + flags enabled),
            # the alert is sent immediately without waiting for the next monitor cycle
            try:
                from app.services.signal_monitor import signal_monitor_service
                # Refresh item to get latest values
                db.refresh(item)
                # Evaluate signals and send alerts if criteria are met
                signal_monitor_service._check_signal_for_coin_sync(db, item)
                log.info(f"⚡ [STRATEGY] Evaluated signals immediately for {item.symbol} after strategy change - alert sent if criteria met")
            except Exception as eval_err:
                log.warning(f"⚠️ [STRATEGY] Failed to evaluate signals immediately for {item.symbol}: {eval_err}", exc_info=True)
            
        except Exception as strategy_err:
            log.warning(f"⚠️ [STRATEGY] Failed to reset throttle state for {item.symbol}: {strategy_err}", exc_info=True)
    
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
    
    # CRITICAL: Verify trade_enabled was actually saved to database
    # This prevents the issue where trade_enabled gets deactivated immediately after activation
    if "trade_enabled" in payload and trade_enabled_old_value is not None:
        expected_value = payload["trade_enabled"]
        # Only verify and log if the value actually changed
        if trade_enabled_old_value != expected_value:
            db.refresh(item)  # Ensure we have latest from DB
            actual_value = item.trade_enabled
            if actual_value != expected_value:
                log.error(f"❌ SYNC ERROR: trade_enabled mismatch for {item.symbol} ({item_id}): "
                         f"Expected {expected_value}, but DB has {actual_value}. "
                         f"This is the bug causing immediate deactivation! Attempting to fix...")
                item.trade_enabled = expected_value
                db.commit()
                db.refresh(item)
                log.info(f"✅ Fixed trade_enabled sync issue for {item.symbol}")
            else:
                # Log successful update only after verification confirms it was saved correctly
                log.info(f"✅ Updated trade_enabled for {item.symbol} ({item_id}): {trade_enabled_old_value} -> {expected_value}")
    
    # Enrich with MarketData before returning
    md = _get_market_data_for_symbol(db, item.symbol)
    result = _serialize_watchlist_item(item, market_data=md, db=db)
    
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
    """Get a watchlist item by symbol (includes deleted items).
    
    Enriches the item with MarketData (price, rsi, ma50, ma200, ema10, atr) before returning.
    """
    symbol = (symbol or "").upper()
    # Deterministic selection when duplicates exist:
    # - Prefer active rows; if all are deleted, return the "best" deleted row.
    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.symbol == symbol)
        .order_by(WatchlistItem.id.desc())
        .all()
    )
    item = select_preferred_watchlist_item(items, symbol)
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    
    # Enrich with MarketData
    md = _get_market_data_for_symbol(db, symbol)
    return _serialize_watchlist_item(item, market_data=md, db=db)


@router.put("/dashboard/symbol/{symbol}/restore")
def restore_watchlist_item_by_symbol(symbol: str, db: Session = Depends(get_db)):
    """Restore a deleted watchlist item by symbol (set is_deleted=False)."""
    symbol = (symbol or "").upper()
    # Include deleted rows in lookup so restore works even if the only row is deleted.
    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.symbol == symbol)
        .order_by(WatchlistItem.id.desc())
        .all()
    )
    item = select_preferred_watchlist_item(items, symbol)
    if not item:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    
    # Check if already active
    is_deleted = getattr(item, "is_deleted", False)
    if not is_deleted:
        # Enrich with MarketData before returning
            md = _get_market_data_for_symbol(db, symbol)
            return {
                "ok": True,
                "message": f"{symbol} is already active (not deleted)",
                "item": _serialize_watchlist_item(item, market_data=md, db=db)
            }
    
    # Restore the item
    try:
        if _soft_delete_supported(db) and hasattr(item, "is_deleted"):
            item.is_deleted = False
            # Preserve existing alert_enabled value instead of resetting
            # This prevents alerts from being deactivated when items are restored
            # item.alert_enabled is preserved (not reset)
            db.commit()
            db.refresh(item)
            log.info(f"✅ Restored watchlist item {symbol} (ID: {item.id})")
            
            # Enrich with MarketData before returning
            md = _get_market_data_for_symbol(db, item.symbol)
            return {
                "ok": True,
                "message": f"{symbol} has been restored",
                "item": _serialize_watchlist_item(item, market_data=md, db=db)
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
    # CRITICAL: Use get_canonical_watchlist_item to handle duplicate entries correctly
    # This ensures we always get the same canonical entry when there are duplicates
    item = get_canonical_watchlist_item(db, symbol)
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


def _verify_diagnostics_auth(request: Request) -> None:
    """
    Internal auth guard for diagnostics endpoints.
    Requires ENABLE_DIAGNOSTICS_ENDPOINTS=1 and X-Diagnostics-Key header.
    Returns 404 (not 401) to reduce endpoint discoverability.
    Do not log the key.
    """
    import os
    
    # Check if diagnostics endpoints are enabled
    if os.getenv("ENABLE_DIAGNOSTICS_ENDPOINTS", "0") != "1":
        raise HTTPException(status_code=404, detail="Not found")
    
    # Check for diagnostics API key
    expected_key = os.getenv("DIAGNOSTICS_API_KEY")
    if not expected_key:
        raise HTTPException(status_code=404, detail="Not found")
    
    # Verify header (case-insensitive)
    provided_key = request.headers.get("X-Diagnostics-Key") or request.headers.get("x-diagnostics-key")
    if not provided_key or provided_key != expected_key:
        raise HTTPException(status_code=404, detail="Not found")
    
    # Auth passed - continue


@router.get("/diagnostics/portfolio-verify", tags=["diagnostics"])
def diagnostics_portfolio_verify(
    request: Request,
    db: Session = Depends(get_db),
    include_breakdown: bool = False
):
    """
    Verify that dashboard "Total Value" (NET Wallet Balance) matches Crypto.com "Wallet Balance".
    
    This endpoint:
    1. Gets dashboard NET from cached portfolio summary (same value shown in UI)
    2. Fetches fresh from Crypto.com API and calculates NET the same way
    3. Compares them and returns pass/fail
    
    Query params:
    - include_breakdown: If 1 and PORTFOLIO_DEBUG=1, includes asset-by-asset breakdown
    
    Protected by:
    - ENABLE_DIAGNOSTICS_ENDPOINTS=1 environment variable
    - X-Diagnostics-Key header (DIAGNOSTICS_API_KEY env var)
    """
    import os
    from app.services.brokers.crypto_com_trade import trade_client
    from app.services.portfolio_cache import _normalize_currency_name, get_crypto_prices
    from datetime import datetime, timezone
    from fastapi import Query
    
    # Security: Verify diagnostics auth
    _verify_diagnostics_auth(request)
    
    VERIFICATION_DEBUG = os.getenv("VERIFICATION_DEBUG", "0") == "1"
    PORTFOLIO_DEBUG = os.getenv("PORTFOLIO_DEBUG", "0") == "1"
    
    try:
        # Step 1: Get dashboard NET value (same as shown in UI "Total Value")
        portfolio_summary = get_portfolio_summary(db)
        dashboard_net_usd = portfolio_summary.get("total_usd", 0.0)  # NET Wallet Balance
        dashboard_gross_usd = portfolio_summary.get("total_assets_usd", 0.0)  # Raw gross assets
        dashboard_collateral_usd = portfolio_summary.get("total_collateral_usd", 0.0)  # Collateral after haircuts
        dashboard_borrowed_usd = portfolio_summary.get("total_borrowed_usd", 0.0)
        
        # Step 2: Fetch fresh from Crypto.com API and calculate NET the same way
        # This replicates the calculation in update_portfolio_cache() without updating cache
        try:
            balance_data = trade_client.get_account_summary()
        except Exception as api_err:
            return {
                "error": f"Crypto.com API call failed: {str(api_err)}",
                "dashboard_net_usd": dashboard_net_usd,
                "crypto_com_net_usd": None,
                "diff_usd": None,
                "diff_pct": None,
                "pass": False,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
        if not balance_data or "accounts" not in balance_data:
            return {
                "error": "No balance data received from Crypto.com",
                "dashboard_net_usd": dashboard_net_usd,
                "crypto_com_net_usd": None,
                "diff_usd": None,
                "diff_pct": None,
                "pass": False,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
        # Calculate NET Wallet Balance from Crypto.com API response (same logic as portfolio_cache)
        # Must use collateral (after haircuts) to match Crypto.com Margin "Wallet Balance"
        crypto_com_total_assets = 0.0
        crypto_com_total_collateral = 0.0
        crypto_com_total_borrowed = 0.0
        
        # Get prices for calculating USD values if market_value not available
        prices = get_crypto_prices()
        
        for account in balance_data.get("accounts", []):
            currency = _normalize_currency_name(
                account.get("currency") or account.get("instrument_name") or account.get("symbol")
            )
            if not currency:
                continue
            
            balance = float(account.get("balance", 0))
            
            # Skip negative balances (they're loans, handled separately)
            if balance < 0:
                # Check for explicit loan fields
                borrowed_balance = abs(float(account.get("borrowed_balance", 0)))
                borrowed_value = abs(float(account.get("borrowed_value", 0)))
                loan_amount = abs(float(account.get("loan_amount", 0)))
                loan_value = abs(float(account.get("loan_value", 0)))
                
                total_borrowed = borrowed_balance or loan_amount or abs(balance)
                total_borrowed_usd = borrowed_value or loan_value
                
                # Calculate borrowed USD value if not provided
                if total_borrowed_usd == 0 and total_borrowed > 0:
                    if currency in ["USD", "USDT", "USDC"]:
                        total_borrowed_usd = total_borrowed
                    elif currency in prices:
                        total_borrowed_usd = total_borrowed * prices[currency]
                
                if total_borrowed_usd > 0:
                    crypto_com_total_borrowed += total_borrowed_usd
                continue
            
            # Use market_value from Crypto.com if available (most accurate)
            market_value_from_api = account.get("market_value")
            usd_value = 0.0
            
            if market_value_from_api:
                try:
                    if isinstance(market_value_from_api, str):
                        market_value_str = market_value_from_api.strip().replace(",", "").replace(" ", "")
                        if market_value_str and market_value_str.lower() not in ["0", "0.0", "0.00"]:
                            usd_value = float(market_value_str)
                    else:
                        usd_value = float(market_value_from_api)
                except (ValueError, TypeError):
                    usd_value = 0.0
            
            # If no market_value, calculate from prices (same as portfolio_cache)
            if usd_value == 0:
                if currency in ["USDT", "USD", "USDC"]:
                    usd_value = balance
                elif currency in prices:
                    usd_value = balance * prices[currency]
                else:
                    # Try Crypto.com API directly for this currency (same as portfolio_cache)
                    from app.utils.http_client import http_get
                    price_found = False
                    
                    # Try USDT pair first
                    try:
                        ticker_url = f"https://api.crypto.com/exchange/v1/public/get-ticker?instrument_name={currency}_USDT"
                        ticker_response = http_get(ticker_url, timeout=5, calling_module="portfolio_verify")
                        if ticker_response.status_code == 200:
                            ticker_data = ticker_response.json()
                            if "result" in ticker_data and "data" in ticker_data["result"]:
                                ticker = ticker_data["result"]["data"]
                                price = float(ticker.get("a", 0))
                                if price > 0:
                                    prices[currency] = price
                                    usd_value = balance * price
                                    price_found = True
                    except Exception:
                        pass
                    
                    # If USDT pair failed, try USD pair
                    if not price_found:
                        try:
                            ticker_url = f"https://api.crypto.com/exchange/v1/public/get-ticker?instrument_name={currency}_USD"
                            ticker_response = http_get(ticker_url, timeout=5, calling_module="portfolio_verify")
                            if ticker_response.status_code == 200:
                                ticker_data = ticker_response.json()
                                if "result" in ticker_data and "data" in ticker_data["result"]:
                                    ticker = ticker_data["result"]["data"]
                                    price = float(ticker.get("a", 0))
                                    if price > 0:
                                        prices[currency] = price
                                        usd_value = balance * price
                        except Exception:
                            pass
            
            if usd_value > 0:
                crypto_com_total_assets += usd_value
                
                # Extract haircut and calculate collateral (same as portfolio_cache)
                haircut = 0.0
                haircut_raw = account.get("haircut") or account.get("collateral_ratio") or account.get("discount") or account.get("haircut_rate")
                if haircut_raw is not None:
                    try:
                        if isinstance(haircut_raw, str):
                            haircut_str = haircut_raw.strip().replace("--", "").strip()
                            if haircut_str and haircut_str.lower() not in ["0", "0.0", "0.00"]:
                                haircut = float(haircut_str)
                        else:
                            haircut = float(haircut_raw)
                    except (ValueError, TypeError):
                        haircut = 0.0
                
                # Stablecoins have 0 haircut
                if currency in ["USD", "USDT", "USDC"]:
                    haircut = 0.0
                
                # Calculate collateral value (after haircut)
                collateral_value = usd_value * (1 - haircut)
                crypto_com_total_collateral += collateral_value
        
        # Calculate NET Wallet Balance (collateral - borrowed) - matches Crypto.com "Wallet Balance"
        crypto_com_net_usd = crypto_com_total_collateral - crypto_com_total_borrowed
        
        # Step 3: Compare
        diff_usd = dashboard_net_usd - crypto_com_net_usd
        diff_pct = (diff_usd / crypto_com_net_usd * 100) if crypto_com_net_usd != 0 else 0.0
        pass_check = abs(diff_usd) <= 5.0  # Tolerance: $5
        
        result = {
            "dashboard_net_usd": round(dashboard_net_usd, 2),
            "dashboard_gross_usd": round(dashboard_gross_usd, 2),
            "dashboard_collateral_usd": round(dashboard_collateral_usd, 2),
            "dashboard_borrowed_usd": round(dashboard_borrowed_usd, 2),
            "crypto_com_net_usd": round(crypto_com_net_usd, 2),
            "crypto_com_gross_usd": round(crypto_com_total_assets, 2),
            "crypto_com_collateral_usd": round(crypto_com_total_collateral, 2),
            "crypto_com_borrowed_usd": round(crypto_com_total_borrowed, 2),
            "diff_usd": round(diff_usd, 2),
            "diff_pct": round(diff_pct, 4),
            "pass": pass_check,
            "tolerance_usd": 5.0,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Add breakdown if requested and PORTFOLIO_DEBUG is enabled
        if include_breakdown and PORTFOLIO_DEBUG:
            breakdown = []
            # Re-process accounts to build breakdown (we already have the data, but need to format it)
            for account in balance_data.get("accounts", []):
                currency = _normalize_currency_name(
                    account.get("currency") or account.get("instrument_name") or account.get("symbol")
                )
                if not currency:
                    continue
                
                balance = float(account.get("balance", 0))
                if balance <= 0:
                    continue
                
                # Calculate raw value (same logic as above)
                market_value_from_api = account.get("market_value")
                usd_value = 0.0
                
                if market_value_from_api:
                    try:
                        if isinstance(market_value_from_api, str):
                            market_value_str = market_value_from_api.strip().replace(",", "").replace(" ", "")
                            if market_value_str and market_value_str.lower() not in ["0", "0.0", "0.00"]:
                                usd_value = float(market_value_str)
                        else:
                            usd_value = float(market_value_from_api)
                    except (ValueError, TypeError):
                        usd_value = 0.0
                
                if usd_value == 0:
                    if currency in ["USDT", "USD", "USDC"]:
                        usd_value = balance
                    elif currency in prices:
                        usd_value = balance * prices[currency]
                
                if usd_value > 0:
                    # Extract haircut (same logic as above)
                    haircut = 0.0
                    haircut_raw = account.get("haircut") or account.get("collateral_ratio") or account.get("discount") or account.get("haircut_rate")
                    if haircut_raw is not None:
                        try:
                            if isinstance(haircut_raw, str):
                                haircut_str = haircut_raw.strip().replace("--", "").strip()
                                if haircut_str and haircut_str.lower() not in ["0", "0.0", "0.00"]:
                                    haircut = float(haircut_str)
                            else:
                                haircut = float(haircut_raw)
                        except (ValueError, TypeError):
                            haircut = 0.0
                    
                    if currency in ["USD", "USDT", "USDC"]:
                        haircut = 0.0
                    
                    collateral_value = usd_value * (1 - haircut)
                    breakdown.append({
                        "symbol": currency,
                        "quantity": round(balance, 8),
                        "raw_value_usd": round(usd_value, 2),
                        "haircut": round(haircut, 4),
                        "collateral_value_usd": round(collateral_value, 2)
                    })
            
            # Sort by raw_value_usd descending
            breakdown.sort(key=lambda x: x["raw_value_usd"], reverse=True)
            result["breakdown"] = breakdown
        
        # Structured logging when VERIFICATION_DEBUG=1
        if VERIFICATION_DEBUG:
            log.info(f"[VERIFICATION_DEBUG] Portfolio verify: dashboard_net=${dashboard_net_usd:,.2f}, crypto_com_net=${crypto_com_net_usd:,.2f}, diff=${diff_usd:,.2f}, pass={pass_check}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error in portfolio verification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")


@router.get("/diagnostics/portfolio-verify-lite", tags=["diagnostics"])
def diagnostics_portfolio_verify_lite(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Lightweight portfolio verification endpoint.
    
    Returns only essential fields: pass, dashboard_net_usd, crypto_com_net_usd, diff_usd, timestamp.
    No per-asset breakdown even if PORTFOLIO_DEBUG=1.
    
    Protected by:
    - ENABLE_DIAGNOSTICS_ENDPOINTS=1 environment variable
    - X-Diagnostics-Key header (DIAGNOSTICS_API_KEY env var)
    """
    import os
    from app.services.brokers.crypto_com_trade import trade_client
    from app.services.portfolio_cache import _normalize_currency_name, get_crypto_prices
    from datetime import datetime, timezone
    
    # Security: Verify diagnostics auth
    _verify_diagnostics_auth(request)
    
    VERIFICATION_DEBUG = os.getenv("VERIFICATION_DEBUG", "0") == "1"
    
    try:
        # Step 1: Get dashboard NET value (same as shown in UI "Total Value")
        portfolio_summary = get_portfolio_summary(db)
        dashboard_net_usd = portfolio_summary.get("total_usd", 0.0)  # NET equity
        
        # Step 2: Fetch fresh from Crypto.com API and calculate NET the same way
        try:
            balance_data = trade_client.get_account_summary()
        except Exception as api_err:
            return {
                "error": f"Crypto.com API call failed: {str(api_err)}",
                "dashboard_net_usd": round(dashboard_net_usd, 2),
                "crypto_com_net_usd": None,
                "diff_usd": None,
                "pass": False,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
        if not balance_data or "accounts" not in balance_data:
            return {
                "error": "No balance data received from Crypto.com",
                "dashboard_net_usd": round(dashboard_net_usd, 2),
                "crypto_com_net_usd": None,
                "diff_usd": None,
                "pass": False,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
        # Calculate NET Wallet Balance from Crypto.com API response (same logic as portfolio_cache)
        # Must use collateral (after haircuts) to match Crypto.com Margin "Wallet Balance"
        crypto_com_total_assets = 0.0
        crypto_com_total_collateral = 0.0
        crypto_com_total_borrowed = 0.0
        prices = get_crypto_prices()
        
        for account in balance_data.get("accounts", []):
            currency = _normalize_currency_name(
                account.get("currency") or account.get("instrument_name") or account.get("symbol")
            )
            if not currency:
                continue
            
            balance = float(account.get("balance", 0))
            
            # Handle loans (negative balances)
            if balance < 0:
                borrowed_balance = abs(float(account.get("borrowed_balance", 0)))
                borrowed_value = abs(float(account.get("borrowed_value", 0)))
                loan_amount = abs(float(account.get("loan_amount", 0)))
                loan_value = abs(float(account.get("loan_value", 0)))
                
                total_borrowed = borrowed_balance or loan_amount or abs(balance)
                total_borrowed_usd = borrowed_value or loan_value
                
                if total_borrowed_usd == 0 and total_borrowed > 0:
                    if currency in ["USD", "USDT", "USDC"]:
                        total_borrowed_usd = total_borrowed
                    elif currency in prices:
                        total_borrowed_usd = total_borrowed * prices[currency]
                
                if total_borrowed_usd > 0:
                    crypto_com_total_borrowed += total_borrowed_usd
                continue
            
            # Calculate asset USD value (raw)
            market_value_from_api = account.get("market_value")
            usd_value = 0.0
            
            if market_value_from_api:
                try:
                    if isinstance(market_value_from_api, str):
                        market_value_str = market_value_from_api.strip().replace(",", "").replace(" ", "")
                        if market_value_str and market_value_str.lower() not in ["0", "0.0", "0.00"]:
                            usd_value = float(market_value_str)
                    else:
                        usd_value = float(market_value_from_api)
                except (ValueError, TypeError):
                    usd_value = 0.0
            
            if usd_value == 0:
                if currency in ["USDT", "USD", "USDC"]:
                    usd_value = balance
                elif currency in prices:
                    usd_value = balance * prices[currency]
                else:
                    # Try Crypto.com API directly (minimal - only if needed)
                    from app.utils.http_client import http_get
                    try:
                        ticker_url = f"https://api.crypto.com/exchange/v1/public/get-ticker?instrument_name={currency}_USDT"
                        ticker_response = http_get(ticker_url, timeout=5, calling_module="portfolio_verify_lite")
                        if ticker_response.status_code == 200:
                            ticker_data = ticker_response.json()
                            if "result" in ticker_data and "data" in ticker_data["result"]:
                                ticker = ticker_data["result"]["data"]
                                price = float(ticker.get("a", 0))
                                if price > 0:
                                    usd_value = balance * price
                    except Exception:
                        pass
            
            if usd_value > 0:
                crypto_com_total_assets += usd_value
                
                # Extract haircut and calculate collateral (same as portfolio_cache)
                haircut = 0.0
                haircut_raw = account.get("haircut") or account.get("collateral_ratio") or account.get("discount") or account.get("haircut_rate")
                if haircut_raw is not None:
                    try:
                        if isinstance(haircut_raw, str):
                            haircut_str = haircut_raw.strip().replace("--", "").strip()
                            if haircut_str and haircut_str.lower() not in ["0", "0.0", "0.00"]:
                                haircut = float(haircut_str)
                        else:
                            haircut = float(haircut_raw)
                    except (ValueError, TypeError):
                        haircut = 0.0
                
                # Stablecoins have 0 haircut
                if currency in ["USD", "USDT", "USDC"]:
                    haircut = 0.0
                
                # Calculate collateral value (after haircut)
                collateral_value = usd_value * (1 - haircut)
                crypto_com_total_collateral += collateral_value
        
        # Calculate NET Wallet Balance (collateral - borrowed) - matches Crypto.com "Wallet Balance"
        crypto_com_net_usd = crypto_com_total_collateral - crypto_com_total_borrowed
        
        # Compare
        diff_usd = dashboard_net_usd - crypto_com_net_usd
        pass_check = abs(diff_usd) <= 5.0
        
        result = {
            "pass": pass_check,
            "dashboard_net_usd": round(dashboard_net_usd, 2),
            "crypto_com_net_usd": round(crypto_com_net_usd, 2),
            "diff_usd": round(diff_usd, 2),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Structured logging when VERIFICATION_DEBUG=1
        if VERIFICATION_DEBUG:
            log.info(f"[VERIFICATION_DEBUG] Portfolio verify-lite: dashboard_net=${dashboard_net_usd:,.2f}, crypto_com_net=${crypto_com_net_usd:,.2f}, diff=${diff_usd:,.2f}, pass={pass_check}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error in portfolio verification (lite): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Verification failed: {str(e)}")
