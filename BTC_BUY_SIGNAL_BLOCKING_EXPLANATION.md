# BTC Buy Signal Blocking Explanation

## Problem
BTC buy signals are being blocked because the system uses **signal throttling** to prevent duplicate alerts. The system compares the current price against a stored "last signal price" and blocks new signals if the price hasn't changed enough.

## How Signal Throttling Works

### Price Reference Storage
When a BUY signal is successfully sent, the system stores:
- **Last Price**: The price at which the signal was sent (stored in `signal_throttle_states` table)
- **Last Time**: When the signal was sent
- **Strategy Key**: The strategy combination (e.g., "swing:conservative")

### Throttling Logic
When a new BUY signal is detected, the system:
1. Retrieves the last stored price from the database
2. Calculates the absolute price change percentage: `|current_price - last_price| / last_price * 100`
3. Compares against the minimum threshold (default: **1%**)
4. **Blocks the signal** if price change < 1% (or configured threshold)

### Why BTC Signals Are Blocked
If you haven't had signals for a while, it's likely because:
- The last signal was sent at a price very close to the current price
- The price hasn't moved enough (less than 1%) since the last signal
- The stored price reference is preventing new signals

## How to Check the Price Reference

### Option 1: Check Logs
Look for log messages like:
```
🚫 BLOQUEADO: BTC_USDT BUY - THROTTLED_MIN_CHANGE (absolute price change ↑ 0.45% < 1.00%)
```

This shows:
- The current price
- The last signal price
- The price change percentage
- Why it was blocked

### Option 2: Query Database Directly
The price reference is stored in the `signal_throttle_states` table:

```sql
SELECT 
    symbol,
    strategy_key,
    side,
    last_price,
    last_time,
    emit_reason
FROM signal_throttle_states
WHERE symbol = 'BTC_USDT' AND side = 'BUY';
```

### Option 3: Use the Diagnostic Script
Run the diagnostic script (requires database access):
```bash
python3 backend/scripts/check_signal_throttle.py BTC_USDT swing conservative
```

## How to Reset the Throttle State

### Option 1: Toggle Trade Status (Easiest)
In the dashboard:
1. Find BTC_USDT in the watchlist
2. Toggle the "Trade" column from YES → NO → YES
3. This automatically resets the throttle state and allows the next signal

### Option 2: Toggle Alert Status
1. Find BTC_USDT in the watchlist
2. Toggle the "ALERTS" button (BUY alert)
3. This resets the throttle state for BUY signals

### Option 3: Reset via API (if available)
The system has a `reset_throttle_state()` function that can be called programmatically.

### Option 4: Direct Database Update (Advanced)
If you have database access, you can manually reset:

```sql
-- Reset last_price and last_time for BTC_USDT BUY signals
UPDATE signal_throttle_states
SET 
    last_price = NULL,
    previous_price = NULL,
    last_time = '1970-01-01 00:00:00+00',
    force_next_signal = false
WHERE symbol = 'BTC_USDT' AND side = 'BUY';
```

## Understanding the Price Reference

The **price reference** is the `last_price` value stored in `signal_throttle_states` table. This is:
- **Set when**: A signal is successfully sent (not blocked)
- **Used for**: Comparing against current price to determine if enough change occurred
- **Updated**: Only when a new signal passes throttling and is sent

**Important**: The price reference is NOT updated when signals are blocked. This ensures the threshold is always calculated from the last successfully sent signal price.

## Example Scenario

Let's say:
- Last BUY signal was sent at: **$88,000**
- Current BTC price is: **$88,500**
- Price change: `|88500 - 88000| / 88000 * 100 = 0.57%`

Since 0.57% < 1.00% (minimum threshold), the signal is **blocked**.

To allow a new signal, either:
1. Wait for price to move 1%+ from $88,000 (to $88,880 or $87,120)
2. Reset the throttle state (clears the $88,000 reference)

## Configuration

The minimum price change threshold can be configured per symbol in the watchlist:
- Default: **1.0%** (`ALERT_MIN_PRICE_CHANGE_PCT`)
- Can be overridden per symbol via `min_price_change_pct` column in watchlist

## Summary

**What price reference is being used?**
- The `last_price` from `signal_throttle_states` table for BTC_USDT BUY signals
- This is the price at which the last BUY signal was successfully sent

**Why no signals?**
- Price hasn't changed enough (less than 1%) since the last signal
- The stored price reference is blocking new signals

**How to fix?**
- Toggle Trade or Alert status in the dashboard (easiest)
- Or wait for price to move 1%+ from the stored reference price












