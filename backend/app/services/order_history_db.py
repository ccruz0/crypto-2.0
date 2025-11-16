import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

class OrderHistoryDB:
    """Service for managing order history in SQLite database"""
    
    def __init__(self, db_path: str = "order_history.db"):
        self.db_path = db_path
        self._create_table()
    
    def _get_connection(self):
        """Get database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _create_table(self):
        """Create order_history table if it doesn't exist"""
        conn = self._get_connection()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS order_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE,
                    client_oid TEXT,
                    instrument_name TEXT,
                    order_type TEXT,
                    side TEXT,
                    status TEXT,
                    quantity REAL,
                    price REAL,
                    avg_price REAL,
                    order_value REAL,
                    cumulative_quantity REAL,
                    cumulative_value REAL,
                    create_time INTEGER,
                    update_time INTEGER,
                    raw_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_order_id ON order_history(order_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_instrument ON order_history(instrument_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_create_time ON order_history(create_time)")
            # Optimize: Add composite index for status + create_time queries (used by get_orders_by_status)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status_create_time ON order_history(status, create_time)")
            conn.commit()
            logger.info("Order history table created/verified")
        except Exception as e:
            logger.error(f"Error creating order_history table: {e}")
        finally:
            conn.close()
    
    def upsert_order(self, order_data: dict) -> bool:
        """Insert or update order in database"""
        conn = self._get_connection()
        try:
            order_id = str(order_data.get("order_id", ""))
            client_oid = str(order_data.get("client_oid", ""))
            instrument_name = order_data.get("instrument_name", "")
            order_type = order_data.get("order_type", "")
            side = order_data.get("side", "")
            status = order_data.get("status", "")
            
            # Handle numeric fields
            def safe_float(val):
                try:
                    return float(val) if val else 0
                except (ValueError, TypeError):
                    return 0
            
            quantity = safe_float(order_data.get("quantity"))
            price = safe_float(order_data.get("limit_price") or order_data.get("price")) or None
            avg_price = safe_float(order_data.get("avg_price")) or None
            order_value = safe_float(order_data.get("order_value")) or None
            cumulative_quantity = safe_float(order_data.get("cumulative_quantity")) or None
            cumulative_value = safe_float(order_data.get("cumulative_value")) or None
            
            # Handle timestamps (convert from ms to seconds)
            create_time = order_data.get("create_time")
            if create_time:
                create_time = int(create_time / 1000) if create_time > 1000000000000 else create_time
            else:
                create_time = int(datetime.now().timestamp())
            
            update_time = order_data.get("update_time")
            if update_time:
                update_time = int(update_time / 1000) if update_time > 1000000000000 else update_time
            else:
                update_time = create_time
            
            raw_data = json.dumps(order_data)
            
            conn.execute("""
                INSERT OR REPLACE INTO order_history 
                (order_id, client_oid, instrument_name, order_type, side, status,
                 quantity, price, avg_price, order_value, cumulative_quantity, cumulative_value,
                 create_time, update_time, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (order_id, client_oid, instrument_name, order_type, side, status,
                  quantity, price, avg_price, order_value, cumulative_quantity, cumulative_value,
                  create_time, update_time, raw_data))
            
            conn.commit()
            logger.info(f"Upserted order: {order_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error upserting order: {e}")
            return False
        finally:
            conn.close()
    
    def get_all_orders(self, limit: int = 500) -> List[Dict]:
        """Get all orders, sorted by create_time descending"""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                SELECT * FROM order_history 
                ORDER BY create_time DESC 
                LIMIT ?
            """, (limit,))
            
            orders = []
            for row in cursor.fetchall():
                order = dict(row)
                # Convert timestamps back to milliseconds
                if order['create_time']:
                    order['create_time'] = order['create_time'] * 1000
                if order['update_time']:
                    order['update_time'] = order['update_time'] * 1000
                orders.append(order)
            
            return orders
            
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            return []
        finally:
            conn.close()
    
    def get_orders_by_instrument(self, instrument_name: str, limit: int = 100) -> List[Dict]:
        """Get orders for a specific instrument"""
        conn = self._get_connection()
        try:
            cursor = conn.execute("""
                SELECT * FROM order_history 
                WHERE instrument_name = ?
                ORDER BY create_time DESC 
                LIMIT ?
            """, (instrument_name, limit))
            
            orders = []
            for row in cursor.fetchall():
                order = dict(row)
                if order['create_time']:
                    order['create_time'] = order['create_time'] * 1000
                if order['update_time']:
                    order['update_time'] = order['update_time'] * 1000
                orders.append(order)
            
            return orders
            
        except Exception as e:
            logger.error(f"Error getting orders by instrument: {e}")
            return []
        finally:
            conn.close()
    
    def get_orders_by_status(self, statuses: List[str], limit: int = 1000) -> List[Dict]:
        """Get orders by status (e.g., ['ACTIVE', 'PENDING'])"""
        conn = self._get_connection()
        try:
            placeholders = ','.join('?' * len(statuses))
            cursor = conn.execute(f"""
                SELECT * FROM order_history 
                WHERE status IN ({placeholders})
                ORDER BY create_time DESC 
                LIMIT ?
            """, (*statuses, limit))
            
            orders = []
            for row in cursor.fetchall():
                order = dict(row)
                if order['create_time']:
                    order['create_time'] = order['create_time'] * 1000
                if order['update_time']:
                    order['update_time'] = order['update_time'] * 1000
                orders.append(order)
            
            return orders
            
        except Exception as e:
            logger.error(f"Error getting orders by status: {e}")
            return []
        finally:
            conn.close()
    
    def count_orders(self) -> int:
        """Get total count of orders"""
        conn = self._get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) as count FROM order_history")
            result = cursor.fetchone()
            return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Error counting orders: {e}")
            return 0
        finally:
            conn.close()


# Global instance
order_history_db = OrderHistoryDB()
