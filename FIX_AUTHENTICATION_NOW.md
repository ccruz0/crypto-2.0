# 🚀 Fix Authentication Error - Quick Start Guide

## ⚡ Immediate Action Required

Your automated trading platform is failing to create SELL orders due to an authentication error with Crypto.com Exchange API.

### 🔴 Error You're Seeing:
```
🔐 AUTOMATIC SELL ORDER CREATION FAILED: AUTHENTICATION ERROR
❌ Error: Authentication failed: Authentication failure
```

## 📋 Quick Fix (5 Minutes)

### Step 1: SSH into Your AWS Server
```bash
ssh ubuntu@your-aws-server-ip
cd ~/automated-trading-platform
```

### Step 2: Run the Quick Fix Script
```bash
./backend/scripts/quick_fix_auth_aws.sh
```

This script will:
- ✅ Show your server's IP address
- ✅ Check if credentials are configured
- ✅ Run authentication diagnostics
- ✅ Provide specific fix instructions

### Step 3: Most Likely Fix - Whitelist Your IP

**90% of authentication errors are caused by IP not being whitelisted!**

1. **Get your server IP** (the script will show it, or run):
   ```bash
   curl https://api.ipify.org
   ```

2. **Add IP to Crypto.com Exchange:**
   - Go to: https://exchange.crypto.com/
   - Login → **Settings** → **API Keys**
   - Click **Edit** on your API key
   - In **IP Whitelist**, add your server's IP
   - Click **Save**
   - **Wait 2-5 minutes** for changes to take effect

3. **Verify API Key Permissions:**
   - Make sure **Trade** permission is ✅ enabled
   - **Read** permission should also be ✅ enabled

### Step 4: Restart Backend
```bash
docker compose restart backend
```

### Step 5: Verify It Works
```bash
# Check logs for authentication success
docker compose logs backend -f | grep -i "authentication\|auth"
```

## 🔍 Detailed Diagnostics

If the quick fix doesn't work, run the full diagnostic:

```bash
python3 backend/scripts/diagnose_auth_issue.py
```

This will show:
- ✅ Exact error code (40101, 40103, etc.)
- ✅ Specific cause and solution
- ✅ Credential configuration status
- ✅ IP whitelist status

## 📚 Full Documentation

For comprehensive troubleshooting, see:
- **`AUTHENTICATION_TROUBLESHOOTING.md`** - Complete troubleshooting guide
- **`CRYPTO_COM_SETUP.md`** - Initial setup instructions

## 🎯 Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| **IP not whitelisted** | Add server IP to Crypto.com Exchange API key whitelist |
| **Missing credentials** | Set `EXCHANGE_CUSTOM_API_KEY` and `EXCHANGE_CUSTOM_API_SECRET` |
| **No Trade permission** | Enable "Trade" permission in API key settings |
| **Expired API key** | Create new API key and update credentials |

## ✅ Verification Checklist

After fixing, verify:
- [ ] Diagnostic script shows authentication success
- [ ] Backend logs show no authentication errors
- [ ] Test order creation works (use test alert endpoint)
- [ ] Automatic orders can be created successfully

## 🆘 Still Stuck?

1. **Check backend logs:**
   ```bash
   docker compose logs backend | grep -i "authentication\|401" | tail -50
   ```

2. **Enable diagnostic logging:**
   ```bash
   # Add to .env.aws
   CRYPTO_AUTH_DIAG=true
   # Then restart
   docker compose restart backend
   ```

3. **Review the full error in logs:**
   ```bash
   docker compose logs backend -f
   ```

---

**Time to Fix:** ~5 minutes  
**Most Common Cause:** IP not whitelisted (90% of cases)

