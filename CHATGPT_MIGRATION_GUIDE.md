# Migration Guide: NordVPN Dedicated IP → AWS Elastic IP

## Context

I have an automated trading platform running on AWS EC2 that currently uses NordVPN (via Gluetun container) with a dedicated IP for connecting to Crypto.com Exchange API. I want to **stop paying for NordVPN dedicated IP** and use **AWS Elastic IP** instead.

## Current Setup

- **Platform**: Automated trading platform (FastAPI backend + Next.js frontend)
- **Infrastructure**: AWS EC2 instance running Docker containers
- **VPN**: NordVPN via Gluetun container (docker-compose profile: `aws`)
- **Current Flow**: Backend → Gluetun VPN → NordVPN Server → Crypto.com API
- **Cost**: Paying extra for NordVPN dedicated IP subscription (~$70/year)

## Goal

- **Remove dependency on NordVPN dedicated IP**
- **Use AWS Elastic IP** (free while instance is running)
- **Connect directly** from AWS to Crypto.com API
- **Whitelist Elastic IP** in Crypto.com Exchange

## Current Architecture

```
backend-aws container
  ├── depends_on: gluetun (VPN container)
  ├── depends_on: db
  ├── USE_CRYPTO_PROXY=true (uses proxy at host.docker.internal:9000)
  └── Connects to Crypto.com via VPN (NordVPN dedicated IP)
```

## Target Architecture

```
backend-aws container
  ├── depends_on: db (removed gluetun dependency)
  ├── USE_CRYPTO_PROXY=false (direct connection)
  └── Connects directly to Crypto.com using AWS Elastic IP
```

## Files That Need Changes

1. **`.env.aws`** - Environment variables for AWS backend
   - Change: `USE_CRYPTO_PROXY=false`
   - Ensure: `LIVE_TRADING=true`
   - Ensure: `EXCHANGE_CUSTOM_API_KEY` and `EXCHANGE_CUSTOM_API_SECRET` are set

2. **`docker-compose.yml`** - Docker Compose configuration
   - Location: `backend-aws` service, `depends_on` section (around line 201-205)
   - Change: Remove `gluetun` dependency
   - From:
     ```yaml
     depends_on:
       gluetun:
         condition: service_healthy
       db:
         condition: service_healthy
     ```
   - To:
     ```yaml
     depends_on:
       db:
         condition: service_healthy
     ```

3. **AWS EC2 Instance** - Need to allocate and associate Elastic IP
   - Allocate new Elastic IP
   - Associate to EC2 instance
   - Note the Elastic IP address

4. **Crypto.com Exchange** - API Key whitelist
   - Add Elastic IP to whitelist
   - URL: https://exchange.crypto.com/ → Settings → API Keys

## Step-by-Step Migration Checklist

### Step 1: Allocate AWS Elastic IP
- [ ] Run `./scripts/setup_aws_elastic_ip.sh` OR
- [ ] Use AWS Console: EC2 → Elastic IPs → Allocate → Associate to instance
- [ ] Note the Elastic IP address (e.g., `54.254.150.31`)

### Step 2: Whitelist Elastic IP in Crypto.com
- [ ] Go to https://exchange.crypto.com/
- [ ] Settings → API Keys
- [ ] Edit your API Key
- [ ] Add Elastic IP to whitelist
- [ ] Save

### Step 3: Update Environment Variables
- [ ] Edit `.env.aws` file
- [ ] Set `USE_CRYPTO_PROXY=false`
- [ ] Verify `LIVE_TRADING=true`
- [ ] Verify API credentials are set

### Step 4: Update Docker Compose
- [ ] Edit `docker-compose.yml`
- [ ] Find `backend-aws` service (around line 144)
- [ ] Find `depends_on` section (around line 201)
- [ ] Remove `gluetun` dependency
- [ ] Keep only `db` dependency

