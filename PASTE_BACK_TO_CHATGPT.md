# PASTE BACK TO CHATGPT

## Changes Made

### Files Modified/Created:

1. **backend/scripts/verify_watchlist_e2e.py** (NEW)
   - Created end-to-end verification script
   - Includes E2E_WRITE_TEST=1 safety flag for write operations
   - Verifies: DB ↔ API consistency, write-through, strategy_key resolution
   - Read-only by default; requires env flag for writes

2. **backend/scripts/watchlist_consistency_check.py** (MODIFIED)
   - Added `get_resolved_strategy_key()` function
   - Added strategy comparison: Strategy (DB) vs Strategy (API) columns
   - Normalizes "no strategy" values (None/"No strategy"/empty)
   - Mismatch count includes strategy mismatches

3. **backend/app/api/routes_dashboard.py** (MODIFIED - already committed)
   - Returns `strategy_key`, `strategy_preset`, `strategy_risk` in API response
   - Strategy resolved via `resolve_strategy_profile()` (preset from trading_config.json catalog + risk from WatchlistItem.sl_tp_mode)

4. **frontend/src/app/components/tabs/WatchlistTab.tsx** (MODIFIED - in submodule)
   - Uses API `strategy_key` as single source of truth
   - Removed `updateCoinConfig()` calls (no writes to trading_config.json)
   - Added regression guards for dropdown/tooltip consistency
   - Dropdown and tooltip use same `getCoinStrategy()` function

5. **frontend/src/lib/api.ts** (MODIFIED - in submodule)
   - Added `strategy_preset`, `strategy_risk`, `strategy_key` to `TopCoin` interface

## verify_watchlist_e2e.py Status

✅ **EXISTS in main branch** (commit a2abcd3)
- File: `backend/scripts/verify_watchlist_e2e.py`
- Committed: "Verify watchlist strategy consistency (E2E + report)"

## AWS Commands to Run (DO NOT RUN YET - LIST ONLY)

```bash
# 1. Consistency check (read-only, safe)
cd /path/to/repo/backend
python3 scripts/watchlist_consistency_check.py

# 2. E2E verification (read-only mode, safe)
python3 scripts/verify_watchlist_e2e.py

# 3. E2E verification with writes (requires flag, modifies DB)
E2E_WRITE_TEST=1 python3 scripts/verify_watchlist_e2e.py
```

## Expected PASS Output Patterns

### Consistency Check (`watchlist_consistency_check.py`):

**Expected:**
```
✅ No Issues Found
All watchlist items are consistent between API and database.

## Watchlist Items
| Symbol | Trade | Alert | Buy Alert | Sell Alert | Strategy (DB) | Strategy (API) | Throttle | In API | Issues |
|--------|-------|-------|-----------|------------|---------------|---------------|----------|--------|--------|
| ADA_USD | ✅ | ✅ | ✅ | ❌ | swing-conservative | swing-conservative | — | ✅ | — |
```

**PASS Criteria:**
- Zero mismatches in "API Mismatches" count
- Strategy (DB) column matches Strategy (API) column for all rows
- No ⚠️ warning indicators in strategy columns

### E2E Verification (`verify_watchlist_e2e.py` - read-only):

**Expected:**
```
TEST 1: Verify specific symbols (TRX_USDT, ALGO_USDT, ADA_USD) - READ ONLY
  ✅ TRX_USDT: All fields match
  ✅ ALGO_USDT: All fields match
  ✅ ADA_USD: All fields match

TEST 2: Skipped (write tests disabled)
To enable write tests, set: E2E_WRITE_TEST=1

VERIFICATION SUMMARY
✅ ALL TESTS PASSED
✅ Dashboard shows exactly what is in DB
✅ Write-through works: changes persist and reflect immediately
✅ Zero mismatches detected
```

**PASS Criteria:**
- All symbols show "All fields match" including `strategy_key`
- Exit code 0
- No "SOME TESTS FAILED" message

### E2E Verification with Writes (`E2E_WRITE_TEST=1`):

**Expected:**
```
Write tests enabled: True (set E2E_WRITE_TEST=1 to enable)

TEST 2: Verify write-through (update and verify persistence) - WRITE MODE
Testing with BTC_USDT (original trade_amount_usd: 10.0, sl_tp_mode: conservative)
  ✓ DB updated: trade_amount_usd=25.5
  ✓ API matches DB: trade_amount_usd: 25.5 == 25.5 ✓
  ✓ Strategy write-through verified: strategy_key=swing-aggressive
  Restored original trade_amount_usd: 10.0
  Restored original sl_tp_mode: conservative

✅ ALL TESTS PASSED
```

**PASS Criteria:**
- All write operations succeed
- Original values restored
- Exit code 0
- No errors in logs

## If Mismatches Remain

### Strategy Mismatches:

**Look for:**
- `strategy: DB=swing-conservative, API=None` or similar
- ⚠️ indicators in consistency report strategy columns

**Where to check:**
1. **Backend API** (`backend/app/api/routes_dashboard.py`):
   - `_serialize_watchlist_item()` function
   - Verify `resolve_strategy_profile()` is called correctly
   - Check `strategy_key` computation: `f"{strategy_type.value}-{risk_approach.value}"`

2. **Database** (`WatchlistItem`):
   - Check `sl_tp_mode` column (should be "conservative" or "aggressive")
   - Verify `trading_config.json` has preset for symbol (catalog)

3. **Frontend** (`frontend/src/app/components/tabs/WatchlistTab.tsx`):
   - Verify `getCoinStrategy()` prioritizes `coin.strategy_key`
   - Check browser console for `[STRATEGY_MISMATCH]` warnings
   - Ensure dropdown and tooltip use same function

### Field Mismatches (trade_amount_usd, etc.):

**Look for:**
- `trade_amount_usd: DB=10.0, API=11.0` or similar

**Where to check:**
1. **API serialization** - verify no defaults applied
2. **Database values** - check WatchlistItem table directly
3. **Frontend state** - verify using API response, not local computation

## Git Status Summary

**Committed files:**
- `backend/scripts/verify_watchlist_e2e.py` (NEW)
- `backend/scripts/watchlist_consistency_check.py` (MODIFIED)
- `backend/app/api/routes_dashboard.py` (MODIFIED)

**Commit:** `a2abcd3` - "Verify watchlist strategy consistency (E2E + report)"

**Frontend files** (in submodule, separately committed):
- `frontend/src/app/components/tabs/WatchlistTab.tsx`
- `frontend/src/lib/api.ts`

## Verification Complete

All scripts exist and are committed to main branch. Ready for AWS deployment verification.

