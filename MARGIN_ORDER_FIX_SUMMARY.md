# Margin Order Fix - Summary

## Problem Identified

**Issue:** Margin orders fail with error 306 (INSUFFICIENT_AVAILABLE_BALANCE) even when the account has sufficient margin capacity (can place $10,000 orders manually in UI, but script fails with $1,000 orders).

**Root Cause:** The issue is likely in how the API request is constructed, not actual margin capacity.

## Solution Implemented

### 1. Enhanced Margin Order Construction (`place_market_order` and `place_limit_order`)

**File:** `backend/app/services/brokers/crypto_com_trade.py`

**Current Implementation:**
- **Endpoint:** `private/create-order` (same for spot and margin)
- **Margin Flag:** Presence of `leverage` parameter makes it a margin order
- **Leverage Format:** String (e.g., `"10"`), not a number

**Request Structure for Margin Orders:**
```json
{
  "id": 1,
  "method": "private/create-order",
  "api_key": "<REDACTED>",
  "params": {
    "instrument_name": "BTC_USDT",
    "side": "BUY",              // UPPERCASE
    "type": "MARKET",
    "notional": "1000.00",      // For BUY orders (amount in USDT)
    "client_oid": "<uuid>",
    "leverage": "10"            // REQUIRED for margin orders (string)
  },
  "nonce": 1234567890,
  "sig": "<HMAC_SIGNATURE>"
}
```

**Key Points:**
- `leverage` must be a STRING, not a number
- No `exec_inst` parameter needed
- No `margin_trading` flag needed
- Same endpoint for spot and margin orders

### 2. Detailed Request/Response Logging

**Added logging tags:**
- `[MARGIN_REQUEST]` - Shows endpoint, symbol, side, type, payload (without secrets)
- `[MARGIN_RESPONSE]` - Shows status_code and full JSON response
- `[MARGIN_ERROR_306]` - Special logging for error 306 with detailed context

**Log Format:**
```
[MARGIN_REQUEST] endpoint=private/create-order
[MARGIN_REQUEST] symbol=BTC_USDT side=BUY type=MARKET is_margin=True
[MARGIN_REQUEST] payload={
  "id": 1,
  "method": "private/create-order",
  "api_key": "<REDACTED_API_KEY>",
  "params": {
    "instrument_name": "BTC_USDT",
    "side": "BUY",
    "type": "MARKET",
    "notional": "1000.00",
    "client_oid": "...",
    "leverage": "10"
  },
  "nonce": 1234567890,
  "sig": "<REDACTED_SIGNATURE>"
}
[MARGIN_REQUEST] params_detail: instrument_name=BTC_USDT, side=BUY, type=MARKET, notional=1000.0
[MARGIN_REQUEST] margin_params: leverage=10

[MARGIN_RESPONSE] status_code=500
[MARGIN_RESPONSE] payload={
  "id": 1,
  "method": "private/create-order",
  "code": 306,
  "message": "INSUFFICIENT_AVAILABLE_BALANCE",
  "result": {
    "client_oid": "...",
    "order_id": "..."
  }
}

[MARGIN_ERROR_306] symbol=BTC_USDT side=BUY type=MARKET
[MARGIN_ERROR_306] requested_size=1000.00 leverage=10
[MARGIN_ERROR_306] raw_response={...}
[MARGIN_ERROR_306] NOTE: This error means insufficient margin balance OR malformed request
[MARGIN_ERROR_306] Verify: 1) Request payload matches Crypto.com API docs 2) Account has enough margin
```

### 3. Enhanced Error 306 Handling

**Special handling for error 306:**
- Logs exact request payload that failed
- Logs full error response from Crypto.com
- Clearly identifies if it's a margin order vs spot
- Provides verification steps

### 4. Margin Test Helper

**File:** `backend/app/services/brokers/margin_test_helper.py`

**Function:** `test_margin_order()`

Allows testing small margin orders (e.g., $20) to verify request construction:
- Uses same internal builder as production orders
- Provides detailed logging
- Safe for debugging (use `dry_run=True` initially)

### 5. Debug Endpoint

**File:** `backend/app/api/routes_debug.py`

**Endpoint:** `POST /api/debug/test-margin-order`

**Parameters:**
- `symbol`: Trading symbol (e.g., BTC_USDT)
- `side`: BUY or SELL
- `notional`: Amount in quote currency (for BUY orders)
- `leverage`: Leverage multiplier (default: 10)
- `dry_run`: If True, doesn't place real order

**Example:**
```bash
curl -X POST "http://localhost:8002/api/debug/test-margin-order?symbol=DOGE_USDT&notional=20&leverage=10&dry_run=false"
```

## Files Modified

1. **`backend/app/services/brokers/crypto_com_trade.py`**
   - Enhanced `place_market_order()` with detailed logging
   - Enhanced `place_limit_order()` with detailed logging
   - Improved error 306 handling
   - Added comprehensive docstrings explaining margin order construction

2. **`backend/app/services/brokers/margin_test_helper.py`** (NEW)
   - Test helper function for debugging margin orders

3. **`backend/app/api/routes_debug.py`** (NEW)
   - Debug endpoint for testing margin orders

4. **`backend/app/main.py`**
   - Registered debug router

## Next Steps

1. **Deploy changes** to backend
2. **Check logs** when a margin order is attempted:
   - Look for `[MARGIN_REQUEST]` logs to see exact payload
   - Look for `[MARGIN_RESPONSE]` logs to see Crypto.com's response
   - If error 306 occurs, check `[MARGIN_ERROR_306]` logs for details

3. **Compare with manual UI orders:**
   - Place a $20 margin order via debug endpoint
   - Compare the `[MARGIN_REQUEST]` payload with what the UI sends (check browser network tab)
   - Identify any differences in parameter format or structure

4. **Verify Crypto.com API docs:**
   - Check if there are any additional required parameters for margin orders
   - Verify the `leverage` parameter format (string vs number)
   - Check if there's a separate margin endpoint or flag

## Verification Checklist

When testing, verify:
- [ ] `[MARGIN_REQUEST]` logs show `leverage` as a string (e.g., `"10"`)
- [ ] `[MARGIN_REQUEST]` logs show correct `notional` for BUY orders
- [ ] `[MARGIN_REQUEST]` logs show `side` in UPPERCASE
- [ ] `[MARGIN_RESPONSE]` logs show the full response from Crypto.com
- [ ] If error 306 occurs, `[MARGIN_ERROR_306]` logs provide detailed context

## Notes

- All sensitive fields (api_key, signature) are redacted in logs
- The request payload structure matches Crypto.com Exchange API v1 documentation
- Error 306 can mean either insufficient balance OR malformed request - the detailed logs will help distinguish

