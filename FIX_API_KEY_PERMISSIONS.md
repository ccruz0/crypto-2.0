# 🔑 Fix: API Key Missing Trade Permission

## 🎯 Problem

You're seeing authentication errors when creating orders, but other operations (getting balances, reading orders) work fine.

**Error:**
```
🔐 AUTOMATIC SELL ORDER CREATION FAILED: AUTHENTICATION ERROR
❌ Error: Authentication failed: Authentication failure
```

## ✅ Solution: Enable Trade Permission

Your API key likely has **Read** permission but is missing **Trade** permission.

### Step 1: Check Current Permissions

1. Go to [Crypto.com Exchange](https://exchange.crypto.com/)
2. Login to your account
3. Navigate to **Settings** → **API Keys**
4. Find your API key (the one configured in your `.env.aws`)
5. Check the permissions:
   - ✅ **Read** - Should be enabled (this is why reading works)
   - ❌ **Trade** - Probably disabled (this is why order creation fails)

### Step 2: Enable Trade Permission

1. Click **Edit** on your API key
2. Enable the **Trade** checkbox
3. Click **Save**
4. **Wait 1-2 minutes** for changes to take effect

### Step 3: Verify It Works

1. Restart your backend:
   ```bash
   docker compose restart backend
   ```

2. Test order creation (use test alert endpoint or wait for next signal)

3. Check logs - you should no longer see authentication errors:
   ```bash
   docker compose logs backend -f | grep -i "authentication\|order created"
   ```

## 🔍 Why This Happens

- **Read operations** (get balances, get orders) only require **Read** permission ✅
- **Write operations** (create orders, cancel orders) require **Trade** permission ❌

If your API key only has Read permission:
- ✅ `get_account_summary()` works
- ✅ `get_open_orders()` works  
- ❌ `place_market_order()` fails with authentication error

## ✅ Verification Checklist

After enabling Trade permission:

- [ ] Trade permission is enabled in Crypto.com Exchange
- [ ] Backend has been restarted
- [ ] No authentication errors in logs
- [ ] Test order creation works
- [ ] Automatic orders can be created successfully

## 🆘 Still Not Working?

If you've enabled Trade permission and it still fails:

1. **Wait a few minutes** - permission changes can take time to propagate
2. **Check API key status** - Make sure it's not expired or revoked
3. **Verify credentials** - Double-check API key and secret in `.env.aws`
4. **Run diagnostic script:**
   ```bash
   python3 backend/scripts/diagnose_auth_issue.py
   ```

---

**Time to Fix:** ~2 minutes  
**Most Common Issue:** Missing Trade permission (90% of cases when read works but write fails)

