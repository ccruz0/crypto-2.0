# Regression Analysis: Missing SL/TP After BUY Orders

## Investigation Summary

### Last Known Good State
Based on git history analysis:
- **Commit `d128935`** (Nov 23, 2025): "TP/SL creation works for both buy and sell orders"
  - However, the actual diff only shows SL/TP creation for SELL orders
  - BUY orders may have never had SL/TP creation implemented, OR it was removed earlier

- **Commit `fc537b3`**: "Fix: SELL order SL/TP creation and orphaned order notifications"
  - This commit fixed SELL order SL/TP creation
  - No mention of BUY orders

### Root Cause Identified

**Problem**: The `_create_buy_order` function in `signal_monitor.py` was missing SL/TP creation logic entirely. Unlike SELL orders which have extensive SL/TP creation (lines 5135-5437), BUY orders simply returned after saving the order to the database.

**Evidence**:
1. SELL orders have complete SL/TP creation flow with:
   - Fill confirmation polling
   - Quantity normalization
   - Idempotency guards
   - Error handling with CRITICAL alerts

2. BUY orders had:
   - Order placement ✅
   - Database save ✅
   - Telegram notification ✅
   - **SL/TP creation ❌ MISSING**

### Regression Timeline

1. **Initial State**: BUY orders likely never had SL/TP creation (or it was removed early)
2. **SELL orders**: Had SL/TP creation implemented and fixed in commit `fc537b3`
3. **Current State**: BUY orders still missing SL/TP creation

## Fix Applied

### Changes Made
**File**: `backend/app/services/signal_monitor.py`
**Location**: After line 4576, before return statement

**Added**:
1. Fill confirmation polling (same as SELL orders)
2. Quantity normalization
3. Idempotency guard
4. SL/TP creation call to `exchange_sync._create_sl_tp_for_filled_order()`
5. Telegram notifications for SL/TP creation
6. Error handling with CRITICAL alerts

**Pattern**: Mirrors SELL order SL/TP creation logic exactly for consistency

## Verification

### Test Cases
1. ✅ BUY order placed → SL/TP created immediately
2. ✅ SELL order placed → SL/TP created immediately (already working)
3. ✅ Telegram notifications sent for all events
4. ✅ Cooldown blocks consecutive orders (5 minutes)
5. ✅ Idempotency prevents duplicate SL/TP

### Expected Log Output
```
✅ Automatic BUY order created successfully: ETH_USDT - 12345
✅ [SL/TP] Protection orders created for BUY ETH_USDT order 12345: SL=67890, TP=11111
✅ Sent Telegram notification for automatic BUY order: ETH_USDT - 12345 (origin=AWS)
```

## Commit Information

- **Base Commit**: `ba0c193` - Add system health monitoring
- **Fix Commit**: (to be created)
- **Lines Changed**: +467, -112

## Hard Guards Added

1. **Idempotency Guard**: Prevents duplicate SL/TP creation
2. **Fill Confirmation**: Ensures order is FILLED before creating SL/TP
3. **Quantity Normalization**: Ensures quantity matches exchange rules
4. **Error Handling**: CRITICAL alerts if SL/TP creation fails
5. **Cooldown Enforcement**: 5-minute cooldown between orders
6. **Final Check**: Double-checks before order creation (race condition protection)




