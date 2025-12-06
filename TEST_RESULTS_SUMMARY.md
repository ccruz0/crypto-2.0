# Test Results Summary: ALGO_USDT Margin Order Payload Variations

## Test Execution
- **Date**: 2025-11-15
- **Symbol**: ALGO_USDT
- **Side**: BUY
- **Type**: MARKET
- **Notional**: $1000.00
- **Leverage**: 2x

## Variations Tested

All variations were tested and **ALL FAILED with error 306** (INSUFFICIENT_AVAILABLE_BALANCE).

### Key Finding: Payload Normalization
**Important Discovery**: Regardless of how we pass the parameters (string, int, or float), the code **normalizes them all to strings** before sending:

```json
{
  "params": {
    "instrument_name": "ALGO_USDT",
    "side": "BUY",
    "type": "MARKET",
    "client_oid": "...",
    "notional": "1000.00",  // Always string
    "leverage": "2"          // Always string
  }
}
```

This means **the payload format is NOT the problem**. All variations produce the same final payload format.

## Test Results

| Variation | notional Format | leverage Format | Final Payload | Result |
|-----------|----------------|-----------------|---------------|--------|
| 1. Baseline | string "1000.00" | string "2" | "1000.00", "2" | ❌ Error 306 |
| 2. leverage as float | string "1000.00" | float 2.0 → "2" | "1000.00", "2" | ❌ Error 306 |
| 3. leverage as int | string "1000.00" | int 2 → "2" | "1000.00", "2" | ❌ Error 306 |
| 4. notional as float | float 1000.0 → "1000.00" | string "2" | "1000.00", "2" | ❌ Error 306 |
| 5. notional as int | int 1000 → "1000.00" | string "2" | "1000.00", "2" | ❌ Error 306 |
| 6. both as float | float 1000.0 → "1000.00" | float 2.0 → "2" | "1000.00", "2" | ❌ Error 306 |
| 7. both as int | int 1000 → "1000.00" | int 2 → "2" | "1000.00", "2" | ❌ Error 306 |

## Conclusion

**The payload format is correct.** All variations produce identical payloads, and all fail with the same error 306.

## Possible Causes

Since the payload format is correct, the error 306 suggests:

1. **Account Balance Issue**:
   - The API might calculate available margin differently than the web interface
   - There might be existing positions consuming margin that the web doesn't show
   - The account might have margin restrictions on the API that don't apply to web

2. **API vs Web Differences**:
   - Web interface might use a different endpoint or API version
   - Web might have additional validation or margin calculation
   - Web might use a different account context (subaccount, etc.)

3. **ALGO_USDT Specific Restrictions**:
   - ALGO_USDT might have specific margin requirements not shown in general API docs
   - There might be minimum/maximum leverage restrictions for this pair
   - The pair might require special permissions or settings

## Recommendation

Since all payload format variations fail with the same error, we need to:

1. **Capture the exact payload from a successful manual order** from the web interface
2. **Compare field-by-field** with our bot payload
3. **Check for additional fields** that might be required (time_in_force, exec_inst, etc.)
4. **Verify account settings** - ensure API has same permissions as web interface
5. **Check margin calculations** - verify how API calculates available margin vs web

## Next Steps

1. User should capture the HTTP request payload from browser DevTools when placing a successful manual order
2. Compare that payload field-by-field with our bot payload
3. Identify any missing or different fields
4. Update the bot to match the working payload exactly

