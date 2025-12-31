# WatchlistItem Regression Guard

## Overview

This document describes the regression guards put in place to ensure that `WatchlistItem` remains the single source of truth and that `trade_amount_usd` is never mutated or defaulted.

## Regression Guards Implemented

### 1. Code Comments (Inline Documentation)

**Location**: `backend/app/api/routes_dashboard.py`

#### Serialization Function (Line ~117)
```python
# REGRESSION GUARD: trade_amount_usd must be returned exactly as stored in DB
# - If DB is NULL, API must return null (NOT 10, NOT 0, NOT any default)
# - If DB is 10.0, API must return 10.0 (NOT 11, NOT mutated)
# - This field is the single source of truth - no defaults/mutations allowed
# - Any change that adds defaults here will break the consistency guarantee
"trade_amount_usd": item.trade_amount_usd,
```

#### GET Endpoint (Line ~1086)
```python
"""
REGRESSION GUARD: This function MUST query WatchlistItem, NOT WatchlistMaster.
Changing this to query WatchlistMaster will break the "DB is truth" guarantee.
See tests/test_watchlist_regression_guard.py for regression tests.
"""
```

#### PUT Endpoint (Line ~1138)
```python
"""
REGRESSION GUARD: This function MUST update WatchlistItem, NOT WatchlistMaster.
Changing this to update WatchlistMaster will break the "DB is truth" guarantee.
See tests/test_watchlist_regression_guard.py for regression tests.
"""
```

### 2. Unit Tests (Automated Regression Tests)

**Location**: `backend/tests/test_watchlist_regression_guard.py`

These tests will **FAIL** if any regression is introduced:

1. **test_trade_amount_usd_null_returns_null**: Ensures NULL stays NULL (not 10, not 0)
2. **test_trade_amount_usd_exact_value_preserved**: Ensures 10.0 stays 10.0 (not 11)
3. **test_trade_amount_usd_zero_preserved**: Ensures 0.0 stays 0.0 (not None)
4. **test_trade_amount_usd_no_default_applied**: Tests multiple scenarios
5. **test_get_dashboard_reads_from_watchlist_item**: Ensures GET queries WatchlistItem
6. **test_put_dashboard_writes_to_watchlist_item**: Ensures PUT updates WatchlistItem

## Running Regression Tests

### Prerequisites
- Backend dependencies installed
- Database accessible (for DB tests)
- API server NOT required (tests run against code directly)

### Run All Regression Tests

```bash
cd /Users/carloscruz/automated-trading-platform/backend

# Run regression guard tests
pytest tests/test_watchlist_regression_guard.py -v
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

### Run Specific Test

```bash
# Test NULL handling
pytest tests/test_watchlist_regression_guard.py::test_trade_amount_usd_null_returns_null -v

# Test exact value preservation
pytest tests/test_watchlist_regression_guard.py::test_trade_amount_usd_exact_value_preserved -v
```

## What These Guards Prevent

### ❌ Prevented: Adding Defaults
```python
# BAD - This would fail regression tests
"trade_amount_usd": item.trade_amount_usd or 10.0,  # ❌ REGRESSION
```

### ❌ Prevented: Mutating Values
```python
# BAD - This would fail regression tests
"trade_amount_usd": item.trade_amount_usd + 1.0,  # ❌ REGRESSION
```

### ❌ Prevented: Querying Wrong Table
```python
# BAD - This would fail regression tests
items = db.query(WatchlistMaster).filter(...)  # ❌ REGRESSION
```

### ✅ Allowed: Exact DB Value
```python
# GOOD - This passes regression tests
"trade_amount_usd": item.trade_amount_usd,  # ✅ CORRECT
```

## Integration with CI/CD

These regression tests should be run as part of:
- Pre-commit hooks (optional but recommended)
- CI pipeline (required)
- Before deploying to production

### Example CI Configuration

```yaml
# .github/workflows/test.yml
- name: Run Watchlist Regression Tests
  run: |
    cd backend
    pytest tests/test_watchlist_regression_guard.py -v
```

## Manual Verification (When API Server is Running)

### 1. End-to-End Verification
```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 scripts/verify_watchlist_e2e.py
```

**Expected**: All tests pass, zero mismatches

### 2. Consistency Check
```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 scripts/watchlist_consistency_check.py
```

**Expected**: 0 mismatches for `trade_amount_usd`

### 3. Unit Test
```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 scripts/test_trade_amount_usd_consistency.py
```

**Expected**: All tests pass

## What to Do If Tests Fail

1. **Identify the regression**: Check which test failed and why
2. **Review recent changes**: Look at git history for changes to:
   - `backend/app/api/routes_dashboard.py` (serialization or endpoints)
   - Any code that modifies `trade_amount_usd`
3. **Fix the regression**: Remove any defaults/mutations
4. **Re-run tests**: Ensure all tests pass
5. **Update documentation**: If behavior intentionally changed, update this doc

## Maintenance

- **When adding new watchlist fields**: Consider if they need similar guards
- **When refactoring**: Ensure regression tests still pass
- **When changing serialization**: Review regression guard comments
- **When changing endpoints**: Ensure they still use WatchlistItem

## Summary

✅ **Code comments** document the invariant  
✅ **Unit tests** automatically detect regressions  
✅ **Integration tests** verify end-to-end behavior  
✅ **CI/CD integration** prevents regressions from reaching production

These guards ensure that the "DB is single source of truth" guarantee is maintained and cannot be accidentally broken by future changes.

