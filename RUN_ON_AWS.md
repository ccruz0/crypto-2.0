# 🚀 Run Authentication Diagnostic on AWS

## Quick Fix Commands

Run these commands on your AWS server to diagnose and fix the authentication issue:

### Option 1: Run Individual Scripts

```bash
# SSH into AWS
ssh hilovivo-aws

# Get current IP (needs to be whitelisted)
cd ~/automated-trading-platform
docker compose --profile aws exec backend-aws python scripts/get_aws_ip.py

# Check configuration
docker compose --profile aws exec backend-aws python scripts/check_crypto_config.py

# Run full diagnostic
docker compose --profile aws exec backend-aws python scripts/diagnose_auth_issue.py

# Test connection
docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py
```

### Option 2: Run All at Once

```bash
# From your local machine, run:
ssh hilovivo-aws "cd ~/automated-trading-platform && bash backend/scripts/fix_auth_on_aws.sh"
```

## Most Common Fix

Based on the error message, the most likely issue is:

### 1. Get Your AWS IP
```bash
docker compose --profile aws exec backend-aws python scripts/get_aws_ip.py
```

### 2. Whitelist the IP
1. Go to https://exchange.crypto.com/ → Settings → API Keys
2. Edit your API key
3. Add the IP from step 1 to the whitelist
4. Save and wait 30 seconds

### 3. Verify API Key Permissions
- ✅ **Read** must be enabled
- ✅ **Trade** must be enabled (for automatic orders)

### 4. Restart Backend
```bash
docker compose --profile aws restart backend-aws
```

### 5. Test Again
```bash
docker compose --profile aws exec backend-aws python scripts/diagnose_auth_issue.py
```

## Check Current Configuration

```bash
# Check environment variables
docker compose --profile aws exec backend-aws env | grep EXCHANGE_CUSTOM

# Check if credentials are loaded
docker compose --profile aws exec backend-aws python -c "
from app.services.brokers.crypto_com_trade import CryptoComTradeClient
client = CryptoComTradeClient()
print(f'API Key configured: {bool(client.api_key)}')
print(f'API Secret configured: {bool(client.api_secret)}')
print(f'Using proxy: {client.use_proxy}')
print(f'Base URL: {client.base_url}')
"
```

## Monitor Logs

```bash
# Watch for authentication errors
docker compose --profile aws logs -f backend-aws | grep -i "authentication\|401\|auth"

# Watch all backend logs
docker compose --profile aws logs -f backend-aws
```

## Full Troubleshooting Guide

See [AUTHENTICATION_FIX_GUIDE.md](AUTHENTICATION_FIX_GUIDE.md) for detailed troubleshooting steps.

