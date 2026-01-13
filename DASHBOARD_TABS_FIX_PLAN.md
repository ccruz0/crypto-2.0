# Dashboard Tabs Fix Plan

## Baseline Status

✅ **Backend Health**: Working (`/api/health`)
✅ **Frontend Running**: Yes (docker compose)
✅ **Endpoints Available**:
- `/api/dashboard/state` - Returns portfolio, balances, signals, open_orders
- `/api/orders/open` - Returns open orders
- `/api/dashboard` - Returns watchlist items

⚠️ **Issues to Fix**:
1. Frontend may not be parsing responses correctly
2. Error handling may not show user-friendly messages
3. Some tabs may fail silently with empty data
4. Local dev needs better observability

## Implementation Plan

### Step 1: Add Local Debug Panel (Dev-Only)
- Component: `frontend/src/app/components/LocalDebugPanel.tsx`
- Shows: API URL, last errors, refresh timestamps
- Only visible when `process.env.NODE_ENV !== 'production'`

### Step 2: Fix Each Tab Systematically

For each tab:
1. Check what API endpoint it calls
2. Test endpoint manually with curl
3. Check frontend parsing/logic
4. Add error handling with user-friendly messages
5. Ensure empty states are handled gracefully

**Tab Order**:
1. Portfolio (`/api/dashboard/state` → `portfolio`)
2. Watchlist (`/api/dashboard` or `/api/dashboard/state` → `fast_signals`/`slow_signals`)
3. Open Orders (`/api/orders/open`)
4. Expected TP (`/api/dashboard/open-orders-summary`)
5. Executed Orders (`/api/orders/history` or similar)
6. Monitoring (`/api/monitoring/*`)
7. Version History (build info, git commit)

### Step 3: Data Strategy for Local Dev
- If endpoints return empty data, show helpful messages
- Consider mock data for local dev (optional)
- Ensure error messages explain what's missing

## Files to Modify

### Frontend
- `frontend/src/app/components/LocalDebugPanel.tsx` (NEW)
- `frontend/src/app/page.tsx` (add debug panel, improve error handling)
- `frontend/src/app/components/tabs/PortfolioTab.tsx` (error handling)
- `frontend/src/app/components/tabs/WatchlistTab.tsx` (error handling)
- `frontend/src/app/components/tabs/OrdersTab.tsx` (error handling)
- `frontend/src/app/components/tabs/ExpectedTakeProfitTab.tsx` (error handling)
- `frontend/src/app/components/tabs/ExecutedOrdersTab.tsx` (error handling)
- `frontend/src/app/components/tabs/MonitoringTab.tsx` (error handling)
- `frontend/src/app/components/tabs/VersionHistoryTab.tsx` (error handling)

### Backend (if needed)
- May need to add error logging
- May need to ensure endpoints return consistent formats

## Verification Checklist

After fixes:
- [ ] Portfolio tab loads and shows data or error message
- [ ] Watchlist tab loads and shows data or error message
- [ ] Open Orders tab loads and shows data or error message
- [ ] Expected TP tab loads and shows data or error message
- [ ] Executed Orders tab loads and shows data or error message
- [ ] Monitoring tab loads and shows data or error message
- [ ] Version History tab loads and shows data or error message
- [ ] Debug panel shows API URL and errors (dev mode only)
- [ ] All tabs show user-friendly error messages instead of blank screens



