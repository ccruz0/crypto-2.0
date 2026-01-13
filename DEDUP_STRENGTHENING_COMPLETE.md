# Dedup Strengthening - Complete

## Summary

Fixed idempotency key computation to ensure `signal_id`-based keys are idempotent forever (no timestamp bucket).

## Changes Made

### 1. `compute_idempotency_key()` Function Fix

**File**: `backend/app/services/signal_order_orchestrator.py`

**Change**:
- **Before**: `key = f"{env}:{symbol}:{side}:{signal_id}:{timestamp_str}"` (included timestamp bucket)
- **After**: `key = f"signal:{signal_id}:side:{side}"` (no timestamp, idempotent forever)

**Rationale**:
- A given `signal_id` must be idempotent forever (or at least for a long retention window)
- Timestamp buckets only used for fallback (when `signal_id` is missing)

### 2. Regression Test Added

**File**: `backend/tests/test_signal_orchestrator_dedup.py`

Added test `test_idempotency_across_time_window()` that:
- Creates an order_intent with a signal_id
- Waits >60 seconds (crosses timestamp boundary)
- Calls orchestrator again with same signal_id
- Verifies DEDUP_SKIPPED is returned
- Verifies only 1 order_intent exists

## Production Verification

### Test Execution

**Signal ID**: 777666  
**Symbol**: DEDUP_PROD  
**Side**: BUY

**Results**:
```
Idempotency key: signal:777666:side:BUY
First call: status=PENDING, order_intent_id=10
Waiting 65 seconds...
Second call: status=DEDUP_SKIPPED, order_intent_id=None
Total order_intents for signal_id=777666: 1
✅ SUCCESS: Dedup works across time window!
```

### SQL Verification

Query: `SELECT id, signal_id, symbol, side, status, LEFT(idempotency_key, 50) as key_preview FROM order_intents WHERE signal_id = 777666 ORDER BY id;`

**Expected**: Only 1 order_intent row (second call was dedup skipped)

## Deliverables

### ✅ Diff of `compute_idempotency_key`
```diff
-if signal_id:
-    key = f"{env}:{symbol}:{side}:{signal_id}:{timestamp_str}"
+if signal_id:
+    key = f"signal:{signal_id}:side:{side}"
```

### ✅ New Test
- File: `backend/tests/test_signal_orchestrator_dedup.py`
- Test: `test_idempotency_across_time_window()`
- Validates dedup works across time boundaries

### ✅ Production Proof
- Idempotency key format: `signal:777666:side:BUY` (no timestamp)
- First call: Created order_intent ID=10
- Second call (after 65s): DEDUP_SKIPPED, no new order_intent
- SQL: Only 1 order_intent exists for signal_id=777666

## Commit

**Commit**: `573e379` - "Strengthen dedup: signal_id idempotent forever (no timestamp bucket)"

**Files Changed**:
- `backend/app/services/signal_order_orchestrator.py`
- `backend/tests/test_signal_orchestrator_dedup.py` (new)

## Status

✅ **COMPLETE**: Dedup strengthened, tested, deployed, and verified in production.
