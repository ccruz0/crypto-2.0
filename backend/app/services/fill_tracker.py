"""Persistent fill tracking for order execution notifications.

Tracks last seen filled quantity per order to prevent duplicate notifications
and ensure only real fills trigger notifications.
"""
import logging
import sqlite3
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

logger = logging.getLogger(__name__)


class FillTracker:
    """Tracks order fills persistently to prevent duplicate notifications."""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize fill tracker with SQLite database.
        
        Args:
            db_path: Path to SQLite database file. If None, uses /app/.state/fill_tracker.db
        """
        if db_path is None:
            # Try container paths first, then local
            for base_path in ['/app/.state', '/data', '/tmp', os.path.expanduser('~/.state')]:
                state_dir = Path(base_path)
                try:
                    state_dir.mkdir(parents=True, exist_ok=True)
                    db_path = str(state_dir / 'fill_tracker.db')
                    break
                except (OSError, PermissionError):
                    continue
            else:
                # Fallback to current directory
                db_path = 'fill_tracker.db'
        
        self.db_path = db_path
        self._init_db()
        self._cleanup_old_entries()
    
    def _init_db(self):
        """Initialize SQLite database with required tables."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fill_tracking (
                    order_id TEXT NOT NULL PRIMARY KEY,
                    last_filled_qty REAL NOT NULL,
                    last_status TEXT,
                    last_updated TIMESTAMP NOT NULL,
                    notification_sent TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notification_sent (
                    order_id TEXT NOT NULL,
                    filled_qty REAL NOT NULL,
                    status TEXT NOT NULL,
                    sent_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (order_id, filled_qty, status)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notification_sent_at ON notification_sent(sent_at)")
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to initialize fill tracker database: {e}")
            raise
    
    def _cleanup_old_entries(self, days: int = 7):
        """Remove entries older than specified days."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            cutoff_ts = cutoff.timestamp()
            
            # Cleanup fill_tracking
            conn.execute(
                "DELETE FROM fill_tracking WHERE last_updated < ?",
                (cutoff_ts,)
            )
            
            # Cleanup notification_sent
            conn.execute(
                "DELETE FROM notification_sent WHERE sent_at < ?",
                (cutoff_ts,)
            )
            
            deleted = conn.total_changes()
            conn.commit()
            conn.close()
            
            if deleted > 0:
                logger.debug(f"Cleaned up {deleted} old fill tracking entries")
        except Exception as e:
            logger.warning(f"Failed to cleanup old fill tracking entries: {e}")
    
    def get_last_filled_qty(self, order_id: str) -> Tuple[Optional[float], Optional[str]]:
        """Get last seen filled quantity and status for an order.
        
        Returns:
            Tuple of (last_filled_qty, last_status) or (None, None) if not found
        """
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            cursor = conn.execute(
                "SELECT last_filled_qty, last_status FROM fill_tracking WHERE order_id = ?",
                (order_id,)
            )
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return row[0], row[1]
            return None, None
        except Exception as e:
            logger.warning(f"Failed to get last filled qty for {order_id}: {e}")
            return None, None
    
    def has_notification_been_sent(self, order_id: str, filled_qty: float, status: str) -> bool:
        """Check if a notification has been sent for this exact (order_id, filled_qty, status).
        
        Args:
            order_id: Exchange order ID
            filled_qty: Filled quantity
            status: Order status (FILLED, PARTIALLY_FILLED)
            
        Returns:
            True if notification was already sent for this exact combination
        """
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            cursor = conn.execute(
                "SELECT 1 FROM notification_sent WHERE order_id = ? AND filled_qty = ? AND status = ?",
                (order_id, filled_qty, status)
            )
            exists = cursor.fetchone() is not None
            conn.close()
            return exists
        except Exception as e:
            logger.warning(f"Failed to check notification sent for {order_id}: {e}")
            return False
    
    def should_notify_fill(
        self,
        order_id: str,
        current_filled_qty: float,
        status: str
    ) -> Tuple[bool, str]:
        """Determine if a fill notification should be sent.
        
        Args:
            order_id: Exchange order ID
            current_filled_qty: Current filled quantity
            status: Order status
            
        Returns:
            Tuple of (should_notify: bool, reason: str)
        """
        # Only notify for FILLED or PARTIALLY_FILLED status
        if status not in ('FILLED', 'PARTIALLY_FILLED'):
            return False, f"Status {status} is not a fill status"
        
        # Require filled quantity > 0
        if current_filled_qty <= 0:
            return False, "Filled quantity is zero or negative"
        
        # Check if notification already sent for this exact combination
        if self.has_notification_been_sent(order_id, current_filled_qty, status):
            return False, f"Notification already sent for {order_id} with qty={current_filled_qty} status={status}"
        
        # Get last seen filled quantity
        last_qty, last_status = self.get_last_filled_qty(order_id)
        
        if last_qty is None:
            # First time seeing this order with a fill - notify
            return True, "First fill for this order"
        
        # Only notify if filled quantity increased
        if current_filled_qty > last_qty:
            return True, f"Fill increment: {last_qty} -> {current_filled_qty}"
        
        # Same or decreased quantity - don't notify
        return False, f"Filled quantity did not increase ({last_qty} -> {current_filled_qty})"
    
    def record_fill(
        self,
        order_id: str,
        filled_qty: float,
        status: str,
        notification_sent: bool = False
    ):
        """Record a fill event.
        
        Args:
            order_id: Exchange order ID
            filled_qty: Filled quantity
            status: Order status
            notification_sent: Whether a notification was sent
        """
        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            now = datetime.now(timezone.utc).timestamp()
            
            # Update or insert fill tracking
            conn.execute("""
                INSERT OR REPLACE INTO fill_tracking
                (order_id, last_filled_qty, last_status, last_updated, notification_sent)
                VALUES (?, ?, ?, ?, ?)
            """, (
                order_id,
                filled_qty,
                status,
                now,
                now if notification_sent else None
            ))
            
            # Record notification if sent
            if notification_sent:
                conn.execute("""
                    INSERT OR IGNORE INTO notification_sent
                    (order_id, filled_qty, status, sent_at)
                    VALUES (?, ?, ?, ?)
                """, (order_id, filled_qty, status, now))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to record fill for {order_id}: {e}")


# Global instance
_fill_tracker_instance: Optional[FillTracker] = None


def get_fill_tracker() -> FillTracker:
    """Get or create global FillTracker instance."""
    global _fill_tracker_instance
    if _fill_tracker_instance is None:
        _fill_tracker_instance = FillTracker()
    return _fill_tracker_instance


