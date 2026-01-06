# Dashboard Tab Audit Workflow - Complete

**Date:** 2026-01-04  
**Status:** ✅ Complete and Verified

## Files Changed

### Frontend
1. **`frontend/src/app/page.tsx`**
   - ✅ Verified: All 8 tabs have stable `data-testid="tab-{tabId}"` selectors
   - No changes needed (already correct)

2. **`frontend/scripts/dashboard_tabs_audit.cjs`** (enhanced)
   - Enhanced wait strategy with bounded timeouts
   - Added fallback selectors (data-testid → text)
   - Network tracking with `duration_ms` field (matches requirements)
   - Failed requests grouped by endpoint
   - Recommended fixes generation (prioritized A-D)
   - Enhanced data missing detection (portfolio/watchlist)
   - Top 20 slow endpoints in summary

3. **`frontend/package.json`**
   - ✅ Verified: `"qa:tabs": "node scripts/dashboard_tabs_audit.cjs"` exists

4. **`frontend/tmp/dashboard_tab_audit/README.md`** (verified)
   - Complete guide on running and interpreting audits
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

```
frontend/tmp/dashboard_tab_audit/2026-01-04T14-31-28-109Z/
```

**Contents:**
- `summary.md` - Human-readable report with recommended fixes
- `summary.json` - Machine-readable summary with all metrics
- `console.json` - All console messages (all levels)
- `network.json` - All network requests (url, method, status, duration_ms, failed)
- `tabs.json` - Tab-by-tab results with status
- `screenshots/` - 8 screenshots:
  - `01_portfolio.png`
  - `02_watchlist.png`
  - `03_signals.png`
  - `04_orders.png`
  - `05_expected-take-profit.png`
  - `06_executed-orders.png`
  - `07_monitoring.png`
  - `08_version-history.png`

## Latest Audit Results

**Overall Status:** ✅ PASS

**Summary:**
- **Tabs:** 8/8 loaded, 0 failed
- **Console Errors:** 0
- **Page Errors:** 0
- **Failed Requests:** 0
- **Slow Requests (>5s):** 9

**All Tabs:** ✅ PASS
- Portfolio ✅
- Watchlist ✅
- Signals ✅
- Orders ✅
- Expected TP ✅
- Executed Orders ✅
- Monitoring ✅
- Version History ✅

## Fix Next (Ranked List)

### Priority D: Slow Endpoints

**Issue:** 9 requests taking >5 seconds

**Slow Endpoints:**
1. `GET /api/dashboard/state` - 20.34s, 16.50s, 12.09s, 10.99s
2. `GET /api/dashboard/expected-take-profit` - 15.80s, 7.90s
3. `GET /api/dashboard` - 5.08s, 5.04s
4. `GET /api/portfolio/snapshot` - 5.01s

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

**No Priority A/B/C Issues** - All critical endpoints working, no CORS errors, no TypeScript errors, no missing data.

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

The `summary.md` includes:
- ✅ Total tabs tested (8)
- ✅ Failures count + list by tab
- ✅ Console errors count + top 20
- ✅ Failed requests count + grouped by endpoint
- ✅ Slow requests count (>5000ms) + top 20
- ✅ "Fix next" list ranked by impact (A-D priority)

## Network Request Format

Each request in `network.json` includes:
- `url` - Full request URL
- `method` - HTTP method (GET, POST, etc.)
- `status` - HTTP status code
- `duration_ms` - Request duration in milliseconds
- `failed` - Boolean indicating if request failed (status >= 400)

## Notes

- ✅ All changes are **local-only** (gated by `ENVIRONMENT=local` or local profile)
- ✅ **AWS deployment unchanged** - no modifications to `backend-aws`
- ✅ Audit is stable (no flaky selectors)
- ✅ Evidence bundle is complete and timestamped
- ✅ Summary includes ranked fixes
- ✅ No secrets logged

## Acceptance Criteria Status

- ✅ `npm run qa:tabs` always produces a complete evidence bundle
- ✅ Tab selection is stable (data-testid selectors verified)
- ✅ Summary includes ranked fixes (A-D priority)
- ✅ AWS remains unchanged (no backend-aws modifications)


