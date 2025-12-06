"""
AWS Database Backup System
Creates and maintains all tables in AWS RDS PostgreSQL with automatic updates
"""

import os
import psycopg2
import sqlite3
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import boto3
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AWSDatabaseBackup:
    """AWS Database backup and sync system"""
    
    def __init__(self):
        # AWS RDS Configuration
        self.aws_config = {
            'host': os.getenv('AWS_RDS_HOST', 'your-rds-endpoint.amazonaws.com'),
            'port': os.getenv('AWS_RDS_PORT', '5432'),
            'database': os.getenv('AWS_RDS_DATABASE', 'trading_platform'),
            'user': os.getenv('AWS_RDS_USER', 'postgres'),
            'password': os.getenv('AWS_RDS_PASSWORD', 'your-password')
        }
        
        # Local SQLite database path
        self.local_db_path = os.path.join(os.path.dirname(__file__), 'assets.db')
        
        # S3 backup configuration
        self.s3_bucket = os.getenv('AWS_S3_BACKUP_BUCKET', 'trading-platform-backups')
        self.s3_client = boto3.client('s3')
    
    def get_aws_connection(self):
        """Get AWS RDS PostgreSQL connection"""
        try:
            conn = psycopg2.connect(**self.aws_config)
            return conn
        except Exception as e:
            logger.error(f"Failed to connect to AWS RDS: {e}")
            return None
    
    def create_aws_tables(self):
        """Create all necessary tables in AWS RDS"""
        conn = self.get_aws_connection()
        if not conn:
            return False
        
        try:
            cursor = conn.cursor()
            
            # Create assets table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS assets (
                    id SERIAL PRIMARY KEY,
                    coin VARCHAR(50) NOT NULL,
                    balance DECIMAL(20,8),
                    available_qty DECIMAL(20,8),
                    reserved_qty DECIMAL(20,8),
                    haircut DECIMAL(5,4),
                    value_usd DECIMAL(20,2),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(coin)
                )
            """)
            
            # Create orders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id SERIAL PRIMARY KEY,
                    order_id VARCHAR(100) UNIQUE NOT NULL,
                    instrument_name VARCHAR(50) NOT NULL,
                    side VARCHAR(10) NOT NULL,
                    order_type VARCHAR(20) NOT NULL,
                    quantity DECIMAL(20,8) NOT NULL,
                    price DECIMAL(20,8) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create watchlist table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(50) UNIQUE NOT NULL,
                    trade_enabled BOOLEAN DEFAULT FALSE,
                    trade_amount_usd DECIMAL(20,2),
                    trade_on_margin BOOLEAN DEFAULT FALSE,
                    sl_tp_mode VARCHAR(20) DEFAULT 'conservative',
                    sl_percentage DECIMAL(5,2),
                    tp_percentage DECIMAL(5,2),
                    preset VARCHAR(20) DEFAULT 'swing',
                    overrides JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create trading signals table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trading_signals (
                    id SERIAL PRIMARY KEY,
                    symbol VARCHAR(50) NOT NULL,
                    exchange VARCHAR(20) NOT NULL,
                    price DECIMAL(20,8),
                    rsi DECIMAL(5,2),
                    ma10 DECIMAL(20,8),
                    ma50 DECIMAL(20,8),
                    ma200 DECIMAL(20,8),
                    ema10 DECIMAL(20,8),
                    ma10w DECIMAL(20,8),
                    volume DECIMAL(20,2),
                    avg_volume DECIMAL(20,2),
                    signals JSONB,
                    source VARCHAR(20),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create trading config table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trading_config (
                    id SERIAL PRIMARY KEY,
                    config_key VARCHAR(100) UNIQUE NOT NULL,
                    config_value JSONB NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create data sources status table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS data_sources_status (
                    id SERIAL PRIMARY KEY,
                    source_name VARCHAR(50) UNIQUE NOT NULL,
                    available BOOLEAN DEFAULT FALSE,
                    priority INTEGER DEFAULT 1,
                    response_time DECIMAL(10,3),
                    last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error_message TEXT
                )
            """)
            
            # Create indexes for better performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_assets_coin ON assets(coin)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(instrument_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_watchlist_symbol ON watchlist(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol ON trading_signals(symbol)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_signals_created ON trading_signals(created_at)")
            
            conn.commit()
            logger.info("✅ AWS RDS tables created successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create AWS tables: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def sync_assets_to_aws(self):
        """Sync assets from local SQLite to AWS RDS"""
        if not os.path.exists(self.local_db_path):
            logger.warning("Local assets.db not found")
            return False
        
        # Get data from local SQLite
        local_conn = sqlite3.connect(self.local_db_path)
        local_cursor = local_conn.cursor()
        
        try:
            local_cursor.execute("""
                SELECT coin, balance, available_qty, reserved_qty, haircut, value_usd, updated_at
                FROM assets
            """)
            local_assets = local_cursor.fetchall()
            
            # Sync to AWS
            aws_conn = self.get_aws_connection()
            if not aws_conn:
                return False
            
            aws_cursor = aws_conn.cursor()
            
            for asset in local_assets:
                coin, balance, available_qty, reserved_qty, haircut, value_usd, updated_at = asset
                
                aws_cursor.execute("""
                    INSERT INTO assets (coin, balance, available_qty, reserved_qty, haircut, value_usd, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (coin) DO UPDATE SET
                        balance = EXCLUDED.balance,
                        available_qty = EXCLUDED.available_qty,
                        reserved_qty = EXCLUDED.reserved_qty,
                        haircut = EXCLUDED.haircut,
                        value_usd = EXCLUDED.value_usd,
                        updated_at = EXCLUDED.updated_at
                """, (coin, balance, available_qty, reserved_qty, haircut, value_usd, updated_at))
            
            aws_conn.commit()
            logger.info(f"✅ Synced {len(local_assets)} assets to AWS RDS")
            return True
            
        except Exception as e:
            logger.error(f"Failed to sync assets to AWS: {e}")
            return False
        finally:
            local_conn.close()
            if 'aws_conn' in locals():
                aws_conn.close()
    
    def sync_orders_to_aws(self, orders_data: List[Dict[str, Any]]):
        """Sync orders data to AWS RDS"""
        aws_conn = self.get_aws_connection()
        if not aws_conn:
            return False
        
        try:
            cursor = aws_conn.cursor()
            
            for order in orders_data:
                cursor.execute("""
                    INSERT INTO orders (order_id, instrument_name, side, order_type, quantity, price, status, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (order_id) DO UPDATE SET
                        instrument_name = EXCLUDED.instrument_name,
                        side = EXCLUDED.side,
                        order_type = EXCLUDED.order_type,
                        quantity = EXCLUDED.quantity,
                        price = EXCLUDED.price,
                        status = EXCLUDED.status,
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    order.get('order_id'),
                    order.get('instrument_name'),
                    order.get('side'),
                    order.get('order_type'),
                    order.get('quantity'),
                    order.get('price'),
                    order.get('status'),
                    order.get('created_at', datetime.now(timezone.utc))
                ))
            
            aws_conn.commit()
            logger.info(f"✅ Synced {len(orders_data)} orders to AWS RDS")
            return True
            
        except Exception as e:
            logger.error(f"Failed to sync orders to AWS: {e}")
            return False
        finally:
            aws_conn.close()
    
    def sync_watchlist_to_aws(self, watchlist_data: List[Dict[str, Any]]):
        """Sync watchlist data to AWS RDS"""
        aws_conn = self.get_aws_connection()
        if not aws_conn:
            return False
        
        try:
            cursor = aws_conn.cursor()
            
            for item in watchlist_data:
                cursor.execute("""
                    INSERT INTO watchlist (symbol, trade_enabled, trade_amount_usd, trade_on_margin, 
                                         sl_tp_mode, sl_percentage, tp_percentage, preset, overrides, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol) DO UPDATE SET
                        trade_enabled = EXCLUDED.trade_enabled,
                        trade_amount_usd = EXCLUDED.trade_amount_usd,
                        trade_on_margin = EXCLUDED.trade_on_margin,
                        sl_tp_mode = EXCLUDED.sl_tp_mode,
                        sl_percentage = EXCLUDED.sl_percentage,
                        tp_percentage = EXCLUDED.tp_percentage,
                        preset = EXCLUDED.preset,
                        overrides = EXCLUDED.overrides,
                        updated_at = EXCLUDED.updated_at
                """, (
                    item.get('symbol'),
                    item.get('trade_enabled'),
                    item.get('trade_amount_usd'),
                    item.get('trade_on_margin'),
                    item.get('sl_tp_mode'),
                    item.get('sl_percentage'),
                    item.get('tp_percentage'),
                    item.get('preset'),
                    json.dumps(item.get('overrides', {})) if item.get('overrides') else None,
                    datetime.now(timezone.utc)
                ))
            
            aws_conn.commit()
            logger.info(f"✅ Synced {len(watchlist_data)} watchlist items to AWS RDS")
            return True
            
        except Exception as e:
            logger.error(f"Failed to sync watchlist to AWS: {e}")
            return False
        finally:
            aws_conn.close()
    
    def sync_trading_config_to_aws(self, config_data: Dict[str, Any]):
        """Sync trading configuration to AWS RDS"""
        aws_conn = self.get_aws_connection()
        if not aws_conn:
            return False
        
        try:
            cursor = aws_conn.cursor()
            
            cursor.execute("""
                INSERT INTO trading_config (config_key, config_value, updated_at)
                VALUES ('main_config', %s, %s)
                ON CONFLICT (config_key) DO UPDATE SET
                    config_value = EXCLUDED.config_value,
                    updated_at = EXCLUDED.updated_at
            """, (json.dumps(config_data), datetime.now(timezone.utc)))
            
            aws_conn.commit()
            logger.info("✅ Synced trading configuration to AWS RDS")
            return True
            
        except Exception as e:
            logger.error(f"Failed to sync trading config to AWS: {e}")
            return False
        finally:
            aws_conn.close()
    
    def backup_to_s3(self):
        """Create a backup of the database to S3"""
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_key = f"database_backup_{timestamp}.json"
            
            # Get all data from AWS RDS
            aws_conn = self.get_aws_connection()
            if not aws_conn:
                return False
            
            cursor = aws_conn.cursor()
            
            # Collect all data
            backup_data = {
                'timestamp': timestamp,
                'assets': [],
                'orders': [],
                'watchlist': [],
                'trading_config': {},
                'data_sources_status': []
            }
            
            # Get assets
            cursor.execute("SELECT * FROM assets")
            assets = cursor.fetchall()
            backup_data['assets'] = [dict(zip([desc[0] for desc in cursor.description], row)) for row in assets]
            
            # Get orders
            cursor.execute("SELECT * FROM orders")
            orders = cursor.fetchall()
            backup_data['orders'] = [dict(zip([desc[0] for desc in cursor.description], row)) for row in orders]
            
            # Get watchlist
            cursor.execute("SELECT * FROM watchlist")
            watchlist = cursor.fetchall()
            backup_data['watchlist'] = [dict(zip([desc[0] for desc in cursor.description], row)) for row in watchlist]
            
            # Get trading config
            cursor.execute("SELECT config_value FROM trading_config WHERE config_key = 'main_config'")
            config_result = cursor.fetchone()
            if config_result:
                backup_data['trading_config'] = config_result[0]
            
            # Get data sources status
            cursor.execute("SELECT * FROM data_sources_status")
            data_sources = cursor.fetchall()
            backup_data['data_sources_status'] = [dict(zip([desc[0] for desc in cursor.description], row)) for row in data_sources]
            
            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=backup_key,
                Body=json.dumps(backup_data, indent=2, default=str),
                ContentType='application/json'
            )
            
            logger.info(f"✅ Database backup created in S3: {backup_key}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create S3 backup: {e}")
            return False
        finally:
            if 'aws_conn' in locals():
                aws_conn.close()
    
    def full_sync(self):
        """Perform a full synchronization of all data to AWS"""
        logger.info("🔄 Starting full sync to AWS RDS...")
        
        # Create tables if they don't exist
        if not self.create_aws_tables():
            logger.error("Failed to create AWS tables")
            return False
        
        # Sync assets
        if not self.sync_assets_to_aws():
            logger.error("Failed to sync assets")
            return False
        
        # Create S3 backup
        if not self.backup_to_s3():
            logger.error("Failed to create S3 backup")
            return False
        
        logger.info("✅ Full sync completed successfully")
        return True

# Global instance
aws_backup = AWSDatabaseBackup()

def sync_to_aws():
    """Public function to sync all data to AWS"""
    return aws_backup.full_sync()

def backup_to_s3():
    """Public function to create S3 backup"""
    return aws_backup.backup_to_s3()
