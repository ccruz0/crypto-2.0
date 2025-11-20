"""Service for maintaining dashboard state snapshot cache"""
import logging
import time
import asyncio
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.dashboard_cache import DashboardCache

logger = logging.getLogger(__name__)


def update_dashboard_snapshot(db: Session = None, dashboard_state: dict = None) -> dict:
    """
    Update the dashboard snapshot cache by computing full dashboard state
    and storing it in the database.
    
    This function should only be called from background tasks, not from HTTP handlers.
    
    Args:
        db: Database session (optional, will create if None)
        dashboard_state: Precomputed dashboard state dict (optional).
                         If None, will compute it (this takes 40-70 seconds).
    
    Returns:
        dict: Update result with success status and timing info
    """
    start_time = time.time()
    should_close_db = False
    
    try:
        # Use provided session or create new one
        if db is None:
            db = SessionLocal()
            should_close_db = True
        
        logger.info("🔄 Starting dashboard snapshot update...")
        
        # Compute full dashboard state if not provided (this may take 40-70 seconds)
        if dashboard_state is None:
            try:
                # Lazy import to avoid circular dependency
                from app.api.routes_dashboard import get_dashboard_state
                # get_dashboard_state is now async, so we need to run it in an event loop
                # Use asyncio.run() which creates a new event loop and runs the coroutine
                dashboard_state = asyncio.run(get_dashboard_state(db))
                logger.info(f"✅ Dashboard state computed in {time.time() - start_time:.2f}s")
            except Exception as e:
                logger.error(f"❌ Error computing dashboard state: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": str(e),
                    "duration_seconds": time.time() - start_time
                }
        else:
            logger.info("📥 Using precomputed dashboard state for snapshot update")
        
        # Store snapshot in database (upsert id=1)
        try:
            cache_entry = db.query(DashboardCache).filter(DashboardCache.id == 1).first()
            
            if cache_entry:
                # Update existing entry
                cache_entry.data = dashboard_state
                cache_entry.last_updated_at = datetime.now(timezone.utc)
                logger.info("📝 Updated existing dashboard cache entry")
            else:
                # Create new entry
                cache_entry = DashboardCache(
                    id=1,
                    data=dashboard_state,
                    last_updated_at=datetime.now(timezone.utc)
                )
                db.add(cache_entry)
                logger.info("📝 Created new dashboard cache entry")
            
            db.commit()
            
            duration = time.time() - start_time
            logger.info(f"✅ Dashboard snapshot updated successfully in {duration:.2f}s")
            
            return {
                "success": True,
                "duration_seconds": duration,
                "last_updated_at": cache_entry.last_updated_at.isoformat()
            }
            
        except Exception as e:
            db.rollback()
            logger.error(f"❌ Error storing dashboard snapshot: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "duration_seconds": time.time() - start_time
            }
            
    except Exception as e:
        logger.error(f"❌ Error in update_dashboard_snapshot: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "duration_seconds": time.time() - start_time
        }
    finally:
        if should_close_db and db:
            db.close()


def get_dashboard_snapshot(db: Session = None) -> dict:
    """
    Get the latest dashboard snapshot from cache.
    
    This is a fast read-only operation that should be used by HTTP handlers.
    
    Returns:
        dict: Snapshot data with metadata (stale_seconds, stale flag, etc.)
    """
    should_close_db = False
    
    try:
        if db is None:
            db = SessionLocal()
            should_close_db = True
        
        cache_entry = db.query(DashboardCache).filter(DashboardCache.id == 1).first()
        
        if not cache_entry or not cache_entry.data:
            # No snapshot available yet
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
                    "errors": ["No snapshot available yet. Background update in progress."]
                },
                "last_updated_at": None,
                "stale_seconds": None,
                "stale": True,
                "empty": True
            }
        
        # Calculate staleness
        now = datetime.now(timezone.utc)
        if cache_entry.last_updated_at.tzinfo is None:
            # Handle naive datetime
            last_updated = cache_entry.last_updated_at.replace(tzinfo=timezone.utc)
        else:
            last_updated = cache_entry.last_updated_at
        
        stale_seconds = int((now - last_updated).total_seconds())
        stale = stale_seconds > 90
        
        return {
            "data": cache_entry.data,
            "last_updated_at": last_updated.isoformat(),
            "stale_seconds": stale_seconds,
            "stale": stale,
            "empty": False
        }
        
    except Exception as e:
        logger.error(f"❌ Error getting dashboard snapshot: {e}", exc_info=True)
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
                "errors": [str(e)]
            },
            "last_updated_at": None,
            "stale_seconds": None,
            "stale": True,
            "empty": True
        }
    finally:
        if should_close_db and db:
            db.close()

