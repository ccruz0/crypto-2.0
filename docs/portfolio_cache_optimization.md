# Portfolio Cache Performance Optimization

## Summary

Optimized the portfolio cache service to address performance issues and authentication error handling.

## Issues Addressed

1. **Slow Portfolio Summary Fetches**: Queries taking 0.3s - 6.9s instead of target < 0.2s
2. **Multiple Concurrent Fetches**: Many redundant portfolio summary requests
3. **Authentication Errors**: Repeated 40101 errors causing failed cache updates
4. **Inefficient Queries**: Python-side deduplication instead of SQL-based optimization

## Optimizations Implemented

### 1. SQL Query Optimization

**Before**: Fetching all balances and deduplicating in Python
```python
balances_query = db.query(PortfolioBalance).order_by(...).all()
# Then deduplicate in Python
```

**After**: Using SQL window functions to get latest balance per currency
```sql
SELECT currency, balance, usd_value
FROM (
    SELECT currency, balance, usd_value,
           ROW_NUMBER() OVER (PARTITION BY currency ORDER BY id DESC) as rn
    FROM portfolio_balances
) ranked
WHERE rn = 1
ORDER BY usd_value DESC
```

**Benefits**:
- Database does the deduplication (much faster)
- Only fetches the data we need
- Works efficiently even with large datasets

### 2. Request Deduplication

Added a lock mechanism to prevent multiple concurrent portfolio cache updates:

```python
# Minimum 60 seconds between cache updates
_min_update_interval = 60
_update_lock = threading.Lock()
```

**Benefits**:
- Prevents redundant API calls to Crypto.com
- Reduces database load
- Caches recent results for quick responses

### 3. Cached Table Existence Checks

**Before**: Multiple `inspector.get_table_names()` calls (slow)
```python
inspector = inspect(db.bind)
tables = inspector.get_table_names()
if 'portfolio_loans' in tables:
```

**After**: Cached table existence checks
```python
def _table_exists(db: Session, table_name: str) -> bool:
    # Cache results to avoid repeated inspector calls
```

**Benefits**:
- Eliminates repeated database metadata queries
- Significantly faster when checking table existence multiple times

### 4. Authentication Error Handling

**Before**: Generic error handling, immediate retries
```python
except Exception as e:
    logger.error(f"Error: {e}")
    return {"success": False, "error": str(e)}
```

**After**: Specific detection of authentication errors
```python
if "40101" in error_str or "Authentication failure" in error_str:
    logger.error(f"Crypto.com API authentication failed: {error_str}")
    return {"success": False, "error": error_msg, "auth_error": True}
```

**Benefits**:
- Prevents repeated failed authentication attempts
- Clearer error messages for debugging
- Dashboard can handle auth errors appropriately

### 5. Better Performance Logging

Added detailed timing information:
```python
query_elapsed = time_module.time() - query_start
if query_elapsed > 0.1:
    logger.debug(f"Balance query took {query_elapsed:.3f}s")
```

**Benefits**:
- Identifies which operations are slow
- Helps with future optimization

## Database Index Recommendation

For even better performance, consider adding a composite index:

```sql
CREATE INDEX IF NOT EXISTS idx_portfolio_balances_currency_id 
ON portfolio_balances(currency, id DESC);
```

This index will optimize the window function query that gets the latest balance per currency.

## Expected Performance Improvements

- **Portfolio Summary Fetches**: Should now be < 0.2s (down from 0.3s - 6.9s)
- **Reduced API Calls**: Request deduplication prevents redundant Crypto.com API calls
- **Faster Table Checks**: Cached table existence checks eliminate metadata queries
- **Better Error Handling**: Authentication errors are detected and handled gracefully

## Testing

Monitor the logs for:
- `Portfolio summary fetched in X.XXXs` - should be < 0.2s
- `⚠️ Portfolio summary fetch took X.XXXs` - should appear less frequently
- Authentication errors should be logged clearly with actionable messages

## Files Modified

1. `backend/app/services/portfolio_cache.py`
   - Optimized `get_portfolio_summary()` with SQL window functions
   - Added request deduplication in `update_portfolio_cache()`
   - Added cached table existence checks
   - Improved authentication error handling

2. `backend/app/api/routes_dashboard.py`
   - Improved error handling for authentication failures
   - Better logging for auth errors

