# Dashboard Tab Audit - Final Report

**Date:** 2026-01-04  
**Status:** ✅ Complete

## Files Changed

### A) Tab Selectors
1. **`frontend/src/app/page.tsx`**
   - ✅ Verified: All 8 tabs have stable `data-testid="tab-{tabId}"` selectors
   - No changes needed (already correct)

### B) Dashboard Tab Audit Script
1. **`frontend/scripts/dashboard_tabs_audit.cjs`**
   - ✅ Enhanced with bounded waits, network tracking, ranked fixes
   - Captures: screenshots, console.json, network.json, tabs.json
   - Generates: summary.json and summary.md with ranked "Fix next" section

2. **`frontend/package.json`**
   - ✅ Verified: `"qa:tabs": "node scripts/dashboard_tabs_audit.cjs"` exists

3. **`frontend/tmp/dashboard_tab_audit/README.md`**
   - ✅ Complete guide on running and interpreting audits

### C) Portfolio + Watchlist Real Data

**Backend:**
1. **`backend/app/api/routes_portfolio.py`**
   - ✅ Verified: `/api/portfolio/snapshot?exchange=CRYPTO_COM` endpoint exists
   - ✅ Returns correct JSON format with `ok`, `as_of`, `exchange`, `message`, `missing_env`, `positions`, `totals`, `errors`
   - ✅ Added `price_source` field to positions (alongside `source` for compatibility)
   - ✅ Handles missing credentials (returns `ok:false`, `missing_env`)
   - ✅ Handles 40101/40103 errors with clear messages
   - ✅ Price sourcing: Crypto.com → CoinGecko → Yahoo → 0 with error
   - ✅ Debug logging gated by `ENVIRONMENT=local` or `PORTFOLIO_DEBUG=1`

**Frontend:**
1. **`frontend/src/app/api.ts`**
   - ✅ Updated: `getPortfolioSnapshot(exchange?: string)` accepts exchange parameter
   - ✅ Updated: `PortfolioSnapshotPosition` interface includes `price_source` field

2. **`frontend/src/app/components/tabs/PortfolioTab.tsx`**
   - ✅ Auto-fetches snapshot on load (StrictMode-safe)
   - ✅ Shows missing env vars section if `missing_env.length > 0`
   - ✅ Shows clear error message if `ok=false`
   - ✅ Shows positions table if `positions.length > 0`
   - ✅ Shows "No balances found" if `ok=true` but `positions` empty
   - ✅ Shows totals at top
   - ✅ Has Refresh button

3. **`frontend/src/app/components/tabs/WatchlistTab.tsx`**
   - ✅ Keeps existing real prices via `/api/market/top-coins-data`
   - ✅ Has "Holding" column showing:
     - "YES (amount)" if asset exists in portfolio snapshot
     - "NO" if snapshot ok but not held
     - "—" if snapshot not available
   - ✅ Caches snapshot client-side for 25s

### D) Portfolio/Watchlist Evidence Script
1. **`frontend/scripts/portfolio_watchlist_evidence.cjs`**
   - ✅ Enhanced to capture snapshot response body from network responses
   - ✅ Extracts snapshot data into summary.json (snapshot_ok, totals, positions_count)
   - ✅ Captures: screenshots, console.json, network.json, page_errors.json

2. **`frontend/package.json`**
   - ✅ Verified: `"qa:portfolio-watchlist": "node scripts/portfolio_watchlist_evidence.cjs"` exists

## Commands to Run

### 1. Start Services
```bash
cd ~/automated-trading-platform
docker compose --profile local up -d --build db backend-dev

cd ~/automated-trading-platform/frontend
npm run dev
```

### 2. Run Tab Audit
```bash
cd ~/automated-trading-platform/frontend
npm run qa:tabs
```

### 3. Run Portfolio/Watchlist Evidence
```bash
cd ~/automated-trading-platform/frontend
npm run qa:portfolio-watchlist
```

## Latest Evidence Folder Paths

### Tab Audit
```
frontend/tmp/dashboard_tab_audit/2026-01-04T14-58-32-994Z/
```

**Contents:**
- `summary.md` - Human-readable report with ranked fixes
- `summary.json` - Machine-readable summary
- `console.json` - All console messages (level, text, timestamp)
- `network.json` - All network requests (url, method, status, duration_ms, failed)
- `tabs.json` - Tab-by-tab results (tabId, ok, notes, key visible markers)
- `screenshots/` - 8 screenshots (01_portfolio.png through 08_version-history.png)

### Portfolio/Watchlist Evidence
```
frontend/tmp/portfolio_watchlist_evidence/2026-01-04T15-04-06-428Z/
```

**Contents:**
- `summary.md` - Summary with snapshot status, totals, positions count
- `summary.json` - Machine-readable summary (includes snapshot_ok, totals, positions_count)
- `console.json` - All console messages
- `network.json` - All network requests with response bodies for `/api/portfolio/snapshot`
- `page_errors.json` - Page-level errors
- `screenshots/` - 2 screenshots:
  - `01_portfolio.png` - Portfolio tab with live snapshot
  - `02_watchlist.png` - Watchlist tab with real prices + holding column

## Latest Audit Results

### Tab Audit
- **Overall Status:** ✅ PASS
- **Tabs:** 8/8 loaded, 0 failed
- **Console Errors:** 0
- **Page Errors:** 0
- **Failed Requests:** 0
- **Slow Requests:** 8 (>5s)

**All Tabs:** ✅ PASS
- Portfolio ✅
- Watchlist ✅
- Signals ✅
- Orders ✅
- Expected TP ✅
- Executed Orders ✅
- Monitoring ✅
- Version History ✅

### Portfolio/Watchlist Evidence
- **Snapshot OK:** ❌ (credentials not configured - expected in local dev)
- **Positions:** 0
- **Watchlist Rows:** 21
- **Total Value:** $0.00
- **Console Errors:** 0
- **Failed Requests:** 0

## Fix Next (Ranked List)

### Priority D: Slow Endpoints

**Issue:** 8 requests taking >5 seconds

**Slow Endpoints:**
1. `GET /api/dashboard/state` - Multiple requests taking 5-18 seconds
2. `GET /api/dashboard/expected-take-profit` - Multiple requests taking 11-17 seconds

**Recommended Fixes:**
1. **Add caching** - Cache `/api/dashboard/state` for 30-60s
2. **Optimize database queries** - Review `_compute_dashboard_state()` for N+1 problems
3. **Reduce payload size** - Only return necessary fields, paginate large arrays
4. **Background computation** - Pre-compute dashboard state, serve from cache
5. **Request deduplication** - Prevent multiple simultaneous requests

**Verify:**
```bash
# Check backend logs for slow queries
docker compose --profile local logs backend-dev | grep "PERF\|took.*seconds"

# Profile dashboard state computation
# Add timing logs in backend/app/api/routes_dashboard.py
```

**No Priority A/B/C Issues** - All critical endpoints working, no CORS errors, no TypeScript errors, no missing data endpoints.

## Summary

✅ **All tabs pass** - 8/8 tabs loaded successfully  
✅ **No console errors** - 0 console errors, 0 page errors  
✅ **No failed requests** - All API endpoints responding correctly  
⚠️ **Slow endpoints** - 8 requests >5s (Priority D - non-blocking)  
✅ **Portfolio/Watchlist** - Real data integration complete (requires credentials for live data)

The audit system is complete and ready for repeatable tab testing with evidence collection.


