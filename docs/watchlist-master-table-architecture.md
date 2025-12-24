# Watchlist Master Table Architecture

## Overview

This document describes the redesigned Watchlist data flow that ensures the UI always reflects a single backend "master" table (source of truth). The dashboard displays exactly what is stored in this master table, with zero discrepancies.

## Old Flow vs New Flow

### Old Flow (Before)

**Data Sources:**
1. `watchlist_items` table - stored user configurations and some market data
2. `market_data` table - stored live computed values (price, RSI, MA, EMA, ATR, etc.)
3. Multiple endpoints merging data from both sources

**Problems:**
- Data was merged from multiple sources in the API layer
- Frontend received computed/merged values that didn't match any single source
- No way to track when individual fields were last updated
- Discrepancies between what UI showed and what was in the database
- No visual feedback for recently updated values
- No "Saved" confirmation after user edits

**API Endpoints:**
- `GET /api/dashboard` - merged `watchlist_items` + `MarketData`
- `PUT /api/dashboard/{item_id}` - updated `watchlist_items` only
- Various alert toggle endpoints

### New Flow (After)

**Data Source:**
1. `watchlist_master` table - **single source of truth** for all watchlist data
   - Stores all fields (user config + market data)
   - Includes per-field update timestamps (`field_updated_at` JSON)
   - Never empty (seeded from existing data)

**Benefits:**
- UI displays exactly what's in the master table
- Per-field timestamp tracking for "last updated" tooltips
- Visual highlighting for values updated in last 60 seconds
- Immediate "Saved" feedback after user edits
- Zero discrepancies between UI and database

**API Endpoints:**
- `GET /api/dashboard` - reads **only** from `watchlist_master` table
- `PUT /api/dashboard/symbol/{symbol}` - updates `watchlist_master` table with field timestamps
- Background jobs write directly to `watchlist_master` table

## Database Schema

### watchlist_master Table

```sql
CREATE TABLE watchlist_master (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT 'CRYPTO_COM',
    is_deleted BOOLEAN NOT NULL DEFAULT 0,
    
    -- User-configurable fields
    buy_target REAL,
    trade_enabled BOOLEAN NOT NULL DEFAULT 0,
    trade_amount_usd REAL,
    alert_enabled BOOLEAN NOT NULL DEFAULT 0,
    buy_alert_enabled BOOLEAN NOT NULL DEFAULT 0,
    sell_alert_enabled BOOLEAN NOT NULL DEFAULT 0,
    -- ... (all other watchlist fields)
    
    -- Market data fields (updated by background jobs)
    price REAL,
    rsi REAL,
    ma50 REAL,
    ma200 REAL,
    ema10 REAL,
    atr REAL,
    -- ... (all other market data fields)
    
    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    
    -- Per-field update timestamps (JSON string)
    -- Format: {"price": "2024-01-01T12:00:00Z", "rsi": "2024-01-01T12:01:00Z", ...}
    field_updated_at TEXT,
    
    UNIQUE(symbol, exchange)
);
```

## How Timestamps Work

### Per-Field Timestamp Tracking

Each field update automatically records its timestamp in the `field_updated_at` JSON field:

```json
{
  "price": "2024-01-15T10:30:00Z",
  "rsi": "2024-01-15T10:29:45Z",
  "trade_enabled": "2024-01-15T10:25:00Z",
  "buy_alert_enabled": "2024-01-15T10:20:00Z"
}
```

### Backend Implementation

The `WatchlistMaster` model provides helper methods:

```python
# Update a field and its timestamp atomically
master.update_field('price', 50000.0)

# Get timestamp for a specific field
last_updated = master.get_field_last_updated('price')
```

### Frontend Display

- **Tooltip**: On hover, shows "Last updated: <timestamp>" or "<N> seconds ago"
- **Visual Highlighting**: Values updated in last 60 seconds are:
  - Bold text
  - Green background tint (rgba(34, 197, 94, 0.1))
  - Green left border

## How Seeding "Never Empty" is Guaranteed

### Automatic Seeding

