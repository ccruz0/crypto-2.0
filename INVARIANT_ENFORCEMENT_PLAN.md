# Invariant Enforcement Plan

## Problem

Currently, BUY/SELL signals are marked as "sent" (line 2517: `send_buy_signal()`, line 2586: `record_signal_event()`) BEFORE order eligibility checks (lines 2633-3024). This violates the invariant:

**"If a signal is marked as 'sent', an order MUST be attempted immediately (only dedup can block)."**

## Solution

Refactor the flow so that:
1. ALL eligibility checks happen BEFORE marking as "sent"
2. If all checks pass → mark as "sent" → immediately attempt order
3. Only dedup check happens after "sent" but before order

## Changes Required

### Step 1: Move Order Eligibility Checks Before Alert Sending

Move the order eligibility checks (currently at lines 2633-3024) to BEFORE the alert sending (currently at line 2517).

The checks to move:
- MAX_OPEN_ORDERS check (lines 2822-2873)
- RECENT_ORDERS_COOLDOWN check (lines 2874-2978)
- LIVE_TRADING check (needs to be added)
- trade_enabled check (already done, but needs to be consolidated)
- trade_amount_usd validation (already done, but needs to be consolidated)

### Step 2: Create Orchestrator Function

Create `_orchestrate_buy_signal_with_order()` that:
1. Evaluates ALL eligibility checks first
2. If all pass → mark as "sent" → immediately attempt order
3. If LIVE_TRADING=false → send alert but mark as ORDER_BLOCKED_LIVE_TRADING

### Step 3: Update Alert Sending Logic

Modify the alert sending logic (line 2517) to:
- Only mark as "sent" if all eligibility checks pass
- Immediately call order creation after marking as "sent"
- Handle LIVE_TRADING=false explicitly

### Step 4: Update Order Creation Logic

Modify the order creation logic (line 3024) to:
- Only perform dedup check (already done at lines 3165-3200)
- Remove other eligibility checks (they're now done before "sent")

## Implementation Order

1. First, create the orchestrator function
2. Then, refactor the existing code to use it
3. Finally, test and verify

## Testing

After implementation, verify:
1. Signal marked as "sent" → order is attempted immediately
2. Signal blocked by eligibility → NOT marked as "sent"
3. LIVE_TRADING=false → alert sent but order blocked with clear lifecycle event
4. Dedup check works correctly after "sent"
