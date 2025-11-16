from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import csv
import sqlite3
import logging
import os

try:
    import multipart  # type: ignore

    MULTIPART_AVAILABLE = True
except ImportError:  # pragma: no cover - environment driven
    MULTIPART_AVAILABLE = False

logger = logging.getLogger(__name__)
router = APIRouter()


async def _import_assets_csv(file: UploadFile) -> JSONResponse:
    """
    Import assets from CSV file (manual upload from Crypto.com)
    
    IMPORTANT: This endpoint NEVER deletes existing data.
    - Uses INSERT OR REPLACE to add new assets or update existing ones
    - Historical data is preserved permanently
    - CSV imports only ADD or UPDATE records, never DELETE
    """
    
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    
    db_path = os.path.join(os.path.dirname(__file__), '../../assets.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Create table if it doesn't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coin TEXT NOT NULL,
            balance REAL,
            available_qty REAL,
            reserved_qty REAL,
            haircut REAL,
            value_usd REAL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(coin)
        )
    """)
    
    imported_count = 0
    error_count = 0
    errors = []
    
    try:
        # Read file content
        content = await file.read()
        content_str = content.decode('utf-8')
        
        # Split into lines
        lines = content_str.split('\n')
        
        # Skip disclaimer and find header row
        header_index = None
        for i, line in enumerate(lines):
            if 'Coin' in line and 'Balance' in line:
                header_index = i
                break
        
        if header_index is None:
            raise HTTPException(status_code=400, detail="Could not find header row with 'Coin'")
        
        # Parse CSV
        reader = csv.DictReader(lines[header_index:], delimiter=',')
        
        for row_num, row in enumerate(reader, start=header_index+2):
            try:
                # Parse row data
                coin = row.get('Coin', '').strip('"')
                if not coin:
                    continue
                
                # Parse values
                balance_str = row.get('Balance', '').strip('"').strip()
                balance = float(balance_str) if balance_str else 0
                
                available_qty_str = row.get('Available Qty', '').strip('"').strip()
                available_qty = float(available_qty_str) if available_qty_str else 0
                
                reserved_qty_str = row.get('Reserved Qty', '').strip('"').strip()
                reserved_qty = float(reserved_qty_str) if reserved_qty_str else 0
                
                haircut_str = row.get('Haircut', '').strip('"').strip()
                haircut = 0
                if haircut_str and haircut_str != '--':
                    try:
                        haircut = float(haircut_str)
                    except:
                        haircut = 0
                
                value_usd_str = row.get('Value(USD)', '').strip('"').strip()
                value_usd = float(value_usd_str) if value_usd_str else 0
                
                # Insert into database
                cursor.execute("""
                    INSERT OR REPLACE INTO assets 
                    (coin, balance, available_qty, reserved_qty, haircut, value_usd)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (coin, balance, available_qty, reserved_qty, haircut, value_usd))
                
                imported_count += 1
                
            except Exception as e:
                error_count += 1
                errors.append(f"Row {row_num}: {str(e)}")
        
        conn.commit()
        
        # Get total value
        cursor.execute("SELECT SUM(value_usd) as total FROM assets")
        total_value = cursor.fetchone()[0] or 0
        
        return JSONResponse(content={
            "message": "Assets import completed",
            "imported": imported_count,
            "errors": error_count,
            "total_value_usd": round(total_value, 2),
            "error_details": errors[:10] if errors else []
        })
        
    except Exception as e:
        logger.error(f"Error importing assets CSV: {e}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")
    
    finally:
        conn.close()

@router.get("/assets")
def get_assets():
    """Get all assets from the database - fast synchronous response"""
    try:
        db_path = os.path.join(os.path.dirname(__file__), '../../assets.db')
        
        if not os.path.exists(db_path):
            logger.debug(f"Assets database not found at {db_path}, returning empty result")
            return {"assets": [], "total_value_usd": 0}
    
        # Quick database access with timeout
        try:
            conn = sqlite3.connect(db_path, timeout=0.5)  # Very short timeout (0.5 seconds)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get all assets - simple query
            cursor.execute("""
                SELECT coin, balance, available_qty, reserved_qty, haircut, value_usd, updated_at
                FROM assets
                ORDER BY value_usd DESC
            """)
            
            rows = cursor.fetchall()
            
            assets = []
            total_value = 0.0
            
            for row in rows:
                value_usd = float(row['value_usd']) if row['value_usd'] else 0.0
                assets.append({
                    "coin": row['coin'],
                    "balance": float(row['balance']) if row['balance'] else 0.0,
                    "available_qty": float(row['available_qty']) if row['available_qty'] else 0.0,
                    "reserved_qty": float(row['reserved_qty']) if row['reserved_qty'] else 0.0,
                    "haircut": float(row['haircut']) if row['haircut'] else 0.0,
                    "value_usd": value_usd,
                    "updated_at": row['updated_at']
                })
                total_value += value_usd
            
            conn.close()
            
            logger.debug(f"Successfully fetched {len(assets)} assets, total_value={total_value}")
            
            return {
                "assets": assets,
                "total_value_usd": round(total_value, 2)
            }
        except sqlite3.OperationalError as e:
            logger.error(f"Database operational error: {e}")
            return {"assets": [], "total_value_usd": 0}
        except Exception as e:
            logger.error(f"Error fetching assets: {e}", exc_info=True)
            return {"assets": [], "total_value_usd": 0}
            
    except Exception as e:
        logger.error(f"Error accessing assets database: {e}", exc_info=True)
        return {"assets": [], "total_value_usd": 0}

if MULTIPART_AVAILABLE:
    @router.post("/import/assets-csv")
    async def import_assets_csv(file: UploadFile = File(...)):
        return await _import_assets_csv(file)
else:
    @router.post("/import/assets-csv")
    async def import_assets_csv_unavailable():
        logger.warning("CSV import disabled: python-multipart is not installed.")
        raise HTTPException(
            status_code=503,
            detail="CSV uploads require the python-multipart package. Install it to enable this endpoint.",
        )
