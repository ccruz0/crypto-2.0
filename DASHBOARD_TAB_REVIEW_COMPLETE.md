# Dashboard Tab Review - Complete Implementation

**Date:** 2026-01-04  
**Status:** ✅ Complete

## Files Changed

### Part 1: Tab Audit System

1. **`frontend/src/app/page.tsx`**
   - ✅ Verified: All 8 tabs have stable `data-testid="tab-{tabId}"` selectors
   - No changes needed (already correct)

2. **`frontend/scripts/dashboard_tabs_audit.cjs`** (enhanced)
   - Enhanced wait strategy with bounded timeouts
   - Added fallback selectors (data-testid → text)
   - Network tracking with `duration_ms` field
   - Failed requests grouped by endpoint
   - Recommended fixes generation (prioritized A-D)
   - Enhanced data missing detection (portfolio/watchlist)
   - Top 20 slow endpoints in summary

3. **`frontend/package.json`**
   - ✅ Verified: `"qa:tabs": "node scripts/dashboard_tabs_audit.cjs"` exists

4. **`frontend/tmp/dashboard_tab_audit/README.md`**
   - Complete guide on running and interpreting audits

### Part 2: Portfolio + Watchlist Real Data

1. **`backend/app/api/routes_portfolio.py`**
   - ✅ Verified: `/api/portfolio/snapshot?exchange=CRYPTO_COM` endpoint exists
   - Returns correct JSON format with `ok`, `as_of`, `exchange`, `message`, `missing_env`, `positions`, `totals`, `errors`
   - Handles missing credentials (returns `ok:false`, `missing_env`)
   - Handles 40101/40103 errors with clear messages
   - Price sourcing: Crypto.com → CoinGecko → Yahoo → 0 with error
   - Debug logging gated by `ENVIRONMENT=local` or `PORTFOLIO_DEBUG=1`

2. **`frontend/src/app/api.ts`**
   - ✅ Verified: `getPortfolioSnapshot()` function exists

3. **`frontend/src/app/components/tabs/PortfolioTab.tsx`**
   - ✅ Auto-fetches snapshot on load (StrictMode-safe)
   - ✅ Shows missing env vars section if `missing_env.length > 0`
   - ✅ Shows clear error message if `ok=false`
   - ✅ Shows positions table if `positions.length > 0`
   - ✅ Shows "No balances found" if `ok=true` but `positions` empty
   - ✅ Shows totals at top
   - ✅ Has Refresh button

4. **`frontend/src/app/components/tabs/WatchlistTab.tsx`**
   - ✅ Keeps existing real prices via `/api/market/top-coins-data`
   - ✅ Has "Holding" column showing:
     - "YES (amount)" if asset exists in portfolio snapshot
     - "NO" if snapshot ok but not held
     - "—" if snapshot not available
   - ✅ Caches snapshot client-side for 25s

### Part 3: Evidence Scripts

1. **`frontend/scripts/portfolio_watchlist_evidence.cjs`** (enhanced)
   - Opens dashboard
   - Goes to Portfolio tab, clicks refresh, waits for response, screenshot
   - Goes to Watchlist tab, waits, screenshot
   - Captures network + console like tab audit
   - Extracts snapshot response body from network responses
   - Includes key fields in summary.json
   - Saves under `frontend/tmp/portfolio_watchlist_evidence/<timestamp>/`

2. **`frontend/package.json`**
   - ✅ Verified: `"qa:portfolio-watchlist": "node scripts/portfolio_watchlist_evidence.cjs"` exists

## How to Run

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
frontend/tmp/dashboard_tab_audit/2026-01-04T14-50-28-711Z/
```

**Contents:**
- `summary.md` - Human-readable report with ranked fixes
- `summary.json` - Machine-readable summary
- `console.json` - All console messages
- `network.json` - All network requests (url, method, status, duration_ms, failed)
- `tabs.json` - Tab-by-tab results
- `screenshots/` - 8 screenshots (01_portfolio.png through 08_version-history.png)

### Portfolio/Watchlist Evidence
```
frontend/tmp/portfolio_watchlist_evidence/2026-01-04T14-51-58-690Z/
```

**Contents:**
- `summary.md` - Summary with snapshot status, totals, positions count
- `summary.json` - Machine-readable summary
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
- **Slow Requests:** 6 (>5s)

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

**Issue:** 6 requests taking >5 seconds

**Slow Endpoints:**
1. `GET /api/dashboard/state` - 17.65s, 14.40s, 7.00s, 5.55s
2. `GET /api/dashboard/expected-take-profit` - 16.81s, 11.82s

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

## Tab Selectors Verified

All 8 tabs have stable `data-testid` selectors:
- ✅ `tab-portfolio`
- ✅ `tab-watchlist`
- ✅ `tab-signals`
- ✅ `tab-orders`
- ✅ `tab-expected-take-profit`
- ✅ `tab-executed-orders`
- ✅ `tab-monitoring`
- ✅ `tab-version-history`

## Summary Report Format

### Tab Audit Summary
- ✅ Total tabs tested (8)
- ✅ Failures count + list by tab
- ✅ Console errors count + top 20
- ✅ Failed requests count + grouped by endpoint
- ✅ Slow requests count (>5000ms) + top 20
- ✅ "Fix next" list ranked by impact (A-D priority)

### Portfolio/Watchlist Summary
- ✅ Snapshot `ok` status
- ✅ Totals (total_value_usd, total_assets_usd, etc.)
- ✅ Positions count
- ✅ Watchlist rows count
- ✅ Failed requests count
- ✅ Console errors count

## Network Request Format

Each request in `network.json` includes:
- `url` - Full request URL
- `method` - HTTP method (GET, POST, etc.)
- `status` - HTTP status code
- `duration_ms` - Request duration in milliseconds
- `failed` - Boolean indicating if request failed (status >= 400)
- `responseBody` - Response body for `/api/portfolio/snapshot` requests

## Notes

- ✅ All changes are **local-only** (gated by `ENVIRONMENT=local` or local profile)
- ✅ **AWS deployment unchanged** - no modifications to `backend-aws`
- ✅ Audit is stable (no flaky selectors)
- ✅ Evidence bundles are complete and timestamped
- ✅ Summary includes ranked fixes
- ✅ No secrets logged
- ✅ Portfolio shows "No balances found" when `ok=true` but `positions` empty
- ✅ Watchlist shows holdings from portfolio snapshot (cached 25s)

## Acceptance Criteria Status

- ✅ `npm run qa:tabs` always produces a complete evidence bundle
- ✅ `npm run qa:portfolio-watchlist` always produces a complete evidence bundle
- ✅ Tab selection is stable (data-testid selectors verified)
- ✅ Summary includes ranked fixes (A-D priority)
- ✅ AWS remains unchanged (no backend-aws modifications)
- ✅ Portfolio shows real balances from Crypto.com (when credentials configured)
- ✅ Watchlist shows real prices and holdings
- ✅ Evidence saved under correct paths



