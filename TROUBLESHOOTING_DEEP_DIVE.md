# 🔍 Deep Troubleshooting Guide for Authentication Error 40101

## Overview

This guide provides step-by-step troubleshooting to identify and fix the exact cause of authentication error 40101.

## Step 1: Enable Detailed Diagnostics

Enable detailed authentication logging:

```bash
# Enable diagnostics
docker compose exec backend-aws python scripts/enable_auth_diagnostics.py

# Or manually add to .env.local:
# CRYPTO_AUTH_DIAG=true

# Restart backend
docker compose restart backend-aws
```

## Step 2: Run Deep Diagnostic

Run the comprehensive diagnostic that tests signature generation step by step:

```bash
docker compose exec backend-aws python scripts/deep_auth_diagnostic.py
```

This will show:
- ✅ Exact signature generation process
- ✅ String-to-sign construction
- ✅ Encoding verification
- ✅ Actual API request/response
- ✅ Detailed error analysis

## Step 3: Analyze Results

### If Signature Generation Fails

**Symptoms:**
- Encoding errors
- Signature length not 64 characters
- UTF-8 encoding issues

**Possible Causes:**
1. **Hidden characters in credentials**
   - Solution: Copy credentials directly from Crypto.com
   - Remove any quotes or extra spaces
   - Use `verify_api_key_setup.py` to check format

2. **Encoding issues**
   - Solution: Ensure credentials are plain ASCII
   - Check for Unicode characters

### If Signature Generation Works But Request Fails

**Symptoms:**
- Signature generated correctly (64 chars)
- Request returns 40101

**Possible Causes:**

#### A. API Key Permissions (MOST COMMON)

**Check:**
1. Go to https://exchange.crypto.com/ → Settings → API Keys
2. Edit your API key
3. Verify **"Read"** permission is **ENABLED** ✅

**Fix:**
- Enable "Read" permission
- Save changes
- Wait 30-60 seconds
- Test again

#### B. API Key Status

**Check:**
- Status shows "Enabled" (not Disabled/Suspended)

**Fix:**
- If Disabled: Enable it
- If Suspended: Contact Crypto.com Support

#### C. IP Whitelist

**Check:**
1. Get your outbound IP from diagnostic
2. Verify it's in the whitelist

**Fix:**
- Add IP to whitelist (exactly, no spaces)
- Wait 10-30 seconds
- Test again

#### D. Invalid Credentials

**Check:**
```bash
docker compose exec backend-aws python scripts/verify_api_key_setup.py
```

**Fix:**
- Verify credentials match Crypto.com Exchange exactly
- Check for typos
- Regenerate API key if needed

## Step 4: Test Different Endpoints

Some endpoints might work while others fail. Test multiple endpoints:

```bash
docker compose exec backend-aws python scripts/test_crypto_connection.py
```

**Expected Results:**
- ✅ Public API: Should always work
- ✅ Private API: Should work if authentication is correct
- ✅ Open Orders: Should work if authentication is correct
- ✅ Order History: May work even if others fail (different endpoint)

## Step 5: Compare Working vs Non-Working

If some endpoints work but others don't:

1. **Check endpoint-specific requirements:**
   - Some endpoints require specific permissions
   - Some endpoints have different parameter requirements

2. **Check signature format:**
   - Empty params vs non-empty params
   - Parameter ordering

3. **Check request format:**
   - URL path format
   - Request body format

## Step 6: Verify Environment Variables

Check that credentials are actually loaded:

```bash
# Check environment variables
docker compose exec backend-aws env | grep EXCHANGE_CUSTOM

# Should show:
# EXCHANGE_CUSTOM_API_KEY=z3HWF8m292zJKABkzfXWvQ
# EXCHANGE_CUSTOM_API_SECRET=cxakp_oGDfb6D6JW396cYGz8FHmg
```

**Common Issues:**
- Variables not set
- Extra spaces or quotes
- Wrong variable names
- Not loaded from .env.local

## Step 7: Check Backend Logs

