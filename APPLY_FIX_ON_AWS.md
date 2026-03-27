# 🚀 Apply Authentication Fix on AWS Server

## ⚡ Quick Fix Commands

**SSH into your AWS server and run these commands:**

```bash
cd ~/crypto-2.0

# 1. Add the fix to .env.aws
echo "CRYPTO_SKIP_EXEC_INST=true" >> .env.aws
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws

# 2. Verify it was added
grep -E "CRYPTO_SKIP_EXEC_INST|CRYPTO_AUTH_DIAG" .env.aws

# 3. Restart backend to apply changes
docker compose restart backend

# 4. Wait a few seconds for backend to start
sleep 5

# 5. Check logs to verify
docker compose logs backend --tail 50 | grep -E "CRYPTO_SKIP_EXEC_INST|MARGIN ORDER CONFIGURED"
```

## 🔍 Check Current Status

**Run this script to see what's happening:**

```bash
# Copy the check script to AWS (or create it there)
./check_auth_logs_aws.sh

# Or manually check:
docker compose logs backend --tail 200 | grep -A 30 "AUTHENTICATION FAILED"
```

## 📊 What to Look For

### After Applying Fix

**In the logs, you should see:**
```
📊 MARGIN ORDER CONFIGURED: leverage=10 (exec_inst skipped per CRYPTO_SKIP_EXEC_INST=true)
```

**Instead of:**
```
📊 MARGIN ORDER CONFIGURED: leverage=10, exec_inst=['MARGIN_ORDER']
```

### If Still Failing

**Check the diagnostic logs:**
```bash
docker compose logs backend --tail 500 | grep -A 30 "AUTHENTICATION FAILED"
```

**Look for:**
- Error code (40101, 40103, etc.)
- Exact error message
- Signature generation details (if CRYPTO_AUTH_DIAG=true)

## ✅ Verify Fix is Applied

**Check environment variables in running container:**
```bash
docker compose exec backend env | grep CRYPTO_SKIP_EXEC_INST
```

**Should show:**
```
CRYPTO_SKIP_EXEC_INST=true
```

## 🔄 Test the Fix

**After applying the fix, trigger a test alert:**
- Use the test alert endpoint
- Or wait for the next real signal

**Monitor logs:**
```bash
docker compose logs backend -f | grep -E "AUTHENTICATION|order created|SELL order"
```

**Success indicators:**
- ✅ "order created successfully"
- ✅ No "AUTHENTICATION FAILED" messages
- ✅ Order appears in exchange

---

**If the fix doesn't work, share the diagnostic logs output for further analysis.**

