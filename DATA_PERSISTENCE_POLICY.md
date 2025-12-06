# Data Persistence Policy

## Overview
**All data imported from CSV files or fetched from Crypto.com is PERMANENT and NEVER deleted.**

This system is designed to maintain a complete historical record of all trading activities and portfolio data.

## Data Storage

### Order History Database (`order_history.db`)
- **Type**: SQLite database
- **Location**: Backend directory
- **Purpose**: Stores all executed orders from CSV imports and Crypto.com API
- **Persistence**: All orders are kept permanently

### Assets Database (`assets.db`)
- **Type**: SQLite database
- **Location**: Backend directory
- **Purpose**: Stores portfolio/asset balances from CSV imports
- **Persistence**: All asset balances are kept permanently

## Import Behavior

### CSV Import (`backend/import_orders.py`)
```python
# Uses INSERT OR REPLACE strategy
# What happens:
# 1. If order_id exists → UPDATE with new data
# 2. If order_id is new → INSERT as new record
# 3. NEVER deletes any existing records
```

### API Import Endpoints

#### `/api/import/assets-csv`
- **Method**: `INSERT OR REPLACE`
- **Behavior**:
  - Adds new assets if coin doesn't exist
  - Updates existing assets if coin already exists
  - Never removes assets
  - Preserves all historical data

#### `/api/import/orders-csv`
- **Method**: `INSERT OR REPLACE`  
- **Behavior**:
  - Adds new orders if order_id doesn't exist
  - Updates existing orders if order_id already exists
  - Never removes orders
  - Preserves all historical data

## Data Sources

### Primary Sources
1. **CSV Files**: Manual exports from Crypto.com Exchange
   - Order History CSV files
   - Assets/Portfolio CSV files
   - Uploaded via dashboard or imported via command line

2. **Crypto.com API** (when working):
   - Real-time order data
   - Account balance data
   - Open orders and executed orders
   - **All API data is saved to SQLite databases**

### Data Flow
```
CSV File → Parse → SQLite Database (INSERT OR REPLACE)
              ↓
          Update Dashboard
              ↓
          Display to User
```

## Update Strategy

### For Orders
- **New CSV Import**: Adds new orders, updates changed orders
- **API Fetch**: Adds new orders, updates status of existing orders
- **Never**: Deletes or removes any order

### For Assets
- **New CSV Import**: Updates balances for existing coins, adds new coins
- **API Fetch**: Updates current balances
- **Never**: Deletes or removes any asset

## Database Schema

### order_history Table
```sql
CREATE TABLE IF NOT EXISTS order_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT UNIQUE,  -- Ensures no duplicates
    ...
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

### assets Table
```sql
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT UNIQUE,  -- Ensures no duplicates
    ...
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

## Protection Against Data Loss

### Built-in Safeguards
1. **SQLite Transaction Safety**: All writes are atomic
2. **UNIQUE Constraints**: Prevents accidental duplicates
3. **INSERT OR REPLACE**: Updates existing records instead of creating duplicates
4. **No DELETE Operations**: Code never executes DELETE statements
5. **CSV Idempotency**: Importing same CSV multiple times is safe

### Backup Recommendations
- Regular SQLite database backups
- Keep original CSV files as archive
- Version control for database files (if using Git LFS)

## API Endpoints Behavior

### Read Endpoints (Safe)
- `GET /api/orders/open` - Returns ACTIVE/PENDING orders from database
- `GET /api/orders/history` - Returns all orders from database
- `GET /api/assets` - Returns all assets from database

### Write Endpoints (Update Only)
- `POST /api/import/orders-csv` - Import orders (add/update only)
- `POST /api/import/assets-csv` - Import assets (add/update only)

### Never Call Direct DELETE
The API does not expose any DELETE endpoints for historical data.

## User Actions

### What Users Can Do
✅ Import new CSV files
✅ Re-import same CSV files (safe)
✅ Fetch data from Crypto.com API
✅ View all historical data
✅ Update existing records with new data

### What Users Cannot Do
❌ Delete historical orders
❌ Delete historical assets  
❌ Clear the database
❌ Remove records via API

## Example Scenarios

### Scenario 1: Import Same CSV Twice
```
First import:  100 orders saved
Second import: 100 orders updated (no changes)
Result:        Still 100 orders (preserved)
```

### Scenario 2: Import Different CSVs
```
First CSV:     100 orders (Jan-Mar)
Second CSV:    150 orders (Jan-Jun)
Result:        150 orders total
               - First 100 are same/updated
               - Last 50 are new
```

### Scenario 3: New Order from API
```
CSV has:       100 orders
API fetches:   1 new order
Result:        101 orders total
               - 100 from CSV preserved
               - 1 new from API
```

## Technical Implementation

All import functions use this pattern:

```python
cursor.execute("""
    INSERT OR REPLACE INTO table_name 
    (columns...)
    VALUES (?, ?, ...)
""", values)
```

The `INSERT OR REPLACE` syntax ensures:
- New records are added
- Existing records are updated
- No records are ever deleted

## Summary

**The system is designed to NEVER lose data. All CSV imports and API data are permanently stored and only updated when new information arrives.**
