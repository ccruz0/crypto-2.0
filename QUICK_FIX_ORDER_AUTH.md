# ⚡ Quick Fix: Order Creation Authentication

## 🎯 The Problem

- ✅ Read operations work (balances, orders)
- ✅ Trade permissions enabled
- ✅ IP whitelisted
- ❌ Order creation fails: "Authentication failed: Authentication failure"

## 🔍 Most Likely Causes

Since everything else works, the issue is likely:

1. **exec_inst parameter formatting** (for margin orders)
2. **Params ordering mismatch** between signature and request body
3. **List parameter serialization** in signature string

## 🚀 Quick Test: Try Without exec_inst

### Step 1: Disable exec_inst Parameter

```bash
# On AWS server
echo "CRYPTO_SKIP_EXEC_INST=true" >> .env.aws
docker compose restart backend
```

### Step 2: Enable Diagnostic Logging

```bash
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws
docker compose restart backend
```

### Step 3: Monitor Next Order Creation

```bash
docker compose logs backend -f | grep -E "AUTHENTICATION|SELL order|CRYPTO_AUTH_DIAG"
```

## 📊 What to Look For

### If Order Creation Succeeds:
✅ **Issue was exec_inst formatting**
- Keep `CRYPTO_SKIP_EXEC_INST=true`
- The `leverage` parameter alone is sufficient for margin orders

### If Order Creation Still Fails:
Check the diagnostic logs for:
- Exact signature generation process
- Params string format
- API error response details

## 🔧 Alternative: Test Spot Order First

If you're creating margin orders, try a spot order first:

```python
# In your watchlist, temporarily set margin to false
# Or modify the signal to test with is_margin=False
```

If spot orders work but margin orders fail:
→ The issue is definitely with margin-specific params (leverage or exec_inst)

## 📝 Full Diagnostic

For complete analysis, run:

```bash
python3 backend/scripts/test_order_creation_auth.py
python3 backend/scripts/fix_order_creation_auth.py
```

These will show:
- How params are formatted for signature
- Signature generation differences
- Specific issues with list parameters

---

**Start with the exec_inst test - it's the quickest way to isolate the issue.**

