# 🚀 Quick Fix: Authentication Error

## ⚡ Immediate Steps

### 1. Run Diagnostic (2 minutes)
```bash
# On AWS
docker compose --profile aws exec backend-aws python scripts/diagnose_auth_issue.py

# On local  
docker compose exec backend python scripts/diagnose_auth_issue.py
```

### 2. Most Common Fixes

#### Fix #1: Check API Key Permissions
1. Go to https://exchange.crypto.com/ → Settings → API Keys
2. Edit your API key
3. Ensure **Read** and **Trade** are enabled ✅
4. Save

#### Fix #2: Whitelist Your IP
1. Get your IP: `curl https://api.ipify.org`
2. Go to Crypto.com Exchange → API Keys → Edit
3. Add your IP to whitelist
4. Save and wait 30 seconds

#### Fix #3: Verify Credentials in .env.aws
```bash
# Check if credentials are set
docker compose --profile aws exec backend-aws env | grep EXCHANGE_CUSTOM

# Should show:
# EXCHANGE_CUSTOM_API_KEY=your_key
# EXCHANGE_CUSTOM_API_SECRET=your_secret
```

#### Fix #4: Restart Backend
```bash
# AWS
docker compose --profile aws restart backend-aws

# Local
docker compose restart backend
```

## 🔍 Error Codes

- **40101**: Authentication failure → Check credentials & permissions
- **40103**: IP illegal → Whitelist your IP address

## 📝 Full Guide

See [AUTHENTICATION_FIX_GUIDE.md](AUTHENTICATION_FIX_GUIDE.md) for detailed troubleshooting.

