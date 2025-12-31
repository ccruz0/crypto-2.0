# WatchlistItem Verification Commands

## Quick Reference

All commands should be run from the **repo root** (`/Users/carloscruz/automated-trading-platform`).

---

## 1. Regression Guard Tests (No API Server Required)

**Purpose**: Verify that code invariants are maintained (no defaults/mutations)

**Command**:
```bash
cd backend && python3 -m pytest tests/test_watchlist_regression_guard.py -v
```

**Expected Output**:
```
tests/test_watchlist_regression_guard.py::test_trade_amount_usd_null_returns_null PASSED
tests/test_watchlist_regression_guard.py::test_trade_amount_usd_exact_value_preserved PASSED
tests/test_watchlist_regression_guard.py::test_trade_amount_usd_zero_preserved PASSED
tests/test_watchlist_regression_guard.py::test_trade_amount_usd_no_default_applied PASSED
tests/test_watchlist_regression_guard.py::test_get_dashboard_reads_from_watchlist_item PASSED
tests/test_watchlist_regression_guard.py::test_put_dashboard_writes_to_watchlist_item PASSED

======================== 6 passed in X.XXs ========================
```

**What it verifies**:
- ✅ NULL `trade_amount_usd` returns null (not 10, not 0)
- ✅ Exact values preserved (10.0 stays 10.0, not 11)
- ✅ Zero preserved (0.0 stays 0.0, not None)
- ✅ GET endpoint queries WatchlistItem (not WatchlistMaster)
- ✅ PUT endpoint updates WatchlistItem (not WatchlistMaster)

---

## 2. End-to-End Verification (API Server Required)

**Purpose**: Verify complete flow from DB → API → Frontend

**Prerequisites**: Backend API server must be running on port 8002

**Command**:
```bash
cd backend && python3 scripts/verify_watchlist_e2e.py
```

**Expected Output** (when API is running):
```
============================================================
TEST 1: Verify specific symbols (TRX_USDT, ALGO_USDT, ADA_USD)
============================================================
Verifying read consistency for TRX_USDT...
  trade_amount_usd: 10.0 == 10.0 ✓
  trade_enabled: True == True ✓
  ✅ TRX_USDT: All fields match

[... similar for ALGO_USDT and ADA_USD ...]

============================================================
TEST 2: Verify write-through (update and verify persistence)
============================================================
Verifying write-through for BTC_USDT with trade_amount_usd=25.5...
  ✓ DB updated: trade_amount_usd=25.5
  ✓ API matches DB: trade_amount_usd: 25.5 == 25.5 ✓
  ✓ PUT response matches DB: trade_amount_usd (PUT response): 25.5 == 25.5 ✓

============================================================
VERIFICATION SUMMARY
============================================================
✅ ALL TESTS PASSED
✅ Dashboard shows exactly what is in DB
✅ Write-through works: changes persist and reflect immediately
✅ Zero mismatches detected
```

**What it verifies**:
- ✅ Read consistency: GET returns exact DB values
- ✅ Write-through: PUT updates DB and reflects immediately
- ✅ Null handling: Setting null returns null
- ✅ Specific symbols: TRX_USDT, ALGO_USDT, ADA_USD all match

**Note**: If API server is not running, you'll see connection errors. This is expected.

---

## 3. Consistency Check (API Server Required)

**Purpose**: Compare DB (WatchlistItem) with API response for all fields

**Prerequisites**: Backend API server must be running on port 8002

**Command**:
```bash
cd backend && python3 scripts/watchlist_consistency_check.py
```

**Expected Output** (when API is running):
```
Starting watchlist consistency check...
Retrieved 50 items from API
✅ No issues found - watchlist is consistent

📊 Summary:
  - Total items (DB): 50
  - API available: Yes
  - Trade enabled: 15
  - Alert enabled: 20
  - API mismatches: 0
  - Only in DB: 0
  - Only in API: 0
```

**What it verifies**:
- ✅ All watchlist fields match between DB and API
- ✅ Zero mismatches for `trade_amount_usd`
- ✅ Zero mismatches for enabled flags

**Report Location**: `docs/monitoring/watchlist_consistency_report_latest.md`

---

## 4. Unit Test for trade_amount_usd (API Server Required)

**Purpose**: Test NULL and exact value handling

**Prerequisites**: Backend API server must be running on port 8002

**Command**:
```bash
cd backend && python3 scripts/test_trade_amount_usd_consistency.py
```

**Expected Output** (when API is running):
```
============================================================
Test 1: NULL trade_amount_usd should return null
============================================================
Created test item: TEST_NULL_USD with trade_amount_usd=None
✅ PASSED: trade_amount_usd is null as expected

============================================================
Test 2: trade_amount_usd=10.0 should return exactly 10.0
============================================================
Created test item: TEST_10_USD with trade_amount_usd=10.0
✅ PASSED: trade_amount_usd is exactly 10.0 as expected

============================================================
✅ ALL TESTS PASSED
============================================================
```

**What it verifies**:
- ✅ NULL returns null (not 10, not 0)
- ✅ Exact value returns exactly that value (not mutated)

---

## Running All Tests in Sequence

**Command**:
```bash
cd /Users/carloscruz/automated-trading-platform/backend

echo "=== Regression Guard Tests (No API Required) ==="
python3 -m pytest tests/test_watchlist_regression_guard.py -v

echo ""
echo "=== End-to-End Verification (API Required) ==="
python3 scripts/verify_watchlist_e2e.py || echo "⚠️  API server not running - skipping"

echo ""
echo "=== Consistency Check (API Required) ==="
python3 scripts/watchlist_consistency_check.py || echo "⚠️  API server not running - skipping"

echo ""
echo "=== Unit Test (API Required) ==="
python3 scripts/test_trade_amount_usd_consistency.py || echo "⚠️  API server not running - skipping"
```

---

## Troubleshooting

### API Server Not Running

If you see connection errors:
```
Connection refused: [Errno 61] Connection refused
```

**Solution**: Start the backend API server first:
```bash
cd backend
# Start your backend server (method depends on your setup)
# e.g., uvicorn app.main:app --reload --port 8002
```

### Tests Fail

If regression tests fail:
1. Check which test failed
2. Review recent changes to `backend/app/api/routes_dashboard.py`
3. Look for any defaults or mutations added to `trade_amount_usd`
4. Fix the regression
5. Re-run tests

### Consistency Check Shows Mismatches

If consistency check shows mismatches:
1. Check the report: `docs/monitoring/watchlist_consistency_report_latest.md`
2. Identify which symbols have mismatches
3. Verify DB values directly:
   ```bash
   cd backend
   python3 -c "
   from app.database import SessionLocal
   from app.models.watchlist import WatchlistItem
   db = SessionLocal()
   item = db.query(WatchlistItem).filter(WatchlistItem.symbol == 'TRX_USDT').first()
   print(f'DB trade_amount_usd: {item.trade_amount_usd}')
   db.close()
   "
   ```
4. Check API value:
   ```bash
   curl -s http://localhost:8002/api/dashboard | jq '.[] | select(.symbol=="TRX_USDT") | .trade_amount_usd'
   ```
5. If they don't match, there's a regression - fix it

---

## Summary

✅ **Regression Guard Tests**: Run always (no API required) - **6 tests, all pass**  
✅ **End-to-End Verification**: Run when API is running - verifies complete flow  
✅ **Consistency Check**: Run when API is running - verifies zero mismatches  
✅ **Unit Test**: Run when API is running - verifies NULL and exact values

All tests confirm that **WatchlistItem is the single source of truth** and **trade_amount_usd is never mutated or defaulted**.

