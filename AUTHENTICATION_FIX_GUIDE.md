# 🔐 Crypto.com Exchange Authentication Fix Guide

## 🚨 Problem

You're seeing this error when trying to create automatic orders:

```
🔐 AUTOMATIC ORDER CREATION FAILED: AUTHENTICATION ERROR
❌ Error: Authentication failed: Authentication failure
```

This indicates that the Crypto.com Exchange API is rejecting your authentication credentials.

## 🔍 Quick Diagnosis

Run the diagnostic script to identify the exact issue:

```bash
# On AWS
docker compose --profile aws exec backend-aws python scripts/diagnose_auth_issue.py

# On local
docker compose exec backend python scripts/diagnose_auth_issue.py
```

This will check:
- ✅ API credentials configuration
- ✅ Public IP address
- ✅ Public API connectivity
- ✅ Private API authentication
- ✅ Specific error diagnosis

## 🛠️ Common Causes & Solutions

### 1. ❌ API Credentials Not Configured

**Symptoms:**
- `EXCHANGE_CUSTOM_API_KEY` or `EXCHANGE_CUSTOM_API_SECRET` is empty
- Error: "API credentials not configured"

**Solution:**

1. Get your API credentials from Crypto.com Exchange:
   - Go to https://exchange.crypto.com/
   - Settings → API Keys
   - Create a new API key or use an existing one

2. Update your environment file (`.env.aws` for AWS, `.env.local` for local):

```bash
EXCHANGE_CUSTOM_API_KEY=your_api_key_here
EXCHANGE_CUSTOM_API_SECRET=your_api_secret_here
```

3. **Important:** Make sure there are no quotes around the values:
   ```bash
   # ❌ WRONG
   EXCHANGE_CUSTOM_API_KEY="your_key"
   
   # ✅ CORRECT
   EXCHANGE_CUSTOM_API_KEY=your_key
   ```

4. Restart the backend:
   ```bash
   # AWS
   docker compose --profile aws restart backend-aws
   
   # Local
   docker compose restart backend
   ```

### 2. ❌ IP Address Not Whitelisted

**Symptoms:**
- Error: "Authentication failure (code: 40101)" or "IP illegal (code: 40103)"
- Works from one location but not another

**Solution:**

1. Get your current public IP:
   ```bash
   curl https://api.ipify.org
   ```

2. Add IP to whitelist:
   - Go to https://exchange.crypto.com/ → Settings → API Keys
   - Click "Edit" on your API key
   - Add your IP address to the whitelist
   - Save changes
   - Wait 10-30 seconds for changes to propagate

3. **For AWS deployments:**
   - If using Elastic IP, whitelist the Elastic IP address
   - If using dynamic IP, you may need to use a proxy or VPN

### 3. ❌ API Key Missing Permissions

**Symptoms:**
- Authentication works for reading balances but fails for trading
- Error: "Authentication failure" when placing orders

**Solution:**

1. Check API key permissions:
   - Go to https://exchange.crypto.com/ → Settings → API Keys
   - Edit your API key
   - Ensure these permissions are enabled:
     - ✅ **Read** (required for balances, orders)
     - ✅ **Trade** (required for placing orders)
     - ✅ **Transfer** (optional, for transfers)

2. If permissions are missing:
   - Enable the required permissions
   - Save changes
   - Restart the backend

### 4. ❌ API Key Disabled or Suspended

**Symptoms:**
- Authentication worked before but suddenly stopped
- Error: "Authentication failure" on all requests

**Solution:**

1. Check API key status:
   - Go to https://exchange.crypto.com/ → Settings → API Keys
   - Check if your API key is "Enabled" or "Disabled"

2. If disabled:
   - Enable the API key
   - Save changes

3. If suspended:
   - Contact Crypto.com Support
   - You may need to create a new API key

### 5. ❌ Using Proxy but Proxy Not Running

**Symptoms:**
- `USE_CRYPTO_PROXY=true` but proxy connection fails
- Error: "Connection refused" or "Proxy error"

**Solution:**

**Option A: Use Direct Connection (Recommended for AWS with Elastic IP)**

1. Update `.env.aws`:
   ```bash
   USE_CRYPTO_PROXY=false
   EXCHANGE_CUSTOM_API_KEY=your_key
   EXCHANGE_CUSTOM_API_SECRET=your_secret
   EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
   ```

2. Make sure your AWS Elastic IP is whitelisted in Crypto.com

3. Restart backend:
   ```bash
   docker compose --profile aws restart backend-aws
   ```

**Option B: Fix Proxy Configuration**

