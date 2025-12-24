# 🔐 Crypto.com API Authentication Guide

## Quick Start

If you're getting authentication errors, follow these steps in order:

### 1. Run Setup Verification
```bash
docker compose exec backend-aws python scripts/verify_api_key_setup.py
```
This checks your environment variables and provides a checklist.

### 2. Run Comprehensive Diagnostic
```bash
docker compose exec backend-aws python scripts/diagnose_auth_40101.py
```
This provides detailed diagnostics and shows your outbound IP address.

### 3. Run Connection Test
```bash
docker compose exec backend-aws python scripts/test_crypto_connection.py
```
This tests all API endpoints and shows which ones work.

## Common Error Codes

### Error 40101 - Authentication Failure

**Most Common Causes:**
1. ❌ API key doesn't have "Read" permission
2. ❌ API key is disabled or suspended
3. ❌ Invalid API key or secret
4. ❌ Credentials have extra spaces or quotes

**How to Fix:**

1. **Enable "Read" Permission** (MOST COMMON FIX):
   - Go to https://exchange.crypto.com/ → Settings → API Keys
   - Edit your API key
   - **Enable "Read" permission** ✅
   - Save changes

2. **Check API Key Status**:
   - Verify API key shows "Enabled" (not Disabled/Suspended)
   - If suspended, contact Crypto.com Support

3. **Verify Credentials**:
   - Check `EXCHANGE_CUSTOM_API_KEY` matches your API key exactly
   - Check `EXCHANGE_CUSTOM_API_SECRET` matches your secret exactly
   - Remove any quotes or extra spaces

4. **Regenerate API Key** (if needed):
   - Delete old API key
   - Create new one with "Read" permission enabled
   - Add server IP to whitelist
   - Update environment variables

### Error 40103 - IP Illegal (Not Whitelisted)

**How to Fix:**

1. **Get Your Outbound IP**:
   ```bash
   docker compose exec backend-aws python -c "import requests; print(requests.get('https://api.ipify.org', timeout=5).text.strip())"
   ```

2. **Add IP to Whitelist**:
   - Go to https://exchange.crypto.com/ → Settings → API Keys
   - Edit your API key
   - Add the outbound IP to whitelist (exactly, no spaces)
   - Save changes
   - Wait 10-30 seconds for changes to propagate

## Step-by-Step Setup

### 1. Create API Key in Crypto.com Exchange

1. Go to https://exchange.crypto.com/
2. Log in to your account
3. Navigate to **Settings** → **API Keys**
4. Click **Create API Key**
5. **Enable "Read" permission** ✅ (required for balance checks)
6. Enable "Trade" permission if you want to place orders
7. Add your server's IP address to the whitelist
8. Copy the API key and secret (you'll only see the secret once!)

### 2. Configure Environment Variables

Add to your `.env.local` file:

```bash
EXCHANGE_CUSTOM_API_KEY=your_api_key_here
EXCHANGE_CUSTOM_API_SECRET=your_api_secret_here
LIVE_TRADING=true
```

**Important:**
- No quotes around values
- No extra spaces
- Use exact values from Crypto.com Exchange

### 3. Verify Configuration

```bash
# Check configuration
docker compose exec backend-aws python scripts/verify_api_key_setup.py

# Test connection
docker compose exec backend-aws python scripts/test_crypto_connection.py
```

### 4. Restart Services

After updating credentials:

```bash
docker compose restart backend-aws
```

## Diagnostic Tools

### 1. Setup Verification
```bash
docker compose exec backend-aws python scripts/verify_api_key_setup.py
```
- Checks environment variables
- Provides manual verification checklist
- Shows configuration summary

### 2. Comprehensive Diagnostic
```bash
docker compose exec backend-aws python scripts/diagnose_auth_40101.py
```
- Detailed authentication testing
- Shows outbound IP address
- Provides step-by-step diagnosis
- Actionable recommendations

### 3. Connection Test
```bash
docker compose exec backend-aws python scripts/test_crypto_connection.py
```
- Tests public API (no auth)
- Tests private API (with auth)
- Tests open orders endpoint
- Tests order history endpoint

### 4. Configuration Check
```bash
docker compose exec backend-aws python scripts/check_crypto_config.py
```
- Shows current configuration
- Verifies credentials are set
- Checks proxy settings

## Troubleshooting

### Issue: "Error 40101" persists after enabling Read permission

**Solutions:**
1. Wait 30-60 seconds after enabling permission (propagation delay)
2. Restart backend: `docker compose restart backend-aws`
3. Verify permission is actually enabled (refresh the page)
4. Check API key is not suspended
5. Regenerate API key if needed

### Issue: "Error 40103" - IP not whitelisted

**Solutions:**
1. Get your exact outbound IP from diagnostic script
2. Remove any spaces from IP in whitelist
3. Wait 10-30 seconds after adding IP
4. Verify IP is correct (check from server, not local machine)
5. If using VPN/proxy, whitelist the VPN/proxy IP

### Issue: Credentials seem correct but still failing

**Solutions:**
1. Check for hidden characters (copy-paste from Crypto.com directly)
2. Verify no quotes around values in `.env.local`
3. Check environment variables are actually loaded:
   ```bash
   docker compose exec backend-aws env | grep EXCHANGE_CUSTOM
   ```
4. Regenerate API key and update credentials

### Issue: Works locally but fails on server

**Solutions:**
1. Server IP is different from local IP - add server IP to whitelist
2. Check server's outbound IP:
   ```bash
   docker compose exec backend-aws python -c "import requests; print(requests.get('https://api.ipify.org', timeout=5).text.strip())"
   ```
3. Add server IP to whitelist in Crypto.com Exchange

## Best Practices

1. **Always enable "Read" permission** - Required even for trading
2. **Whitelist specific IPs** - Don't use "Allow all IPs" in production
3. **Keep credentials secure** - Never commit to git, use `.env.local`
4. **Test after changes** - Run diagnostic scripts after any changes
5. **Monitor logs** - Check backend logs for detailed error messages

## API Key Permissions

- **Read**: Required for checking balances, order history, account info
- **Trade**: Required for placing/canceling orders
- **Withdraw**: Required for withdrawals (use with caution)

**Recommendation**: Enable "Read" and "Trade" for trading bots. Never enable "Withdraw" unless absolutely necessary.

## IP Whitelist

- Add specific IP addresses, not ranges
- No spaces in IP addresses
- Changes take 10-30 seconds to propagate
- Get IP from server, not your local machine
- If using VPN/proxy, whitelist the VPN/proxy IP

## Getting Help

If you've tried all the above and still have issues:

1. Run comprehensive diagnostic:
   ```bash
   docker compose exec backend-aws python scripts/diagnose_auth_40101.py
   ```

2. Check backend logs:
   ```bash
   docker compose logs backend-aws | grep -i "authentication\|40101\|crypto"
   ```

3. Contact Crypto.com Support with:
   - Your API key (first 10 chars)
   - Error code (40101 or 40103)
   - Your outbound IP address
   - Screenshot of API key permissions

## Related Documentation

- `QUICK_FIX_40101.md` - Quick fix guide for error 40101
- `AUTHENTICATION_ERROR_REPORTING_IMPROVEMENTS.md` - Technical details
- `AUTHENTICATION_IMPROVEMENTS_SUMMARY.md` - Summary of improvements
- `TROUBLESHOOTING_CRYPTO_COM.md` - Additional troubleshooting

