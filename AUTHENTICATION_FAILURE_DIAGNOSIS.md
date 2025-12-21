# 🔍 Authentication Failure Diagnosis: Automatic Sell Order

## Error Summary

**Error**: `Authentication failed: Authentication failure`  
**Symbol**: BTC_USD  
**Side**: SELL  
**Amount**: $10.00  
**Quantity**: 0.00011119

This error occurs when the Crypto.com API returns a **401 status code** with error code **40101**, indicating that the API request cannot be authenticated.

## Root Causes

The authentication failure can be caused by one or more of the following:

### 1. 🔴 IP Whitelist Issue (Most Common)

**Problem**: Your server's IP address is not whitelisted in Crypto.com Exchange.

**Solution**:
1. Find your server's outbound IP:
   ```bash
   # Check backend logs for the outbound IP
   docker compose logs backend | grep "CRYPTO_COM_OUTBOUND_IP"
   
   # Or check directly
   curl https://api.ipify.org
   ```

2. Whitelist the IP in Crypto.com:
   - Go to https://exchange.crypto.com/
   - Settings → API Keys
   - Edit your API Key
   - Add the IP address to the whitelist
   - Save and wait 30-60 seconds for propagation

### 2. 🔴 Invalid API Credentials

**Problem**: The API key or secret is incorrect, expired, or revoked.

**Solution**:
1. Verify credentials are set:
   ```bash
   docker compose exec backend python -c "
   import os
   api_key = os.getenv('EXCHANGE_CUSTOM_API_KEY', '')
   api_secret = os.getenv('EXCHANGE_CUSTOM_API_SECRET', '')
   print(f'API Key: {api_key[:10]}...' if api_key else 'NOT SET')
   print(f'API Secret: {api_secret[:10]}...' if api_secret else 'NOT SET')
   "
   ```

2. If credentials are wrong, update them:
   - Create a new API Key in Crypto.com Exchange
   - Update `.env.local` or your environment variables:
     ```bash
     EXCHANGE_CUSTOM_API_KEY=your_new_api_key
     EXCHANGE_CUSTOM_API_SECRET=your_new_api_secret
     ```
   - Restart the backend:
     ```bash
     docker compose restart backend
     ```

### 3. 🔴 Missing API Permissions

**Problem**: The API Key doesn't have "Trade" permission.

**Solution**:
1. Go to https://exchange.crypto.com/
2. Settings → API Keys
3. Edit your API Key
4. Ensure **"Trade"** permission is enabled (required for placing orders)
5. Save the changes

### 4. 🔴 Clock Synchronization Issue

**Problem**: Server time is out of sync, causing invalid nonce/timestamp.

**Solution**:
1. Check server time:
   ```bash
   docker compose exec backend date
   ```

2. If time is wrong, sync it:
   ```bash
   # On the host system
   sudo ntpdate -s time.nist.gov
   # Or use systemd-timesyncd
   sudo timedatectl set-ntp true
   ```

## Diagnostic Steps

### Step 1: Check Current Configuration

```bash
# Check if credentials are configured
docker compose exec backend python scripts/check_crypto_config.py

# Test API connection
docker compose exec backend python scripts/test_crypto_connection.py

# Check outbound IP (should be logged in backend logs)
docker compose logs backend | grep "CRYPTO_COM_OUTBOUND_IP"
```

### Step 2: Verify API Key Status

1. Log into Crypto.com Exchange
2. Go to Settings → API Keys
3. Check:
   - ✅ API Key is **Active** (not disabled or suspended)
   - ✅ **Trade** permission is enabled
   - ✅ Your server IP is in the whitelist
   - ✅ IP whitelist is enabled (not "Allow all IPs")

### Step 3: Test Authentication

```bash
# Test getting account balance (requires Read permission)
curl -X GET http://localhost:8000/api/dashboard/state | jq '.balances'

# If this works but orders fail, it's likely a Trade permission issue
```

### Step 4: Check Backend Logs

```bash
# Look for authentication errors
docker compose logs backend | grep -i "authentication\|401\|40101"

# Look for outbound IP
docker compose logs backend | grep "CRYPTO_COM_OUTBOUND_IP"

# Look for detailed signing process
docker compose logs backend | grep "CRYPTO_AUTH_DIAG"
```

## Quick Fix Checklist

- [ ] Verify API credentials are correct in environment variables
- [ ] Check that API Key has **Trade** permission enabled
- [ ] Whitelist your server's outbound IP in Crypto.com
- [ ] Verify server time is synchronized
- [ ] Restart backend after making changes: `docker compose restart backend`
- [ ] Wait 30-60 seconds after whitelisting IP for propagation

## Common Error Codes

- **40101**: Authentication failure (invalid credentials or IP not whitelisted)
- **40103**: IP illegal (IP not in whitelist)
- **403**: Forbidden (API Key doesn't have required permissions)

## After Fixing

Once you've resolved the issue, verify it works:

```bash
# Test connection
docker compose exec backend python scripts/test_crypto_connection.py

# Check if balances load
curl http://localhost:8000/api/dashboard/state | jq '.balances'

# Monitor logs for successful orders
docker compose logs -f backend | grep "Successfully placed"
```

## Still Having Issues?

If the problem persists after checking all the above:

1. **Regenerate API Key completely**:
   - Delete the old API Key in Crypto.com
   - Create a new one with Read + Trade permissions
   - Add your IP to whitelist immediately
   - Update environment variables
   - Restart backend

2. **Check if using proxy**:
   ```bash
   # If USE_CRYPTO_PROXY=true, ensure proxy is running
   docker compose ps | grep proxy
   ```

3. **Review detailed logs**:
   ```bash
   docker compose logs backend | grep -A 10 -B 10 "place_market_order\|Authentication failed"
   ```



