### Step 5: Deploy Changes
- [ ] SSH to AWS instance: `ssh ubuntu@your-aws-instance`
- [ ] Navigate to project: `cd automated-trading-platform`
- [ ] Restart backend: `docker compose --profile aws restart backend-aws`
- [ ] OR full restart: `docker compose --profile aws up -d db backend-aws frontend-aws`

### Step 6: Verify Connection
- [ ] Check outbound IP from backend:
  ```bash
  docker compose --profile aws exec backend-aws python -c "import requests; print(requests.get('https://api.ipify.org').text)"
  ```
  Should show Elastic IP, not VPN IP

- [ ] Test Crypto.com connection:
  ```bash
  docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py
  ```

- [ ] Check backend logs:
  ```bash
  docker compose --profile aws logs backend-aws --tail=50
  ```

### Step 7: Verify Trading Works
- [ ] Check dashboard shows real balances
- [ ] Test a small trade (if applicable)
- [ ] Monitor logs for any errors

## Key Configuration Details

### Environment Variables (.env.aws)
```bash
# Direct connection (no proxy, no VPN)
USE_CRYPTO_PROXY=false
LIVE_TRADING=true

# Crypto.com API credentials
EXCHANGE_CUSTOM_API_KEY=your_api_key_here
EXCHANGE_CUSTOM_API_SECRET=your_api_secret_here
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
CRYPTO_REST_BASE=https://api.crypto.com/exchange/v1
```

### Docker Compose (backend-aws service)
```yaml
backend-aws:
  # ... other config ...
  depends_on:
    db:
      condition: service_healthy
    # gluetun dependency removed
```

## Important Notes

1. **Backend doesn't actually route through VPN currently** - The `backend-aws` container doesn't have `network_mode: "service:gluetun"`, so it's already on the bridge network. The gluetun dependency is just for startup ordering.

2. **Elastic IP is free** while EC2 instance is running. If you stop the instance, you'll pay ~$0.005/hour for unassociated Elastic IP.

3. **You can keep gluetun running** for other services if needed, just remove the dependency from backend-aws.

4. **The proxy (`USE_CRYPTO_PROXY=true`)** was pointing to `host.docker.internal:9000`, which may not be running. Setting it to `false` makes direct connection.

## Troubleshooting

### Error: "IP illegal (40103)" from Crypto.com
- Verify Elastic IP is whitelisted in Crypto.com
- Check that backend is using Elastic IP (not VPN IP)
- Verify `USE_CRYPTO_PROXY=false` is set

### Backend still using VPN IP
- Check `USE_CRYPTO_PROXY=false` in `.env.aws`
- Verify `docker-compose.yml` doesn't have gluetun dependency
- Restart backend: `docker compose --profile aws restart backend-aws`

### Backend won't start
- Check if gluetun is still required by other services
- Verify db is healthy: `docker compose --profile aws ps db`
- Check logs: `docker compose --profile aws logs backend-aws`

## Files Reference

- Main guide: `SKIP_VPN_DEDICATED_IP.md`
- Detailed setup: `docs/AWS_ELASTIC_IP_SETUP.md`
- Configuration: `docs/CONFIGURE_DIRECT_CONNECTION.md`
- Script: `scripts/setup_aws_elastic_ip.sh`
- Docker config: `docker-compose.yml` (line ~144-207 for backend-aws)
- Environment: `.env.aws`

## Success Criteria

✅ Elastic IP allocated and associated to EC2 instance  
✅ Elastic IP whitelisted in Crypto.com Exchange  
✅ `.env.aws` has `USE_CRYPTO_PROXY=false`  
✅ `docker-compose.yml` backend-aws doesn't depend on gluetun  
✅ Backend restarted and running  
✅ Backend shows Elastic IP when checking outbound IP  
✅ Crypto.com API connection works  
✅ Trading platform functions normally  

## Next Steps After Migration

1. Test thoroughly for a few days
2. Cancel NordVPN dedicated IP subscription (if no longer needed)
3. Monitor for any connection issues
4. Consider removing gluetun container entirely if not used by other services

---

**Please help me execute this migration step by step, checking each step before proceeding to the next.**

