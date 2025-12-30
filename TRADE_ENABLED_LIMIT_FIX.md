# Trade Enabled Limit Fix

## Problem
When enabling a 17th coin with `trade_enabled=True`, it would be automatically disabled, maintaining a limit of 16 coins.

## Root Cause
The issue was caused by a sync conflict between `watchlist_master` and `watchlist_items` tables:

1. **User enables coin in `watchlist_master`** (via PUT /dashboard/symbol/{symbol})
2. **`watchlist_items` is not updated** (tables are out of sync)
3. **GET /dashboard is called**, which triggers `ensure_master_table_seeded()`
4. **`ensure_master_table_seeded()` syncs FROM `watchlist_items` TO `watchlist_master`**
5. **Master changes are overwritten**, effectively disabling the 17th coin

The `watchlist_items` table only had 16 coins with `trade_enabled=True`, so when syncing, it would overwrite the master table, disabling any coins beyond 16.

## Solution
Two fixes were implemented:

### Fix 1: Sync master to items when updating
**File**: `backend/app/api/routes_dashboard.py` (PUT /dashboard/symbol/{symbol})

When updating `watchlist_master`, also sync the `trade_enabled` value to the corresponding `watchlist_items` row to keep both tables in sync.

```python
# CRITICAL: Also sync to watchlist_items table to keep them in sync
if updated_fields and "trade_enabled" in updated_fields:
    item = db.query(WatchlistItem).filter(...).first()
    if item:
        item.trade_enabled = master.trade_enabled
        db.commit()
```

### Fix 2: Prevent overwriting newer master changes
**File**: `backend/app/services/watchlist_master_seed.py` (ensure_master_table_seeded)

Modified the sync logic to check which table was updated more recently and sync in the correct direction:
- If `watchlist_master` is newer → sync FROM master TO items
- If `watchlist_items` is newer → sync FROM items TO master
- This prevents overwriting user changes made directly to the master table

```python
# Check if master was updated more recently than items
should_sync_from_items = (
    master_updated is None or 
    item_updated is None or 
    (item_updated and item_updated > master_updated)
)

if should_sync_from_items:
    # Sync from items to master
else:
    # Sync from master to items
```

## Testing
To verify the fix works:
1. Enable a 17th coin with `trade_enabled=True`
2. Verify it stays enabled after multiple GET /dashboard requests
3. Check that both `watchlist_master` and `watchlist_items` have the same `trade_enabled` value

## Files Modified
- `backend/app/api/routes_dashboard.py` - Added sync from master to items
- `backend/app/services/watchlist_master_seed.py` - Fixed sync direction logic


