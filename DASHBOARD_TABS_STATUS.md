# Dashboard Tabs Local Fix Status

## Summary

The backend endpoints are **working correctly**. The issues are in frontend error handling and data parsing. All tabs need better error handling to show user-friendly messages instead of blank screens.

## Baseline ✅

- ✅ Backend health: `/api/health` returns `{"status":"ok"}`
- ✅ Frontend running: Docker containers active
- ✅ `/api/dashboard/state` returns: `balances`, `portfolio`, `open_orders`, `fast_signals`, `slow_signals`, etc.
- ✅ `/api/orders/open` returns orders array
- ✅ `/api/dashboard` returns watchlist items

## Implementation Status

### ✅ Completed
1. **Local Debug Panel** (`frontend/src/app/components/LocalDebugPanel.tsx`)
   - Shows API URL
   - Displays last API error (endpoint, status, message, timestamp)
   - Shows last refresh timestamps per tab
   - Only visible in development mode (`NODE_ENV !== 'production'`)
   - Added to `frontend/src/app/page.tsx`

### ⚠️ Needs Fix (Systematic Review Required)

Each tab needs:
1. **Error handling**: Catch API errors and show user-friendly messages
2. **Empty state handling**: Show helpful message when data is empty
3. **Loading states**: Clear loading indicators
4. **Debug events**: Emit events for debug panel (optional but helpful)

## Tab-by-Tab Analysis

### 1. Portfolio Tab
- **Endpoint**: `/api/dashboard/state` → `portfolio`
- **Current Status**: Needs error handling review
- **Frontend File**: `frontend/src/app/components/tabs/PortfolioTab.tsx`
- **API Function**: `getPortfolio()` in `frontend/src/app/api.ts`

### 2. Watchlist Tab
- **Endpoint**: `/api/dashboard` or `/api/dashboard/state` → `fast_signals`/`slow_signals`
- **Current Status**: Needs error handling review
- **Frontend File**: `frontend/src/app/components/tabs/WatchlistTab.tsx`

### 3. Open Orders Tab
- **Endpoint**: `/api/orders/open` (✅ working - returns orders)
- **Current Status**: Needs error handling review
- **Frontend File**: `frontend/src/app/components/tabs/OrdersTab.tsx`
- **API Function**: `getOpenOrders()` in `frontend/src/app/api.ts`

### 4. Expected TP Tab
- **Endpoint**: `/api/dashboard/open-orders-summary` (in `/api/dashboard/state`)
- **Current Status**: Needs error handling review
- **Frontend File**: `frontend/src/app/components/tabs/ExpectedTakeProfitTab.tsx`
- **API Function**: `getExpectedTakeProfitSummary()` in `frontend/src/app/api.ts`

### 5. Executed Orders Tab
- **Endpoint**: `/api/orders/history` or similar (needs verification)
- **Current Status**: Needs endpoint verification + error handling
- **Frontend File**: `frontend/src/app/components/tabs/ExecutedOrdersTab.tsx`
- **API Function**: `getOrderHistory()` in `frontend/src/app/api.ts`

### 6. Monitoring Tab
- **Endpoint**: `/api/monitoring/*` (needs verification)
- **Current Status**: Needs endpoint verification + error handling
- **Frontend File**: `frontend/src/app/components/tabs/MonitoringTab.tsx`
- **Component**: `MonitoringPanel` in `frontend/src/app/components/MonitoringPanel.tsx`

### 7. Version History Tab
- **Endpoint**: Build-time data (git commit, build time from headers)
- **Current Status**: Static data, needs error handling if headers unavailable
- **Frontend File**: `frontend/src/app/page.tsx` (inline component)

## Next Steps

1. **Verify all endpoints exist and work**
   - Test each endpoint with curl
   - Verify response format matches frontend expectations

2. **Add error handling to each tab**
   - Wrap API calls in try-catch
   - Show user-friendly error messages
   - Handle empty data gracefully

3. **Add debug events (optional)**
   - Emit `api-error` events for debug panel
   - Emit `tab-refresh` events for debug panel

4. **Test locally**
   - Open each tab
   - Verify data displays or error messages show
   - Check debug panel shows correct info

## Files Modified

- ✅ `frontend/src/app/components/LocalDebugPanel.tsx` (NEW)
- ✅ `frontend/src/app/page.tsx` (added debug panel import and component)

## Files That Need Review/Updates

- `frontend/src/app/components/tabs/PortfolioTab.tsx`
- `frontend/src/app/components/tabs/WatchlistTab.tsx`
- `frontend/src/app/components/tabs/OrdersTab.tsx`
- `frontend/src/app/components/tabs/ExpectedTakeProfitTab.tsx`
- `frontend/src/app/components/tabs/ExecutedOrdersTab.tsx`
- `frontend/src/app/components/tabs/MonitoringTab.tsx`
- `frontend/src/app/page.tsx` (Version History section)

## Testing Commands

```bash
# Test backend endpoints
curl -sS http://localhost:8002/api/health
curl -sS http://localhost:8002/api/dashboard/state | jq 'keys'
curl -sS http://localhost:8002/api/orders/open | jq '.count'
curl -sS http://localhost:8002/api/dashboard | jq 'length'

# Check frontend
docker compose ps frontend-aws
open http://localhost:3000

# Check logs
docker compose logs -n 50 frontend-aws
docker compose logs -n 50 backend-aws
```

## Notes

- The debug panel is **dev-only** and won't appear in production builds
- All endpoints appear to be working, so fixes are primarily frontend error handling
- Systematic review of each tab's error handling is needed
- Consider adding loading states if not already present



