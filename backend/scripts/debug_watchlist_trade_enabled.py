#!/usr/bin/env python3
"""Debug script to check trade_enabled value for a watchlist symbol.

Usage:
    python -m backend.scripts.debug_watchlist_trade_enabled ALGO_USDT
"""
import sys
import logging
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.watchlist_selector import get_canonical_watchlist_item, select_preferred_watchlist_item

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def debug_watchlist_trade_enabled(symbol: str):
    """Check trade_enabled for a symbol, showing all rows and canonical selection."""
    db: Session = SessionLocal()
    try:
        symbol_upper = symbol.upper()
        logger.info(f"Checking trade_enabled for {symbol_upper}")
        
        # Get all rows for this symbol
        all_rows = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol_upper
        ).all()
        
        if not all_rows:
            logger.warning(f"❌ No watchlist items found for {symbol_upper}")
            return
        
        logger.info(f"Found {len(all_rows)} row(s) for {symbol_upper}:")
        for i, row in enumerate(all_rows, 1):
            logger.info(
                f"  Row {i}: id={row.id}, "
                f"trade_enabled={row.trade_enabled}, "
                f"alert_enabled={getattr(row, 'alert_enabled', None)}, "
                f"is_deleted={getattr(row, 'is_deleted', False)}, "
                f"trade_amount_usd={row.trade_amount_usd}, "
                f"created_at={row.created_at}, "
                f"updated_at={getattr(row, 'updated_at', None)}"
            )
        
        # Get canonical row (same logic as SignalMonitor)
        canonical = get_canonical_watchlist_item(db, symbol_upper)
        if canonical:
            logger.info(f"\n✅ Canonical row (used by SignalMonitor):")
            logger.info(
                f"  id={canonical.id}, "
                f"trade_enabled={canonical.trade_enabled}, "
                f"alert_enabled={getattr(canonical, 'alert_enabled', None)}, "
                f"buy_alert_enabled={getattr(canonical, 'buy_alert_enabled', None)}, "
                f"sell_alert_enabled={getattr(canonical, 'sell_alert_enabled', None)}, "
                f"is_deleted={getattr(canonical, 'is_deleted', False)}, "
                f"trade_amount_usd={canonical.trade_amount_usd}, "
                f"trade_on_margin={getattr(canonical, 'trade_on_margin', None)}, "
                f"exchange={canonical.exchange}"
            )
            
            # Show if this matches what SignalMonitor would see
            logger.info(f"\n📊 SignalMonitor will use:")
            logger.info(f"  - trade_enabled: {canonical.trade_enabled} (for order placement)")
            logger.info(f"  - alert_enabled: {getattr(canonical, 'alert_enabled', None)} (for alerts)")
            logger.info(f"  - trade_amount_usd: {canonical.trade_amount_usd} (for order size)")
            
            if canonical.trade_enabled and canonical.trade_amount_usd and canonical.trade_amount_usd > 0:
                logger.info(f"✅ Order placement: ENABLED (trade_enabled=True, amount=${canonical.trade_amount_usd})")
            elif canonical.trade_enabled:
                logger.warning(f"⚠️ Order placement: DISABLED (trade_enabled=True but amount_usd={canonical.trade_amount_usd})")
            else:
                logger.info(f"ℹ️ Order placement: DISABLED (trade_enabled=False) - alerts will still be sent if alert_enabled=True")
            
            # Show selection logic
            preferred = select_preferred_watchlist_item(all_rows, symbol_upper)
            if preferred and preferred.id == canonical.id:
                logger.info(f"✅ Canonical selection matches preferred row (id={preferred.id})")
            else:
                logger.warning(f"⚠️ Canonical selection mismatch! Preferred id={preferred.id if preferred else None}, Canonical id={canonical.id}")
        else:
            logger.warning(f"❌ No canonical row found for {symbol_upper}")
            
    except Exception as e:
        logger.error(f"Error checking trade_enabled: {e}", exc_info=True)
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m backend.scripts.debug_watchlist_trade_enabled SYMBOL")
        print("Example: python -m backend.scripts.debug_watchlist_trade_enabled ALGO_USDT")
        sys.exit(1)
    
    symbol = sys.argv[1]
    debug_watchlist_trade_enabled(symbol)

