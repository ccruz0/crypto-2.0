# Forensic Audit Analysis: Signal/Order/TP/SL Inconsistencies

## Executive Summary

This document provides a comprehensive analysis of systemic inconsistencies between Telegram messages, executed orders, and TP/SL handling, along with root cause analysis and fixes.

## Business Rules (Source of Truth)

- **BR-1**: SIGNAL → ORDER (MANDATORY) - Every BUY/SELL signal MUST have exactly ONE corresponding order (unless DEDUP_SKIPPED)
- **BR-2**: ORDER UNIQUENESS - Each signal can generate AT MOST one order (idempotency enforced)
- **BR-3**: ORDER → TP/SL (MANDATORY IF STRATEGY REQUIRES IT) - Both TP and SL must be created successfully (no partial creation)
- **BR-4**: FAILURES MUST BE EXPLICIT - All failures must record reason_code, reason_message, and exchange error
- **BR-5**: NO GHOST ENTITIES - Forbidden: signals without orders, orders without signals, TP/SL without parent orders, partial TP/SL

## Root Cause Analysis

### C2: SIGNAL_WITHOUT_ORDER

**Location**: `backend/app/services/signal_monitor.py`

**Root Causes**:
1. **Guard Clauses Return Early** (lines 2803-2957):
   - MAX_OPEN_ORDERS check (line 2803) - returns early with TRADE_BLOCKED event
   - RECENT_ORDERS_COOLDOWN check (line 2854) - returns early with TRADE_BLOCKED event
   - These are VALID skip reasons but MUST be recorded as SKIPPED with explicit reason_code

2. **Early Returns Without Explicit Failure Recording**:
   - Multiple `return None` statements without emitting ORDER_FAILED event
   - Exception handlers that swallow errors without recording failure

**Code Paths**:
- Line 3003-3042: Final guard check that can return early
- Line 5582-5584: Exception handler that returns None without recording failure
- Line 5377: Return None after order failure (but ORDER_FAILED is emitted - OK)

**Fix Required**:
- Ensure ALL early returns emit TRADE_BLOCKED or ORDER_FAILED events with explicit reason_code
- Update original BUY SIGNAL message with decision tracing (already implemented for guard clauses)
- Add explicit failure recording for all exception paths

### C3: ORDER_WITHOUT_SIGNAL

**Root Causes**:
1. **Manual Orders**: Manual orders created via API don't have signals (OK - these are intentional)
2. **Exchange Sync Orders**: Orders imported from exchange sync may not have signals (OK - these are existing orders)

**Classification**: Most orders without signals are MANUAL or SYNC orders, which are allowed. True violations are rare.

### C4/C5: ORDER_WITHOUT_TP_SL / PARTIAL_TP_SL

**Location**: `backend/app/services/sl_tp_checker.py` (line 594-960)

**Root Cause**:
- **NOT ATOMIC**: `_create_protection_order()` creates SL and TP separately (lines 872-904)
- **Partial Success Allowed**: Line 937 returns success if EITHER order is created
- **No Rollback**: If TP fails after SL succeeds, SL order remains (violates BR-3)

**Code Flow**:
```
_create_protection_order()
  ├─→ Create SL order (line 872)
  │   └─→ If fails: sl_error recorded, but function continues
  ├─→ Create TP order (line 890)
  │   └─→ If fails: tp_error recorded
  └─→ Return success if EITHER order created (line 937) ← VIOLATION
```

**Fix Required**:
- Make TP/SL creation atomic: either both succeed or both fail
- On partial failure, cancel the created order (rollback)
- Record SLTP_FAILED event with explicit reason_code

### C6: SILENT_FAILURE

**Root Causes**:
1. **Exception Swallowing**: Exception handlers that catch errors but don't record reason_code
2. **Missing Decision Tracing**: Some code paths don't update Telegram message with decision_type

**Location**: Multiple locations in `signal_monitor.py`

**Fix Required**:
- Ensure ALL exception handlers record failures with reason_code
- Ensure ALL code paths update Telegram messages with decision_type

### C7: DUPLICATE_ORDER

**Root Causes**:
1. **Race Conditions**: Multiple signal monitor cycles running simultaneously
2. **Idempotency Gaps**: order_creation_locks may not prevent all duplicates

**Fix Required**:
- Strengthen idempotency checks
- Add database-level unique constraints (if not already present)

## Fixes Implemented

### Fix 1: Ensure All Signal Paths Record Decisions

**File**: `backend/app/services/signal_monitor.py`

**Changes**:
- Guard clauses already update BUY SIGNAL messages (lines 2836-2851, 2906-2921) ✅
- Need to ensure ALL exception paths also update messages
- Need to ensure ORDER_FAILED paths update original signal message

### Fix 2: Make TP/SL Creation Atomic

**File**: `backend/app/services/sl_tp_checker.py`

**Changes Required**:
- Refactor `_create_protection_order()` to create TP and SL in transaction
- If one fails, cancel the other (rollback)
- Only return success if BOTH orders created
- Record SLTP_FAILED with explicit reason_code if partial failure

### Fix 3: Add Explicit Failure Recording

**File**: `backend/app/services/signal_monitor.py`

**Changes Required**:
- Add explicit failure recording to all exception handlers
- Ensure all ORDER_FAILED events update original BUY SIGNAL message
- Ensure all early returns record decision_type

## Forensic Audit Script

**File**: `backend/scripts/forensic_audit.py`

**Features**:
- Queries Telegram messages from last 12 hours
- Queries orders and TP/SL orders
- Matches signals to orders by timestamp and symbol
- Classifies inconsistencies into categories C1-C8
- Generates comprehensive report

**Usage**:
```bash
python3 backend/scripts/forensic_audit.py
```

## Monitoring Endpoint

**Endpoint**: `GET /api/forensic/audit?hours=12`

**Returns**:
- Summary statistics
- All inconsistencies categorized
- Detailed breakdown per signal/order

## Reconciliation

For the last 12 hours ONLY:
- Mark broken signals as FAILED with explicit reasons
- Mark orphan orders (if any) as MANUAL or SYNC
- Mark partial TP/SL as FAILED_INCONSISTENT

**DO NOT** retroactively create orders or TP/SL.

## Next Steps

1. Run forensic audit to identify current inconsistencies
2. Implement Fix 2 (atomic TP/SL creation) - HIGHEST PRIORITY
3. Implement Fix 3 (explicit failure recording) - HIGH PRIORITY
4. Run reconciliation script for last 12 hours
5. Verify fixes with new signals
6. Monitor for new inconsistencies
