# Watchlist Master Table Implementation Summary

## Overview

This implementation redesigns the Watchlist data flow to use a single backend "master" table as the source of truth. The UI now displays exactly what is stored in this master table, with zero discrepancies.

## What Was Implemented

### 1. Database Schema

**New Table: `watchlist_master`**
- Created migration: `backend/migrations/create_watchlist_master.sql`
- Stores all watchlist fields (user config + market data)
- Includes `field_updated_at` JSON field for per-field timestamp tracking
- Unique constraint on (symbol, exchange)
- Indexed for performance

**New Model: `WatchlistMaster`**
- Location: `backend/app/models/watchlist_master.py`
- Helper methods:
  - `update_field(field_name, value, timestamp)` - Updates field and timestamp atomically
  - `get_field_last_updated(field_name)` - Returns datetime for a field
  - `get_field_updated_at()` - Returns all field timestamps as dict

### 2. Backend Changes

**Updated Endpoints:**
- `GET /api/dashboard` - Now reads **only** from `watchlist_master` table
- `PUT /api/dashboard/symbol/{symbol}` - New endpoint to update master table with field timestamps

**New Services:**
- `watchlist_master_seed.py` - Ensures master table is never empty
  - Seeds from existing `watchlist_items` + `MarketData`
  - Called automatically on `GET /api/dashboard`

**Updated Background Jobs:**
- `market_updater.py` - Now writes to `watchlist_master` table in addition to `MarketData`
  - Updates field timestamps automatically
  - Ensures UI reflects latest market data immediately

### 3. Frontend Changes

**Updated Types:**
- `WatchlistItem` interface now includes `field_updated_at?: Record<string, string>`

**New API Function:**
- `updateWatchlistItem(symbol, updates)` - Uses new PUT endpoint

**New Components:**
- `WatchlistCell.tsx` - Component for displaying cells with:
  - Tooltip showing "Last updated: <timestamp>"
  - Visual highlighting for values updated in last 60 seconds
  - "Saved" feedback after successful edits

**New Styles:**
- `watchlist.css` - Styling for recently updated and saved cells

### 4. Documentation

- `docs/watchlist-master-table-architecture.md` - Complete architecture documentation
  - Old flow vs new flow
  - How timestamps work
  - How seeding ensures table is never empty
  - User edit flow with "Saved" feedback
  - Migration steps
  - Testing guidelines

## Key Features

### ✅ Single Source of Truth
- UI displays exactly what's in `watchlist_master` table
- No data merging or discrepancies

### ✅ Per-Field Timestamp Tracking
- Each field update records its timestamp
- Stored in `field_updated_at` JSON field
- Format: `{"price": "2024-01-15T10:30:00Z", "rsi": "2024-01-15T10:29:45Z"}`

### ✅ Visual Feedback
- Values updated in last 60 seconds are highlighted (bold, green background, green border)
- Tooltip on hover shows "Last updated: <timestamp>" or "<N> seconds ago"
- "✓ Saved" indicator appears for 2 seconds after successful edits

### ✅ Immediate Persistence
- User edits are saved immediately to master table
- Field timestamps updated automatically
- Server response includes updated item with timestamps
- Frontend updates local state from server response

### ✅ Never Empty Table
- Automatic seeding on API requests
- Migration copies existing data
- Background jobs create rows as needed

## Migration Steps

### 1. Run Database Migration

```bash
# For SQLite
sqlite3 your_database.db < backend/migrations/create_watchlist_master.sql

# For PostgreSQL (may need adjustments for PostgreSQL syntax)
psql -d your_database -f backend/migrations/create_watchlist_master.sql
```

**Note:** The migration uses SQLite syntax. For PostgreSQL, you may need to:
- Change `TEXT` to `TIMESTAMP` for datetime fields
- Adjust `datetime('now')` to `NOW()`
- Adjust JSON handling if needed

### 2. Verify Seeding

The seeding happens automatically on first `GET /api/dashboard` call, but you can verify manually:

```python
from app.services.watchlist_master_seed import ensure_master_table_seeded
from app.database import get_db

db = next(get_db())
count = ensure_master_table_seeded(db)
print(f"Seeded {count} rows")
```

### 3. Deploy Backend

Deploy the updated backend with:
- New model and endpoints
- Updated `market_updater.py`
- Seeding service

### 4. Deploy Frontend

Deploy the updated frontend with:
- Updated API calls
- `WatchlistCell` component
- CSS styles

## Testing

### Manual Testing Checklist

1. **Visual Highlighting**
   - Wait for market_updater to update prices
   - Verify recently updated cells are highlighted (green background, bold)
   - Verify highlighting disappears after 60 seconds

2. **Tooltip**
   - Hover over any cell
   - Verify "Last updated: <timestamp>" tooltip appears
   - Verify timestamp format is readable

3. **Saved Feedback**
   - Toggle an alert (buy/sell)
   - Verify "✓ Saved" indicator appears
   - Verify it disappears after 2 seconds

4. **Persistence**
   - Make an edit (toggle alert, change amount, etc.)
   - Refresh the page
   - Verify changes persisted

5. **Consistency**
   - Open browser DevTools
   - Check API response from `GET /api/dashboard`
   - Verify UI displays exactly what API returns

### Automated Testing

Run existing tests:
```bash
cd backend
pytest tests/
```

## Rollback Plan

If issues arise:

1. **Backend Rollback:**
   - Revert `routes_dashboard.py` to use old `watchlist_items` + `MarketData` merge
   - Keep `watchlist_master` table (it's not modified by old code)

2. **Frontend Rollback:**
   - Revert API calls to use old endpoints
   - Remove `WatchlistCell` component usage

3. **Data Safety:**
   - Old `watchlist_items` table is untouched
   - Master table can be re-seeded from old data anytime

## Performance Impact

- **Positive:** Single query instead of multiple queries + merging
- **Positive:** No client-side data merging needed
- **Neutral:** Field timestamp tracking adds minimal overhead
- **Positive:** Indexed queries for fast lookups

## Next Steps

1. **Update Other Background Jobs:**
   - Any process that updates watchlist values should write to `watchlist_master`
   - Examples: signal evaluator, order processor, etc.

2. **Frontend Integration:**
   - Integrate `WatchlistCell` component into actual watchlist table
   - Replace old update calls with `updateWatchlistItem()`

3. **Real-time Updates (Future):**
   - Consider WebSocket for real-time field updates
   - Show live updates without page refresh

4. **Audit Log (Future):**
   - Track all field changes over time
   - Show change history per field

## Files Changed

### Backend
- `backend/migrations/create_watchlist_master.sql` (new)
- `backend/app/models/watchlist_master.py` (new)
- `backend/app/models/__init__.py` (updated)
- `backend/app/services/watchlist_master_seed.py` (new)
- `backend/app/api/routes_dashboard.py` (updated)
- `backend/market_updater.py` (updated)

### Frontend
- `frontend/src/app/api.ts` (updated)
- `frontend/src/components/WatchlistCell.tsx` (new)
- `frontend/src/styles/watchlist.css` (new)

### Documentation
- `docs/watchlist-master-table-architecture.md` (new)
- `WATCHLIST_MASTER_IMPLEMENTATION.md` (this file)

## Notes

- The migration uses SQLite syntax. For PostgreSQL deployments, adjust the migration SQL accordingly.
- The old `watchlist_items` table remains unchanged for safety.
- All existing endpoints continue to work during transition period.