With `CRYPTO_AUTH_DIAG=true`, check detailed logs:

```bash
docker compose logs backend-aws | grep -i "CRYPTO_AUTH_DIAG" | tail -50
```

Look for:
- Signature generation details
- String-to-sign length
- Request details
- Response details

## Step 8: Test with Minimal Request

Test with the simplest possible request:

```python
# Minimal test
method = "private/user-balance"
params = {}
# This should work if authentication is correct
```

## Step 9: Compare with Known Working Example

If you have a working API key from another system:

1. Compare signature generation
2. Compare request format
3. Compare credentials format

## Step 10: Regenerate API Key (Last Resort)

If nothing else works:

1. **Delete old API key** in Crypto.com Exchange
2. **Create new API key:**
   - Enable "Read" permission ✅
   - Enable "Trade" permission (if needed) ✅
   - Add server IP to whitelist
   - Copy new credentials

3. **Update .env.local:**
   ```bash
   EXCHANGE_CUSTOM_API_KEY=new_api_key
   EXCHANGE_CUSTOM_API_SECRET=new_api_secret
   ```

4. **Restart backend:**
   ```bash
   docker compose restart backend-aws
   ```

5. **Test:**
   ```bash
   docker compose exec backend-aws python scripts/deep_auth_diagnostic.py
   ```

## Common Error Patterns

### Pattern 1: Works Yesterday, Fails Today

**Possible Causes:**
- API key permissions changed
- API key disabled/suspended
- IP address changed
- Credentials revoked

**Solution:**
- Check API key status in Crypto.com Exchange
- Verify permissions are still enabled
- Check IP whitelist

### Pattern 2: Works Locally, Fails on Server

**Possible Causes:**
- Different IP addresses
- Different environment variables
- Server IP not whitelisted

**Solution:**
- Get server's outbound IP
- Add to whitelist
- Verify environment variables on server

### Pattern 3: Some Endpoints Work, Others Don't

**Possible Causes:**
- Different permission requirements
- Different signature formats
- Endpoint-specific issues

**Solution:**
- Check which endpoints work
- Compare working vs non-working requests
- Check endpoint-specific requirements

## Diagnostic Tools Summary

1. **`deep_auth_diagnostic.py`** - Step-by-step signature testing
2. **`diagnose_auth_40101.py`** - Comprehensive diagnostic
3. **`verify_api_key_setup.py`** - Setup verification
4. **`test_crypto_connection.py`** - Connection testing
5. **`enable_auth_diagnostics.py`** - Enable detailed logging

## Expected Timeline

- **Step 1-2** (Enable diagnostics + Run deep diagnostic): 2-5 minutes
- **Step 3** (Analyze results): 5-10 minutes
- **Step 4-6** (Testing + Verification): 5-10 minutes
- **Step 7-10** (Advanced troubleshooting): 10-30 minutes
- **Total**: 20-60 minutes depending on issue complexity

## Success Criteria

You'll know it's fixed when:

1. ✅ `deep_auth_diagnostic.py` shows "✅ SUCCESS! Authentication worked!"
2. ✅ `test_crypto_connection.py` shows all endpoints working
3. ✅ Daily summary shows real balance data
4. ✅ No authentication errors in logs

## Getting Help

If you've tried all steps and still have issues:

1. **Collect diagnostic output:**
   ```bash
   docker compose exec backend-aws python scripts/deep_auth_diagnostic.py > auth_diagnostic_output.txt
   ```

2. **Collect logs:**
   ```bash
   docker compose logs backend-aws | grep -i "crypto\|auth\|40101" > auth_logs.txt
   ```

3. **Contact Crypto.com Support** with:
   - Diagnostic output
   - Logs
   - API key (first 10 chars)
   - Error code: 40101
   - Your outbound IP

## Related Documentation

- `QUICK_FIX_40101.md` - Quick fix guide
- `CRYPTO_COM_AUTHENTICATION_GUIDE.md` - Complete guide
- `NEXT_STEPS_ACTION_PLAN.md` - Action plan

