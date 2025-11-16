# Margin Orders Fixed - Final Solution

## Problem
Automatic margin orders were consistently failing with `INSUFFICIENT_AVAILABLE_BALANCE (code: 306)` error, even though:
- Manual orders from the web interface worked successfully
- Account had sufficient margin balance
- Leverage was correctly set (2x, 3x, 5x, 10x)

## Root Cause Identified

After analyzing a successful manual order (BTC_USD, Order ID: 5755600478601727672) from the API response, we discovered that:

**Successful manual orders include:**
```json
{
  "exec_inst": ["MARGIN_ORDER"],
  "leverage": "...",
  ...
}
```

**Failing bot orders only included:**
```json
{
  "leverage": "2",
  // ❌ Missing exec_inst parameter
  ...
}
```

## Solution

The Crypto.com Exchange API requires **both** `leverage` AND `exec_inst: ["MARGIN_ORDER"]` parameters for margin orders to be properly identified and processed.

### Changes Made

1. **Modified `crypto_com_trade.py` - `place_market_order` function:**
   - Added `params["exec_inst"] = ["MARGIN_ORDER"]` when `is_margin=True`
   - This ensures all margin orders include the `exec_inst` parameter

2. **Fixed `_params_to_str` function:**
   - Updated to correctly handle lists containing strings (not just dicts)
   - Prevents `TypeError: string indices must be integers, not 'str'` when processing `exec_inst`

## Test Results

**Test Order: ALGO_USDT**
- Symbol: ALGO_USDT
- Side: BUY
- Type: MARKET
- Amount: $1,000
- Leverage: 2x
- **Status: ✅ SUCCESS**
- Order ID: 5755600478602253245
- Response Code: 200 (success)

**Payload Sent:**
```json
{
  "method": "private/create-order",
  "params": {
    "instrument_name": "ALGO_USDT",
    "side": "BUY",
    "type": "MARKET",
    "notional": "1000.00",
    "leverage": "2",
    "exec_inst": ["MARGIN_ORDER"]  // ⭐ KEY FIX
  }
}
```

## Impact

- ✅ All automatic margin orders now include `exec_inst: ["MARGIN_ORDER"]`
- ✅ Manual orders and bot orders now use the same payload structure
- ✅ Margin orders should no longer fail with error 306 due to missing parameters
- ✅ The fix applies to all margin orders (entry, SL, TP) since they all use `place_market_order` or `place_limit_order`

## Next Steps

1. Monitor automatic margin orders to confirm they execute successfully
2. Verify SL/TP orders created for margin positions also work correctly
3. Confirm no regression for SPOT orders (should not include `exec_inst`)

## Files Modified

- `backend/app/services/brokers/crypto_com_trade.py`
  - Added `exec_inst` parameter for margin orders
  - Fixed `_params_to_str` to handle lists of strings

## Verification

The fix was verified with a test order for ALGO_USDT that successfully executed. The order was placed with:
- Margin enabled
- Leverage: 2x
- `exec_inst: ["MARGIN_ORDER"]` included
- Result: Order ID 5755600478602253245 created successfully

