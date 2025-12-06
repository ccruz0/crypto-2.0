# BTC Throttle Stress Test Report

**Date:** 2025-12-04 10:30:00 UTC

## Scenario

This test simulates the EXACT production code path to verify that BTC alerts
cannot bypass throttle. It uses the same evaluator, gatekeeper, and emit_alert
functions that AWS production uses.

### Test Sequence

1. **Tick 1:** First BUY conditions met → must be **ALLOWED**
2. **Tick 2:** 10 seconds later, 0% price change → must be **BLOCKED**
3. **Tick 3:** 40 seconds later, 0.02% price change → must be **BLOCKED**
4. **Tick 4:** 6 minutes later, 2% price change → must be **ALLOWED**

## Results

| Tick | Decision | Price | Elapsed | Price Δ% | Throttle | Gatekeeper | Alert Emitted | Reason |
|------|----------|-------|---------|----------|----------|------------|---------------|--------|
| 1 | ALERT | $50,000.00 | 0.0s | 0.00% | ✅ | ✅ | ✅ | Throttle check PASSED: No previous same-side signal recorded |
| 2 | NO_ALERT | $50,000.00 | 10.0s | 0.00% | ❌ | ❌ | ❌ | THROTTLED_MIN_TIME (elapsed 0.17m < 5.00m) AND price change 0.00% < 1.00% |
| 3 | NO_ALERT | $50,010.00 | 40.0s | 0.02% | ❌ | ❌ | ❌ | THROTTLED_MIN_CHANGE (price change 0.02% < 1.00%) |
| 4 | ALERT | $51,000.00 | 360.0s | 2.00% | ✅ | ✅ | ✅ | Throttle check PASSED: cooldown OK (6.00m >= 5.00m) AND price change 2.00% >= 1.00% |

## Expected vs Actual

- **Tick 1:** ✅ PASS - First alert should be allowed
- **Tick 2:** ✅ PASS - Second alert within 10s with 0% change should be blocked
- **Tick 3:** ✅ PASS - Third alert with insufficient time/price should be blocked
- **Tick 4:** ✅ PASS - Fourth alert with sufficient time and price should be allowed

## Final Verdict

**✅ PASS**

The throttle system correctly enforced throttle rules.