1. **On API Request**: `GET /api/dashboard` calls `ensure_master_table_seeded(db)` before querying
2. **On Startup**: Background jobs can call seeding function
3. **Migration**: Initial migration copies all data from `watchlist_items` + `MarketData` to `watchlist_master`

### Seeding Logic

The `watchlist_master_seed.py` service:
1. Queries all active `watchlist_items`
2. Creates/updates corresponding rows in `watchlist_master`
3. Enriches with `MarketData` if available
4. Sets initial field timestamps

This ensures the master table always has data for all tracked symbols.

## User Edit Flow with "Saved" Feedback

### Frontend Flow

1. User edits a field (e.g., toggles `buy_alert_enabled`)
2. Frontend calls `updateWatchlistItem(symbol, { buy_alert_enabled: true })`
3. Backend updates `watchlist_master` table and field timestamp
4. Backend returns updated item with `field_updated_at` metadata
5. Frontend shows "✓ Saved" indicator for 2 seconds
6. Frontend updates local state from server response

### API Response

```json
{
  "ok": true,
  "message": "Updated 1 field(s) for BTC_USDT",
  "item": {
    "symbol": "BTC_USDT",
    "buy_alert_enabled": true,
    "field_updated_at": {
      "buy_alert_enabled": "2024-01-15T10:30:00Z"
    }
  },
  "updated_fields": ["buy_alert_enabled"]
}
```

## Background Jobs Integration

### market_updater.py

The market updater process now writes directly to `watchlist_master`:

```python
# Update price in master table
master = db.query(WatchlistMaster).filter(
    WatchlistMaster.symbol == symbol
).first()

if master:
    master.update_field('price', new_price)
    master.update_field('rsi', new_rsi)
    master.update_field('ma50', new_ma50)
    # ... update all market data fields
    db.commit()
```

This ensures market data updates are immediately reflected in the UI with proper timestamps.

## Migration Steps

### 1. Run Database Migration

```bash
# Apply migration
sqlite3 your_database.db < backend/migrations/create_watchlist_master.sql
```

Or if using Alembic:
```bash
alembic upgrade head
```

### 2. Verify Seeding

```python
from app.services.watchlist_master_seed import ensure_master_table_seeded
from app.database import get_db

db = next(get_db())
ensure_master_table_seeded(db)
```

### 3. Update Background Jobs

Update `market_updater.py` and other background processes to write to `watchlist_master` instead of (or in addition to) `watchlist_items`.

### 4. Deploy Backend

Deploy updated backend with new endpoints and model.

### 5. Deploy Frontend

Deploy frontend with:
- Updated API calls to use master table endpoint
- `WatchlistCell` component for tooltips/highlighting
- "Saved" feedback after edits

## Testing

### Consistency Check

A dev-only consistency check compares UI displayed values with raw API response:

```typescript
// Frontend consistency check
const apiResponse = await getDashboard();
const uiDisplayed = watchlistItems;

// They must match exactly
assert.deepEqual(apiResponse, uiDisplayed);
```

### Manual Testing

1. **Visual Highlighting**: Update a price via market_updater, verify it's highlighted in UI
2. **Tooltip**: Hover over a cell, verify "Last updated" tooltip appears
3. **Saved Feedback**: Toggle an alert, verify "✓ Saved" appears
4. **Persistence**: Refresh page, verify changes persisted

## Rollback Plan

If issues arise:

1. **Rollback Backend**: Revert to old endpoints that read from `watchlist_items` + `MarketData`
2. **Rollback Frontend**: Revert to old API calls
3. **Keep Master Table**: Master table remains for future migration

The old `watchlist_items` table is not modified, so rollback is safe.

## Performance Considerations

- **Single Query**: `GET /api/dashboard` now does one query instead of multiple
- **No Merging**: No client-side or server-side data merging needed
- **Indexed**: Master table has indexes on `symbol` and `is_deleted`
- **Batch Updates**: Background jobs can batch update multiple fields in one transaction

## Future Enhancements

- Real-time updates via WebSocket
- Field-level change history
- Audit log for all field updates
- Conflict resolution for concurrent edits

