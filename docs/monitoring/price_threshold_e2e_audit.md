# Price Threshold E2E Audit Report

## Overview
This document tracks the end-to-end verification of price change threshold behavior when changing thresholds from $10 to $11, $3, and "no limit" (0).

## Test Execution Steps

### Phase 0: Observability (Completed)
- ✅ Added structured logging with unique `evaluation_id` per symbol per run
- ✅ Logging added for:
  - UI toggle events (BUY/SELL alert enabled/disabled)
  - Config loading (throttle settings, strategy, environment)
  - Signal evaluation (symbol, side, price, delta $/%, time since last alert, decision ACCEPT/BLOCK, blocking rules)
  - Telegram send attempts (success/failure, message id)
  - Order creation attempts (request payload, exchange response, order id)

### Phase 1: Browser Test (Completed)
- ✅ Created Playwright test: `frontend/tests/e2e/price-threshold-e2e.spec.ts`
- ✅ Test covers:
  - Changing threshold from $10 to $11
  - Changing threshold to $3
  - Setting threshold to 0 (no limit)
  - Verifying UI shows updated values
  - Checking Monitoring tab for SENT/BLOCKED messages

### Phase 1: Test Price Injection (Completed)
- ✅ Added test-only endpoint: `/api/test/inject-price`
- ✅ Endpoint gated behind `ENABLE_TEST_PRICE_INJECTION=1` (local dev only)
- ✅ Supports simulating:
  - delta $ = 10.5 -> should pass $10 but fail $11
  - delta $ = 11.2 -> should pass $11
  - delta $ = 2.9 -> should be blocked by $3 threshold
  - delta $ = 3.1 -> should pass $3 threshold

## Test Results

### Local Testing
**Status**: Ready for execution (code validated, syntax checks passed)

**Prerequisites**:
- Backend server running on port 8000
- Frontend server running on port 3000
- Database accessible
- `ENABLE_TEST_PRICE_INJECTION=1` set for price injection testing

**Commands to run**:
```bash
# Option 1: Start local stack (if using docker-compose)
cd /Users/carloscruz/automated-trading-platform
docker-compose up -d

# Option 2: Start manually (check dev_local.sh or start_local.sh)
# Then run Playwright test:
cd frontend
ENABLE_TEST_PRICE_INJECTION=1 npx playwright test tests/e2e/price-threshold-e2e.spec.ts
```

**Code Validation**:
- ✅ TypeScript syntax: No errors
- ✅ Python syntax: No errors in modified files
- ✅ Playwright test file: Valid and listed in test suite

**Expected Results**:
- [ ] Threshold changes are saved correctly
- [ ] UI reflects updated threshold values
- [ ] Alerts fire when price delta crosses threshold
- [ ] Alerts are blocked when price delta is below threshold
- [ ] Monitoring tab shows SENT vs BLOCKED correctly
- [ ] Orders are created when strategy requires (if applicable)

### AWS Testing
**Status**: Pending deployment

**Steps**:
1. Deploy changes to AWS
2. Open dashboard
3. Repeat browser steps for at least one active coin
4. Verify alerts/orders behave same as local
5. Capture logs

## Issues Found

### Before Fix
_To be filled after testing_

### Root Cause
_To be filled after diagnosis_

## Fix Summary

### Files Changed
1. `backend/app/services/signal_monitor.py`
   - Added `evaluation_id` generation at start of `_check_signal_for_coin_sync` (line ~742)
   - Added structured logging for config load (line ~829-840)
   - Added structured logging for signal evaluation decision (lines ~1210-1225)
   - Added structured logging for Telegram send attempts (lines ~1692-1705)
   - Key logging format: `[EVAL_{evaluation_id}] symbol side event | key=value | ...`

2. `backend/app/api/routes_test.py`
   - Added `/api/test/inject-price` endpoint for test price injection (lines ~1068-1168)
   - Endpoint gated by `ENABLE_TEST_PRICE_INJECTION=1` environment variable
   - Updates MarketPrice with simulated price delta to test threshold crossing

3. `backend/app/api/routes_dashboard.py`
   - Added structured logging for UI toggle events (lines ~1943-1952)
   - Logs format: `[UI_TOGGLE] symbol side | previous_state=X | new_state=Y`

4. `frontend/tests/e2e/price-threshold-e2e.spec.ts`
   - New Playwright test for price threshold E2E verification
   - Key features: threshold changes ($10->$11, $3, 0), price injection, Monitoring tab verification
   - Test validates UI updates, threshold persistence, and Monitoring tab SENT/BLOCKED display

### Key Changes
- Structured logging with `evaluation_id` for traceability
- Test-only price injection mechanism (gated by env var)
- Comprehensive Playwright test covering all threshold scenarios

## Verification

### Local Verification
_To be filled after test execution_

### AWS Verification
_To be filled after deployment_

## Log Snippets

### Example Evaluation Log
```
[EVAL_abc12345] BTC_USDT evaluation started | strategy=Swing/Conservative | min_price_change_pct=10.0% | ...
[EVAL_abc12345] BTC_USDT BUY signal evaluation | decision=ACCEPT | current_price=$50000.00 | price_change_usd=$10.50 | ...
[EVAL_abc12345] BTC_USDT BUY Telegram send SUCCESS | message_id=12345 | price=$50000.00 | ...
```

### Example Blocked Log
```
[EVAL_abc12345] BTC_USDT BUY signal evaluation | decision=BLOCK | current_price=$50000.00 | price_change_usd=$2.90 | threshold=3.0% | reason=THROTTLED_PRICE_GATE
```

## Next Steps

### To Run Tests Locally:

**Prerequisites:**
1. Docker Desktop must be running
2. Backend and frontend servers must be accessible

**Steps:**
```bash
# 1. Start local stack
cd /Users/carloscruz/automated-trading-platform
./dev_local.sh
# OR
docker compose --profile local up -d

# 2. Wait for services to be healthy (check ports 3000 and 8000)
curl http://localhost:3000  # Should return HTML
curl http://localhost:8000/health  # Should return JSON

# 3. Run Playwright test
cd frontend
ENABLE_TEST_PRICE_INJECTION=1 npx playwright test tests/e2e/price-threshold-e2e.spec.ts

# 4. Review test output and fix any issues
# 5. Re-run until all scenarios pass
```

### After Local Testing:
1. Fix any issues found
2. Re-run until all scenarios pass
3. Deploy to AWS
4. Verify on AWS
5. Update this report with final results