1. Ensure proxy is running and accessible
2. Verify proxy URL and token in environment:
   ```bash
   CRYPTO_PROXY_URL=http://host.docker.internal:9000
   CRYPTO_PROXY_TOKEN=your_proxy_token
   ```

## 📋 Step-by-Step Fix Checklist

Follow these steps in order:

- [ ] **Step 1:** Run diagnostic script to identify the issue
  ```bash
  docker compose --profile aws exec backend-aws python scripts/diagnose_auth_issue.py
  ```

- [ ] **Step 2:** Verify API credentials are set
  - Check `.env.aws` (for AWS) or `.env.local` (for local)
  - Ensure `EXCHANGE_CUSTOM_API_KEY` and `EXCHANGE_CUSTOM_API_SECRET` are set
  - Remove any quotes around values

- [ ] **Step 3:** Get your public IP address
  ```bash
  curl https://api.ipify.org
  ```

- [ ] **Step 4:** Whitelist your IP in Crypto.com Exchange
  - Go to https://exchange.crypto.com/ → Settings → API Keys
  - Edit your API key
  - Add your IP to whitelist
  - Save and wait 30 seconds

- [ ] **Step 5:** Verify API key permissions
  - Read: ✅ Enabled
  - Trade: ✅ Enabled (for automatic orders)
  - Transfer: Optional

- [ ] **Step 6:** Check API key status
  - Ensure it's "Enabled" (not "Disabled" or "Suspended")

- [ ] **Step 7:** Restart backend
  ```bash
  # AWS
  docker compose --profile aws restart backend-aws
  
  # Local
  docker compose restart backend
  ```

- [ ] **Step 8:** Test connection again
  ```bash
  docker compose --profile aws exec backend-aws python scripts/diagnose_auth_issue.py
  ```

- [ ] **Step 9:** Monitor logs for authentication errors
  ```bash
  docker compose --profile aws logs -f backend-aws | grep -i "authentication\|401"
  ```

## 🔧 Advanced Troubleshooting

### Enable Authentication Diagnostics

To get detailed authentication logs, enable diagnostics:

1. Add to `.env.aws`:
   ```bash
   CRYPTO_AUTH_DIAG=true
   ```

2. Restart backend:
   ```bash
   docker compose --profile aws restart backend-aws
   ```

3. Check logs:
   ```bash
   docker compose --profile aws logs backend-aws | grep CRYPTO_AUTH_DIAG
   ```

**Note:** This will log safe diagnostic information (no full secrets), but disable it after troubleshooting.

### Test Connection Manually

Test the connection using the test script:

```bash
# AWS
docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py

# Local
docker compose exec backend python scripts/test_crypto_connection.py
```

### Verify Environment Variables in Container

Check if environment variables are loaded correctly:

```bash
# AWS
docker compose --profile aws exec backend-aws env | grep EXCHANGE_CUSTOM

# Local
docker compose exec backend env | grep EXCHANGE_CUSTOM
```

## 📞 Still Having Issues?

If the problem persists after following all steps:

1. **Double-check all credentials:**
   - Verify API key and secret are correct (no typos)
   - Ensure no extra spaces or newlines
   - Check for quotes that shouldn't be there

2. **Regenerate API key:**
   - Create a new API key in Crypto.com Exchange
   - Update credentials in `.env.aws` or `.env.local`
   - Add IP to whitelist immediately
   - Restart backend

3. **Check Crypto.com Exchange status:**
   - Visit https://status.crypto.com/
   - Check if there are any API issues

4. **Review recent changes:**
   - Check if IP address changed (if not using Elastic IP)
   - Verify no recent changes to API key settings
   - Check if API key was regenerated elsewhere

## ✅ Success Indicators

You'll know authentication is working when:

- ✅ Diagnostic script shows "AUTHENTICATION SUCCESSFUL"
- ✅ Account balances are retrieved successfully
- ✅ No authentication errors in logs
- ✅ Automatic orders can be created (if `trade_enabled=True`)

## 🔒 Security Best Practices

1. **Never commit credentials to git:**
   - Use `.env.aws` and `.env.local` (already in `.gitignore`)
   - Never share API keys publicly

2. **Use IP whitelisting:**
   - Always whitelist specific IPs
   - Don't use "Allow all IPs" unless absolutely necessary

3. **Limit API key permissions:**
   - Only enable permissions you actually need
   - Don't enable "Transfer" unless you need it

4. **Rotate credentials regularly:**
   - Regenerate API keys periodically
   - Update credentials in environment files

5. **Monitor for unauthorized access:**
   - Check API key usage in Crypto.com Exchange
   - Review logs for suspicious activity

