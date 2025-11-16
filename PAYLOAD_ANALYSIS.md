# Payload Analysis: ALGO_USDT Margin Order Failure

## Status
- ✅ Step 1: HTTP logging for ENTRY orders added (`[ENTRY_ORDER][AUTO]` and `[ENTRY_ORDER][TEST]`)
- ✅ Step 2: Failing payload captured from test script
- ⚠️ Step 3: Test script also fails with same error 306
- ⏳ Step 4: Need to find working payload format

## Current Failing Payload

From `[ENTRY_ORDER][TEST]` logs:

```json
{
  "id": 1,
  "method": "private/create-order",
  "api_key": "z3HWF8m292zJKABkzfXWvQ",
  "params": {
    "instrument_name": "ALGO_USDT",
    "side": "BUY",
    "type": "MARKET",
    "client_oid": "26dcd32a-7672-4335-a600-5c6bfe02d859",
    "notional": "1000.00",
    "leverage": "2"
  },
  "nonce": 1763209078454,
  "sig": "509584151a1736452bbe8f1e40668ad37d3c7751519a66482a78827f6e3d424d"
}
```

## Error Response

```json
{
  "id": 1,
  "method": "private/create-order",
  "code": 306,
  "message": "INSUFFICIENT_AVAILABLE_BALANCE",
  "result": {
    "client_oid": "26dcd32a-7672-4335-a600-5c6bfe02d859",
    "order_id": "5755600478600559838"
  }
}
```

## Key Observations

1. **Both bot and test script fail** with the same payload format and error 306
2. **User reports manual order works** with same parameters (symbol, size, leverage)
3. **Payload structure appears correct** according to Crypto.com API documentation:
   - Uses `private/create-order` endpoint
   - Has `leverage` in params (makes it a margin order)
   - Uses `notional` for BUY orders
   - All required fields present

## Possible Issues to Investigate

1. **Field types**: Are we sending strings vs numbers correctly?
   - `leverage` is sent as string "2" ✓
   - `notional` is sent as string "1000.00" ✓

2. **Missing fields**: Does Crypto.com web interface send additional fields?
   - `time_in_force`? (usually not required for MARKET orders)
   - `exec_inst`? (we removed this based on previous analysis)
   - Any margin-specific flags?

3. **Parameter location**: Is `leverage` in the right place?
   - Currently in `params` object ✓
   - Should it be at root level? (probably not)

4. **Account state**: Is there a difference in account state?
   - Manual orders might be using a different account/subaccount
   - Web interface might have different margin checks

5. **API endpoint version**: Are we using the correct endpoint?
   - Currently using `/exchange/v1/private/create-order` ✓
   - Web might use a different version?

## Next Steps

1. Try different parameter combinations:
   - Remove `client_oid` (optional field)
   - Try `leverage` as number instead of string
   - Try sending `time_in_force` parameter
   - Try different endpoint if available

2. Compare with successful manual order:
   - Check Crypto.com web interface network logs
   - Capture exact payload sent by web interface
   - Compare field-by-field

3. Check API documentation:
   - Verify latest API requirements
   - Check for any margin-specific requirements
   - Look for known issues with ALGO_USDT margin orders

