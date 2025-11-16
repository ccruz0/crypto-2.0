# Final Payload Analysis: ALGO_USDT Margin Order

## Steps Completed

✅ **Step 1**: Added HTTP logging for ENTRY margin orders
- Logging tags: `[ENTRY_ORDER][AUTO]` for bot orders, `[ENTRY_ORDER][TEST]` for test script
- Logs include full payload before request and full response after request
- Request ID included for matching request/response pairs

✅ **Step 2**: Captured failing payload from test script
- Test script created: `test_margin_order_algo.py`
- Both bot and test script produce identical payloads
- Both fail with error 306 (INSUFFICIENT_AVAILABLE_BALANCE)

✅ **Step 3**: Created test script with same parameters as bot
- Symbol: ALGO_USDT
- Side: BUY
- Type: MARKET
- Notional: $1000.00
- Leverage: 2x
- Same authenticated client as bot

## Current Failing Payload

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

## Key Findings

1. **Both bot and test script fail** with identical payload format and error 306
2. **Payload structure matches** Crypto.com API documentation:
   - Uses `private/create-order` endpoint ✓
   - `leverage` parameter present in `params` (string "2") ✓
   - `notional` for BUY orders (string "1000.00") ✓
   - All required fields present ✓

3. **User reports manual order works** with same parameters:
   - Same symbol (ALGO_USDT)
   - Same size ($1000)
   - Same leverage (2x)
   - This suggests the payload format might differ from what web interface sends

## Possible Solutions to Try

Since we cannot easily capture the manual order payload from the web interface, we need to try variations:

1. **Try `leverage` as number instead of string**:
   - Current: `"leverage": "2"` (string)
   - Try: `"leverage": 2` (number)

2. **Try `notional` as number instead of string**:
   - Current: `"notional": "1000.00"` (string)
   - Try: `"notional": 1000.0` (number)

3. **Remove `client_oid`** (optional field):
   - Current: includes `client_oid`
   - Try: remove it

4. **Add `time_in_force` parameter**:
   - For MARKET orders, might need `"time_in_force": "IOC"`

5. **Use `quantity` instead of `notional`**:
   - Calculate quantity from current price
   - Try: `"quantity": "1234.5678"` instead of `"notional": "1000.00"`

## Next Steps

1. User should capture the exact payload from web interface when placing manual order
2. Or, we can try the variations above one by one
3. Compare field-by-field differences between working manual payload and failing bot payload

## Recommendation

Since the error is 306 (INSUFFICIENT_AVAILABLE_BALANCE) and the user confirms the account has enough margin when placing orders manually, the most likely causes are:

1. **Different account/subaccount**: Web interface might use a different account context
2. **Different margin calculation**: Web might calculate available margin differently than API
3. **Payload format difference**: Web might send parameters in a slightly different format

**Best approach**: Capture the exact HTTP request from the browser when placing a successful manual order, then compare it field-by-field with the bot's payload.

