# 🚀 AWS Backend Deployment Guide

## ✅ Pre-Deployment Checklist

- [x] Credentials added to `.env.aws`
- [x] Docker Compose AWS profile configured
- [x] AWS Elastic IP: 47.130.143.159 (whitelisted in Crypto.com)
- [ ] `.env.aws` file copied to AWS server
- [ ] Backend deployed on AWS server

## 📋 Quick Deployment Steps

### 1. Copy Files to AWS Server

```bash
# From your local machine
scp .env.aws ubuntu@47.130.143.159:~/automated-trading-platform/
scp scripts/deploy_aws_backend.sh ubuntu@47.130.143.159:~/automated-trading-platform/scripts/
```

### 2. SSH to AWS Server

```bash
ssh ubuntu@47.130.143.159
cd ~/automated-trading-platform
```

### 3. Run Deployment Script

```bash
# Make script executable (if needed)
chmod +x scripts/deploy_aws_backend.sh

# Run deployment
./scripts/deploy_aws_backend.sh
```

### 4. Or Deploy Manually

```bash
# Start backend with AWS profile
docker compose --profile aws up -d backend-aws

# Check status
docker compose --profile aws ps backend-aws

# View logs
docker compose --profile aws logs -f backend-aws
```

## ✅ Verification Steps

### 1. Check Backend is Running

```bash
docker ps | grep backend-aws
```

### 2. Verify Credentials Loaded

```bash
docker compose --profile aws exec backend-aws env | grep EXCHANGE_CUSTOM
```

### 3. Check Outbound IP

```bash
docker compose --profile aws exec backend-aws curl -s https://api.ipify.org
# Should show: 47.130.143.159
```

### 4. Test API Connection

```bash
docker compose --profile aws exec backend-aws python -c "
from app.services.brokers.crypto_com_trade import CryptoComTradeClient
client = CryptoComTradeClient()
orders = client.get_open_orders()
print(f'✅ Got {len(orders)} orders')
"
```

### 5. Check for Authentication Errors

```bash
docker compose --profile aws logs backend-aws | grep -i "401\|auth.*fail"
# Should see NO authentication errors
```

### 6. Test Health Endpoint

```bash
curl http://localhost:8002/api/health/system | jq '.'
```

## 🔍 Troubleshooting

### Issue: Authentication still failing (40101)

**Check:**
1. IP whitelist in Crypto.com:
   - Go to https://exchange.crypto.com/ → Settings → API Keys
   - Verify `47.130.143.159` is whitelisted

2. Credentials in .env.aws:
   ```bash
   grep EXCHANGE_CUSTOM .env.aws
   ```

3. Outbound IP matches:
   ```bash
   curl https://api.ipify.org
   ```

### Issue: Backend won't start

**Check logs:**
```bash
docker compose --profile aws logs backend-aws --tail 100
```

### Issue: Credentials not loading

**Verify .env.aws is being read:**
```bash
docker compose --profile aws exec backend-aws env | grep EXCHANGE
```

## 📊 Expected Behavior

### ✅ On AWS (Production):
- Backend connects from IP: `47.130.143.159`
- Authentication succeeds
- Portfolio data loads
- No 40101 errors in logs

### ❌ Locally (Development):
- Backend connects from local IP (not whitelisted)
- Authentication fails (expected)
- Can develop UI/logic without API access

## 🎯 Success Indicators

You'll know deployment is successful when:

1. ✅ Backend container is running
2. ✅ No 40101 authentication errors in logs
3. ✅ Health endpoint returns `"global_status": "PASS"` (or shows working services)
4. ✅ Dashboard endpoint returns real portfolio data
5. ✅ Open orders endpoint returns orders from Crypto.com

## 📞 Support

If authentication still fails after deployment:
1. Double-check IP whitelist in Crypto.com Exchange
2. Verify credentials match exactly (no extra spaces)
3. Check API key has "Read" permission enabled
4. Review logs: `docker compose --profile aws logs backend-aws`

---

*Last updated: 2026-01-07*
