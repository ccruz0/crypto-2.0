# 🔍 Debug Order Creation Authentication Issue

## Situation
- ✅ Read operations work (get_account_summary, get_open_orders)
- ✅ Trade permissions are enabled
- ✅ IP whitelist is configured
- ❌ Order creation fails with "Authentication failed: Authentication failure"

## Hypothesis
Since read operations work but order creation fails, the issue is likely in:
1. **Params formatting** - How params are serialized for signature vs request body
2. **Signature generation** - Difference in how signatures are generated for params vs empty params
3. **Request structure** - Something specific about the order creation request format

## Step 1: Enable Diagnostic Logging

On your AWS server, enable detailed authentication diagnostics:

```bash
# Add to .env.aws
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws

# Restart backend
docker compose restart backend
```

This will log:
- Exact signature generation process
- Params string used in signature
- Request payload (with redacted secrets)
- Response details

## Step 2: Run Comparison Test

```bash
cd ~/automated-trading-platform
python3 backend/scripts/test_order_creation_auth.py
```

This script will:
- Test read operation (should work)
- Test order creation (will show exact error)
- Compare signature generation between read and write
- Show connection method (proxy vs direct)

## Step 3: Check Backend Logs

After enabling diagnostics, trigger a test order and check logs:

```bash
# Watch logs in real-time
docker compose logs backend -f | grep -E "CRYPTO_AUTH_DIAG|AUTHENTICATION|SIGNING|ENTRY_ORDER"

# Or get recent logs
docker compose logs backend --tail 200 | grep -A 20 "AUTHENTICATION FAILED"
```

Look for:
- `[CRYPTO_AUTH_DIAG]` entries showing signature generation
- `[ENTRY_ORDER]` entries showing request/response
- Exact error code and message from API

## Step 4: Compare Working vs Failing Requests

The diagnostic logs will show:

### Working Read Request:
```
Method: private/user-balance
Params: {}
Params string for signature: "" (empty)
String to sign: private/user-balance1{api_key}{nonce}
```

### Failing Write Request:
```
Method: private/create-order
Params: {instrument_name, side, type, quantity, client_oid, ...}
Params string for signature: (alphabetically sorted, concatenated)
String to sign: private/create-order1{api_key}{params_str}{nonce}
```

**Key things to check:**
1. Are params sorted alphabetically in signature?
2. Are list values (like `exec_inst: ["MARGIN_ORDER"]`) formatted correctly?
3. Is the params string in signature matching the params dict in request body?

## Step 5: Check Specific Issues

### Issue: List Parameters in Signature

If your order has `exec_inst: ["MARGIN_ORDER"]`, check how it's formatted in the signature string.

The `_params_to_str` method should handle lists, but verify:
- Lists are iterated and values concatenated
- No separators between list items
- Dicts in lists are recursively processed

### Issue: Params Ordering

The signature uses alphabetically sorted params, but the request body also needs to match. Check:
- Are params in request body sorted alphabetically?
- Do they match the order used in signature generation?

### Issue: Proxy vs Direct

Check if there's a difference:
- Read operations might use proxy
- Order creation might use direct connection (or vice versa)

```bash
# Check connection method
docker compose exec backend env | grep USE_CRYPTO_PROXY
```

## Step 6: Test with Minimal Order

Try creating the simplest possible order to isolate the issue:

```python
# Minimal test order
result = trade_client.place_market_order(
    symbol="BTC_USDT",
    side="SELL",
    qty=0.0001,
    is_margin=False,  # No margin params
    dry_run=True
)
```

If this works but margin orders fail, the issue is with margin-specific params.

## Step 7: Check Actual API Response

The logs should show the exact API response. Look for:
- Error code (40101, 40103, etc.)
- Error message (may give hints)
- Response body structure

## Common Issues Found

### 1. List Formatting in Signature
**Problem:** `exec_inst: ["MARGIN_ORDER"]` not formatted correctly in signature string

**Solution:** Verify `_params_to_str` handles lists correctly

### 2. Params Not Sorted in Request Body
**Problem:** Request body params not sorted to match signature

**Solution:** Ensure `ordered_params = dict(sorted(params.items()))` is used

### 3. Type Mismatch
**Problem:** Numbers vs strings in params (e.g., `leverage: "10"` vs `leverage: 10`)

**Solution:** Ensure all params are correct types (leverage must be string)

## Next Steps After Diagnosis

Once you have the diagnostic logs:

1. **Share the logs** - The `[CRYPTO_AUTH_DIAG]` entries will show exactly what's being sent
2. **Compare signatures** - See if signature generation differs between read/write
3. **Check API response** - The exact error message may give clues
4. **Test variations** - Try different param combinations to isolate the issue

---

**The diagnostic logging will reveal the exact difference between working read operations and failing write operations.**

