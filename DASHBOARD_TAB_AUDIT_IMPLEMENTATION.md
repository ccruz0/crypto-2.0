# Dashboard Tab Audit Implementation

**Date:** 2026-01-04  
**Status:** ✅ Complete

## Files Changed

### Frontend
1. **`frontend/src/app/page.tsx`**
   - ✅ Already has stable selectors: `data-testid="tab-{tabId}"` for all 8 tabs
   - No changes needed

2. **`frontend/scripts/dashboard_tabs_audit.cjs`** (enhanced)
   - Enhanced wait strategy: content detection + network settle (with timeout)
   - Added fallback selector support (data-testid → text)
   - Improved network request tracking with duration
   - Added failed requests grouping by endpoint
   - Added recommended fixes generation (prioritized A-D)
   - Enhanced summary with top 20 slow endpoints
   - Better error handling and content detection

3. **`frontend/package.json`**
   - ✅ Already has `"qa:tabs": "node scripts/dashboard_tabs_audit.cjs"`

4. **`frontend/tmp/dashboard_tab_audit/README.md`** (new)
   - Complete guide on how to run and interpret audits
   - Troubleshooting section
   - Common issues and fixes

## How to Run

### 1. Start Services
```bash
cd ~/automated-trading-platform
docker compose --profile local up -d --build db backend-dev

cd ~/automated-trading-platform/frontend
npm run dev
```

### 2. Run Audit
```bash
cd ~/automated-trading-platform/frontend
npm run qa:tabs
```

## Latest Evidence Folder Path

**Latest evidence folder:**
```
frontend/tmp/dashboard_tab_audit/2026-01-04T14-19-58-817Z/
```

**Contents:**
- `summary.md` - Human-readable report
- `summary.json` - Machine-readable summary
- `console.json` - All console messages
- `network.json` - All network requests with status + duration
- `tabs.json` - Tab-by-tab results
- `screenshots/` - Screenshots of all 8 tabs

## Latest Audit Results

**Overall Status:** ✅ PASS

**Summary:**
- Tabs: 8/8 loaded, 0 failed
- Console Errors: 0
- Page Errors: 0
- Failed Requests: 0
- Slow Requests (>5s): 5

**Tab Results:**
- ✅ Portfolio - PASS
- ✅ Watchlist - PASS
- ✅ Signals - PASS
- ✅ Orders - PASS
- ✅ Expected TP - PASS
- ✅ Executed Orders - PASS
- ✅ Monitoring - PASS
- ✅ Version History - PASS

## Fix Next (Ranked by Priority)

### Priority D: Slow Endpoints (5 requests >5s)

**Issue:** `/api/dashboard/state` taking 9-18 seconds

**Endpoints:**
- `GET /api/dashboard/state` - 18.71s, 13.47s, 9.67s, 5.09s
- `GET /api/dashboard/expected-take-profit` - 13.29s

**Recommended Fixes:**
1. **Add caching** - Cache dashboard state for 30-60s to avoid repeated heavy computations
2. **Optimize database queries** - Review queries in `_compute_dashboard_state()` for N+1 problems
3. **Reduce payload size** - Only return necessary fields, paginate large arrays
4. **Background computation** - Pre-compute dashboard state in background, serve from cache
5. **Add request deduplication** - Prevent multiple simultaneous requests to same endpoint

**Verify:**
```bash
# Check backend logs for slow queries
docker compose --profile local logs backend-dev | grep "PERF\|took.*seconds"

# Profile dashboard state computation
# Add timing logs in backend/app/api/routes_dashboard.py _compute_dashboard_state()
```

**No Priority A/B/C issues found** - All critical endpoints working, no CORS errors, no TypeScript errors.

## Tab Selectors Verified

All tabs have stable `data-testid` selectors:
- ✅ `tab-portfolio`
- ✅ `tab-watchlist`
- ✅ `tab-signals`
- ✅ `tab-orders`
- ✅ `tab-expected-take-profit`
- ✅ `tab-executed-orders`
- ✅ `tab-monitoring`
- ✅ `tab-version-history`

## Evidence Bundle Structure

```
frontend/tmp/dashboard_tab_audit/<timestamp>/
├── summary.md          # Human-readable report
├── summary.json        # Machine-readable summary
├── console.json        # All console messages
├── network.json        # All network requests
├── tabs.json           # Tab-by-tab results
└── screenshots/
    ├── 01_portfolio.png
    ├── 02_watchlist.png
    ├── 03_signals.png
    ├── 04_orders.png
    ├── 05_expected-take-profit.png
    ├── 06_executed-orders.png
    ├── 07_monitoring.png
    └── 08_version-history.png
```

## Summary Format

The `summary.md` includes:
- ✅ Total tabs tested (8)
- ✅ Failures count + list by tab
- ✅ Console errors count + top 20
- ✅ Failed requests count + grouped by endpoint
- ✅ Slow requests count + top 20
- ✅ Recommended next fixes (prioritized A-D)

## Notes

- All changes are **local-only** (gated by `ENVIRONMENT=local`)
- **AWS deployment unchanged** - no modifications to `backend-aws`
- Audit is stable (no flaky selectors)
- Evidence bundle is complete and timestamped
- `/api/health/system` endpoint exists and works correctly


