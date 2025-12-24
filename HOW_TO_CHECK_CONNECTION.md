# 🔍 How to Check Crypto.com Exchange Connection

Based on the existing documentation, here are the ways to check your connection:

## 📋 Method 1: Test Connection Script (Recommended)

This is the main way to test the connection according to the documentation:

### For Local Development:
```bash
docker compose exec backend python scripts/test_crypto_connection.py
```

### For AWS Production:
```bash
docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py
```

**What it tests:**
- ✅ Public API connectivity (no auth needed)
- ✅ Private API authentication (get account summary)
- ✅ Open orders retrieval
- ✅ Order history retrieval

**Expected output:**
```
============================================================
Crypto.com Connection Test
============================================================
API Key: ✅ Configured
API Secret: ✅ Configured
Base URL: https://api.crypto.com/exchange/v1
Using Proxy: false
Live Trading: true

1. Testing public endpoint (no auth)...
   ✅ Public API works! BTC_USDT price: $43,250.00

2. Testing private endpoint (get_account_summary)...
   ✅ Private API works! Found 5 account(s)
   Sample account: USDT - Balance: 1000.0

3. Testing get open orders...
   ✅ Open orders API works! Found 0 open order(s)

4. Testing get order history...
   ✅ Order history API works! Found 10 order(s) in history
============================================================
```

## 📋 Method 2: Check Configuration Script

Verify your configuration is set up correctly:

### For Local:
```bash
docker compose exec backend python scripts/check_crypto_config.py
```

### For AWS:
```bash
docker compose --profile aws exec backend-aws python scripts/check_crypto_config.py
```

**What it checks:**
- ✅ USE_CRYPTO_PROXY setting
- ✅ LIVE_TRADING setting
- ✅ API Key configured
- ✅ API Secret configured
- ✅ Proxy settings (if using proxy)
- ✅ Base URL configuration

## 📋 Method 3: Full Diagnostic (New - Most Comprehensive)

For authentication issues, use the new diagnostic script:

### For Local:
```bash
docker compose exec backend python scripts/diagnose_auth_issue.py
```

### For AWS:
```bash
docker compose --profile aws exec backend-aws python scripts/diagnose_auth_issue.py
```

**What it checks:**
- ✅ Environment configuration
- ✅ API credentials (with validation)
- ✅ Public IP address
- ✅ Public API connectivity
- ✅ Private API authentication
- ✅ Specific error diagnosis with recommendations

## 📋 Method 4: Check via API Endpoint

Check if balances are being synced:

```bash
# Local
curl http://localhost:8002/api/dashboard/state | jq '.balances'

# AWS (replace with your AWS IP/domain)
curl http://your-aws-ip:8002/api/dashboard/state | jq '.balances'
```

**Expected:** Real balances from your Crypto.com account (not simulated data like `USDT: 10000.0`)

## 📋 Method 5: Check Backend Logs

Monitor the backend logs for connection status:

### For Local:
```bash
docker compose logs -f backend | grep -i "crypto\|exchange\|synced\|authentication"
```

### For AWS:
```bash
docker compose --profile aws logs -f backend-aws | grep -i "crypto\|exchange\|synced\|authentication"
```

**Look for:**
- ✅ "Exchange sync service started"
- ✅ "Synced X account balances"
- ✅ "Synced X open orders"
- ✅ No authentication errors

## 📋 Method 6: Setup Script Verification

If you used the setup script:

```bash
cd backend
python scripts/setup_live_trading.py
```

This will:
- ✅ Check current configuration
- ✅ Optionally verify connection interactively

## 🎯 Quick Check Commands Summary

### For AWS (Production):
```bash
# 1. Get your current IP (needs to be whitelisted)
docker compose --profile aws exec backend-aws python scripts/get_aws_ip.py

# 2. Check configuration
docker compose --profile aws exec backend-aws python scripts/check_crypto_config.py

# 3. Test connection
docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py

# 4. Full diagnostic (if having issues)
docker compose --profile aws exec backend-aws python scripts/diagnose_auth_issue.py
```

### For Local (Development):
```bash
# 1. Check configuration
docker compose exec backend python scripts/check_crypto_config.py

# 2. Test connection
docker compose exec backend python scripts/test_crypto_connection.py

# 3. Full diagnostic (if having issues)
docker compose exec backend python scripts/diagnose_auth_issue.py
```

## ✅ Success Indicators

You'll know the connection is working when:

1. ✅ `test_crypto_connection.py` shows all tests passing
2. ✅ Account balances are retrieved (real balances, not simulated)
3. ✅ No authentication errors in logs
4. ✅ Balances appear in `/api/dashboard/state` endpoint
5. ✅ Orders can be retrieved (if you have any)

## ❌ Common Issues

### Authentication Failed (40101)
- **Check:** Run `diagnose_auth_issue.py` for specific diagnosis
- **Fix:** Usually IP not whitelisted or API key missing permissions

### IP Illegal (40103)
- **Check:** Get your IP with `get_aws_ip.py`
- **Fix:** Add IP to Crypto.com Exchange API key whitelist

### Connection Refused
- **Check:** Verify `USE_CRYPTO_PROXY` setting matches your setup
- **Fix:** If using proxy, ensure proxy is running

## 📚 Related Documentation

- **Setup Guide:** `CRYPTO_COM_SETUP.md`
- **Credentials Setup:** `CONFIGURAR_CREDENCIALES.md`
- **Authentication Fix:** `AUTHENTICATION_FIX_GUIDE.md`
- **Quick Fix:** `QUICK_FIX_AUTHENTICATION.md`

