# Crypto.com Exchange API - Order History Access Issue

## Issue Summary
Unable to retrieve order history via the Crypto.com Exchange API v1. The `private/get-order-history` endpoint returns authentication errors (401), while other endpoints like `private/get-open-orders` work correctly.

## Technical Details

### API Endpoint
- **Endpoint**: `private/get-order-history`
- **Base URL**: `https://api.crypto.com/exchange/v1`
- **Authentication Method**: JSON-RPC 2.0 with HMAC-SHA256 signature

### Authentication Configuration
- **Signature Method**: HMAC-SHA256
- **Payload Format**: `method + id + api_key + nonce + json.dumps(params, separators=(',', ':'))`
- **Headers**: `Content-Type: application/json`
- **API Version**: v1 (production)

### Current Behavior

#### ✅ Working Endpoints
1. **`private/get-open-orders`** - Returns 200 OK with data
   ```json
   {
     "ok": true,
     "exchange": "CRYPTO_COM",
     "orders": [...],
     "count": 13
   }
   ```

2. **`private/user-balance`** - Returns 200 OK with account data

#### ❌ Non-Working Endpoint
1. **`private/get-order-history`** - Returns 401 Authentication Error
   ```json
   {
     "status": 401,
     "body": "{\"code\":40101,\"message\":\"Authentication failure\"}",
     "rid": 1761441640454
   }
   ```

### Request Details
```http
POST https://api.crypto.com/exchange/v1/private/get-order-history
Content-Type: application/json

{
  "id": 1761441640454,
  "method": "private/get-order-history",
  "api_key": "[REDACTED]",
  "sig": "[HMAC-SHA256 signature]",
  "nonce": 1761441640454,
  "params": {"page_size": 50}
}
```

### Response
```json
{
  "code": 40101,
  "message": "Authentication failure",
  "id": 1761441640454
}
```

## Environment
- **Exchange**: Crypto.com Exchange (not Mobile App API)
- **API Version**: v1 (production)
- **Server Location**: AWS Singapore (13.215.235.23)
- **Platform**: Automated trading platform with FastAPI backend

## Questions for Support

1. **Is `private/get-order-history` a valid endpoint?**
   - The endpoint is documented but returns 401 errors
   - Are there additional permissions required beyond read access?

2. **Are there alternative endpoints for order history?**
   - Maybe `private/get-trades` or a different method?
   - Or should we use a different API path?

3. **What permissions are required?**
   - Current API key has:
     - ✅ Read balance
     - ✅ Read open orders
     - ✅ Place orders
     - ❌ Order history access?
   
4. **IP whitelisting**
   - Is our server IP whitelisted? (13.215.235.23)
   - Could this be causing the authentication failure?

5. **API key type**
   - Are there different API key types (read-only, trading, etc.)?
   - Does order history require a specific key type?

## Attempted Solutions

1. ✅ Verified authentication method matches Crypto.com documentation
2. ✅ Confirmed signature generation is correct (HMAC-SHA256)
3. ✅ Tested with compact JSON parameters `json.dumps(params, separators=(',', ':'))`
4. ✅ Added `Content-Type: application/json` header
5. ✅ Verified nonce/timestamp format (milliseconds since epoch)
6. ✅ Tested with different `page_size` parameters
7. ✅ Confirmed IP whitelisting includes server IP

## Expected Behavior
The `private/get-order-history` endpoint should return:
```json
{
  "id": 123,
  "method": "private/get-order-history",
  "code": 0,
  "result": {
    "data": [
      {
        "order_id": "...",
        "instrument_name": "BTC_USDT",
        "side": "BUY",
        "order_type": "LIMIT",
        "status": "FILLED",
        "quantity": "0.1",
        "price": "50000.00",
        "create_time": 1234567890000,
        ...
      }
    ]
  }
}
```

## Additional Information

### Working Request Example (Open Orders)
```bash
curl -X POST https://api.crypto.com/exchange/v1/private/get-open-orders \
  -H "Content-Type: application/json" \
  -d '{
    "id": 1761441640454,
    "method": "private/get-open-orders",
    "api_key": "[REDACTED]",
    "sig": "[SIGNATURE]",
    "nonce": 1761441640454,
    "params": {}
  }'
```

Response: 200 OK with data ✅

### Non-Working Request Example (Order History)
```bash
curl -X POST https://api.crypto.com/exchange/v1/private/get-order-history \
  -H "Content-Type: application/json" \
  -d '{
    "id": 1761441640454,
    "method": "private/get-order-history",
    "api_key": "[REDACTED]",
    "sig": "[SIGNATURE]",
    "nonce": 1761441640454,
    "params": {"page_size": 50}
  }'
```

Response: 401 Authentication failure ❌

## Support Request
Please advise:
1. Why `private/get-order-history` returns 401 while other endpoints work
2. What permissions or API key configuration is needed
3. If there's an alternative endpoint for retrieving order history
4. If IP whitelisting or other restrictions apply to this endpoint

Thank you!
