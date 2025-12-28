"""Service to ensure watchlist_master table is never empty.

This service seeds the master table from existing watchlist_items and MarketData
to ensure there's always data available for the UI.
"""

import logging
from sqlalchemy.orm import Session
from app.models.watchlist_master import WatchlistMaster
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketData
from datetime import datetime, timezone
import json

log = logging.getLogger(__name__)


def ensure_master_table_seeded(db: Session) -> int:
    """Ensure watchlist_master table has at least one row per active symbol.
    
    This function:
    1. Creates master rows for all active watchlist_items
    2. Enriches with MarketData if available
    3. Ensures the table is never empty
    
    Returns:
        Number of rows created/updated
    """
    try:
        # Get all active watchlist items
        active_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        if not active_items:
            log.warning("No active watchlist items found - master table may be empty")
            return 0
        
        created_count = 0
        updated_count = 0
        
        for item in active_items:
            # Check if master row exists
            master = db.query(WatchlistMaster).filter(
                WatchlistMaster.symbol == item.symbol.upper(),
                WatchlistMaster.exchange == (item.exchange or "CRYPTO_COM").upper()
            ).first()
            
            if not master:
                # Create new master row
                master = WatchlistMaster(
                    symbol=item.symbol.upper(),
                    exchange=(item.exchange or "CRYPTO_COM").upper(),
                    is_deleted=item.is_deleted or False,
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
                    signals=json.dumps(item.signals) if item.signals else None,
                    skip_sl_tp_reminder=item.skip_sl_tp_reminder or False,
                    order_status=item.order_status or "PENDING",
                    order_date=item.order_date,
                    purchase_price=item.purchase_price,
                    quantity=item.quantity,
                    sold=item.sold or False,
                    sell_price=item.sell_price,
                )
                db.add(master)
                created_count += 1
            else:
                # Update existing master row with latest from watchlist_items
                # BUT: Don't overwrite master if it was updated more recently than items
                # This prevents overwriting user changes made directly to master table
                updated = False
                
                # Check if master was updated more recently than items
                master_updated = master.updated_at if hasattr(master, 'updated_at') and master.updated_at else None
                item_updated = item.updated_at if hasattr(item, 'updated_at') and item.updated_at else None
                
                # Only sync from items to master if items is newer, or if master has no update timestamp
                should_sync_from_items = (
                    master_updated is None or 
                    item_updated is None or 
                    (item_updated and item_updated > master_updated)
                )
                
                if should_sync_from_items:
                    if master.buy_target != item.buy_target:
                        master.buy_target = item.buy_target
                        updated = True
                    # CRITICAL: Only sync trade_enabled from items if items is newer
                    # This prevents overwriting user changes made directly to master
                    if master.trade_enabled != (item.trade_enabled or False):
                        master.trade_enabled = item.trade_enabled or False
                        updated = True
                    if master.alert_enabled != (item.alert_enabled or False):
                        master.alert_enabled = item.alert_enabled or False
                        updated = True
                else:
                    # Master is newer, so sync FROM master TO items instead
                    if item.trade_enabled != (master.trade_enabled or False):
                        item.trade_enabled = master.trade_enabled or False
                        updated = True
                        log.debug(f"[SYNC_MASTER_TO_ITEMS] Synced trade_enabled for {item.symbol} from master to items")
                
                if updated:
                    updated_count += 1
            
            # Enrich with MarketData if available
            market_data = db.query(MarketData).filter(
                MarketData.symbol == item.symbol.upper()
            ).first()
            
            if market_data:
                now = datetime.now(timezone.utc)
                if master.price != market_data.price:
                    master.update_field('price', market_data.price, now)
                if master.rsi != market_data.rsi:
                    master.update_field('rsi', market_data.rsi, now)
                if master.atr != market_data.atr:
                    master.update_field('atr', market_data.atr, now)
                if master.ma50 != market_data.ma50:
                    master.update_field('ma50', market_data.ma50, now)
                if master.ma200 != market_data.ma200:
                    master.update_field('ma200', market_data.ma200, now)
                if master.ema10 != market_data.ema10:
                    master.update_field('ema10', market_data.ema10, now)
                if master.res_up != market_data.res_up:
                    master.update_field('res_up', market_data.res_up, now)
                if master.res_down != market_data.res_down:
                    master.update_field('res_down', market_data.res_down, now)
                if hasattr(market_data, 'volume_ratio') and master.volume_ratio != market_data.volume_ratio:
                    master.update_field('volume_ratio', market_data.volume_ratio, now)
        
        db.commit()
        
        if created_count > 0 or updated_count > 0:
            log.info(f"✅ Seeded watchlist_master: {created_count} created, {updated_count} updated")
        
        return created_count + updated_count
        
    except Exception as e:
        db.rollback()
        log.error(f"Error seeding watchlist_master: {e}", exc_info=True)
        raise

