# 🔐 Crypto.com Exchange API Authentication Troubleshooting Guide

This guide helps you diagnose and fix authentication errors when creating automatic trading orders.

## 🚨 Common Error Messages

### Error: "Authentication failed: Authentication failure"

This error occurs when the system cannot authenticate with Crypto.com Exchange API. The most common causes are:

1. **API credentials not configured** - Missing or incorrect API key/secret
2. **IP address not whitelisted** - Your server's IP must be in the API key whitelist
3. **API key permissions** - API key doesn't have "Trade" permission
4. **Expired or revoked API key** - API key may have been deleted or expired

## ⚠️ IMPORTANT: If Read Works But Write Fails

**If you can get balances and orders but order creation fails**, this is almost certainly a **permissions issue**, not an IP or credential problem.

**Quick Fix:** Enable **Trade** permission on your API key in Crypto.com Exchange.

See [`FIX_API_KEY_PERMISSIONS.md`](FIX_API_KEY_PERMISSIONS.md) for detailed instructions.

---

## 🔍 Step 1: Run Diagnostic Script

On your AWS server, run the diagnostic script to identify the issue:

```bash
cd ~/automated-trading-platform
python3 backend/scripts/diagnose_auth_issue.py
```

This script will:
- ✅ Check if API credentials are configured
- ✅ Display your server's outbound IP address
- ✅ Test authentication with Crypto.com Exchange API
- ✅ Provide specific error codes and solutions

## 🔧 Step 2: Verify API Credentials

### Check Environment Variables

On AWS, verify your credentials are set:

```bash
# SSH into your AWS server
ssh ubuntu@your-server-ip

# Check if credentials are set
echo $EXCHANGE_CUSTOM_API_KEY
echo $EXCHANGE_CUSTOM_API_SECRET
```

### If Using Docker Compose

Check your `.env.aws` file or environment variables:

```bash
# View environment variables in running container
docker compose exec backend env | grep EXCHANGE_CUSTOM
```

### Required Environment Variables

```bash
# Direct connection (recommended)
USE_CRYPTO_PROXY=false
LIVE_TRADING=true
EXCHANGE_CUSTOM_API_KEY=your_api_key_here
EXCHANGE_CUSTOM_API_SECRET=your_api_secret_here
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1

# OR using proxy
USE_CRYPTO_PROXY=true
CRYPTO_PROXY_URL=http://127.0.0.1:9000
CRYPTO_PROXY_TOKEN=your_proxy_token
LIVE_TRADING=true
```

## 🌐 Step 3: Whitelist Your IP Address

**This is the most common cause of authentication failures on AWS!**

### Get Your Server's IP Address

```bash
# On your AWS server
curl https://api.ipify.org
```

### Add IP to Crypto.com Exchange Whitelist

1. Go to [Crypto.com Exchange](https://exchange.crypto.com/)
2. Log in to your account
3. Navigate to **Settings** → **API Keys**
4. Click **Edit** on your API key
5. In the **IP Whitelist** section, add your server's IP address
6. Click **Save**
7. **Wait 2-5 minutes** for changes to take effect

### Verify IP Whitelist

After adding your IP, test again:

```bash
python3 backend/scripts/diagnose_auth_issue.py
```

## 🔑 Step 4: Verify API Key Permissions

Your API key must have the following permissions:

- ✅ **Read** - Required for checking balances and orders
- ✅ **Trade** - **REQUIRED** for creating orders (BUY/SELL)
- ❌ **Withdraw** - Not required (leave disabled for security)

### Check Permissions

1. Go to [Crypto.com Exchange](https://exchange.crypto.com/)
2. Navigate to **Settings** → **API Keys**
3. Check your API key permissions
4. If "Trade" is not enabled, click **Edit** and enable it

## ⏰ Step 5: Check API Key Status

### Verify API Key is Active

1. Go to [Crypto.com Exchange](https://exchange.crypto.com/)
2. Navigate to **Settings** → **API Keys**
3. Check if your API key shows as **Active**
4. If it shows as **Revoked** or **Expired**, create a new API key

### Create New API Key (if needed)

1. Go to **Settings** → **API Keys**
2. Click **Create API Key**
3. Set permissions: **Read** + **Trade**
4. **IMPORTANT**: Copy the API key and secret immediately (secret is only shown once!)
5. Add your server's IP to the whitelist
6. Update environment variables on your server

## 🐳 Step 6: Restart Services

After updating credentials or IP whitelist:

```bash
# Restart backend service
docker compose restart backend

# Or if running without Docker
# Stop and restart your backend service
```

## 📊 Step 7: Enable Diagnostic Logging

For detailed authentication diagnostics, enable diagnostic mode:

```bash
# Add to your .env.aws file
CRYPTO_AUTH_DIAG=true
```

Then restart the backend and check logs:

```bash
docker compose logs backend | grep CRYPTO_AUTH_DIAG
```

## 🔍 Error Code Reference

| Error Code | Meaning | Solution |
|------------|---------|----------|
| **40101** | Authentication failure | Check API key/secret, verify permissions |
| **40103** | IP not whitelisted | Add server IP to API key whitelist |
| **401** | General authentication error | Run diagnostic script for details |

## ✅ Verification Checklist

After fixing the issue, verify everything works:

- [ ] API credentials are set in environment variables
- [ ] Server IP is whitelisted in Crypto.com Exchange
- [ ] API key has "Trade" permission enabled
- [ ] API key is active (not revoked/expired)
- [ ] Diagnostic script shows authentication success
- [ ] Backend service has been restarted
- [ ] Test order creation works (use test alert endpoint)

## 🆘 Still Having Issues?

If authentication still fails after following all steps:

1. **Run the diagnostic script** and save the output
2. **Check backend logs** for detailed error messages:
   ```bash
   docker compose logs backend | grep -i "authentication\|auth\|401"
   ```
3. **Verify credentials format** - Make sure there are no extra spaces or quotes
4. **Test with a simple API call** using the diagnostic script
5. **Contact Crypto.com Support** if the API key appears correct but still fails

## 📝 Quick Reference

### Test Authentication
```bash
python3 backend/scripts/diagnose_auth_issue.py
```

### Check Logs
```bash
docker compose logs backend -f | grep -i auth
```

### Get Server IP
```bash
curl https://api.ipify.org
```

### Restart Backend
```bash
docker compose restart backend
```

---

**Last Updated**: 2025-12-22

