# Configure Direct Connection (Skip VPN)

This guide shows how to configure the backend to connect directly to Crypto.com using AWS Elastic IP, bypassing VPN.

## Quick Setup

### Option 1: Simple - Just Update Environment Variables

If you want to keep the current docker-compose setup but bypass VPN:

1. **Update `.env.aws`**:
   ```bash
   USE_CRYPTO_PROXY=false
   LIVE_TRADING=true
   ```

2. **Remove gluetun dependency** (optional, but recommended):
   
   Edit `docker-compose.yml`, find `backend-aws` section (around line 201), and change:
   ```yaml
   depends_on:
     gluetun:
       condition: service_healthy
     db:
       condition: service_healthy
   ```
   
   To:
   ```yaml
   depends_on:
     db:
       condition: service_healthy
   ```

3. **Restart backend**:
   ```bash
   ssh ubuntu@your-aws-instance "cd automated-trading-platform && docker compose --profile aws restart backend-aws"
   ```

### Option 2: Complete Setup with Elastic IP

1. **Allocate Elastic IP** (see `docs/AWS_ELASTIC_IP_SETUP.md` or run):
   ```bash
   ./scripts/setup_aws_elastic_ip.sh
   ```

2. **Whitelist Elastic IP in Crypto.com**:
   - Go to https://exchange.crypto.com/
   - Settings → API Keys
   - Edit your API Key
   - Add your Elastic IP

3. **Update `.env.aws`**:
   ```bash
   USE_CRYPTO_PROXY=false
   LIVE_TRADING=true
   EXCHANGE_CUSTOM_API_KEY=your_key
   EXCHANGE_CUSTOM_API_SECRET=your_secret
   ```

4. **Update `docker-compose.yml`** to remove gluetun dependency (see Option 1)

5. **Deploy**:
   ```bash
   ssh ubuntu@your-aws-instance "cd automated-trading-platform && docker compose --profile aws up -d db backend-aws frontend-aws"
   ```

## Verify Direct Connection

Check that backend is using your Elastic IP (not VPN IP):

```bash
# From AWS instance
ssh ubuntu@your-aws-instance

# Check what IP Crypto.com sees
docker compose --profile aws exec backend-aws python -c "
import requests
print('Outbound IP:', requests.get('https://api.ipify.org').text)
"
```

This should show your Elastic IP, not a VPN IP.

## Current Architecture

**Before (with VPN):**
```
Backend → Gluetun (VPN) → NordVPN Server → Crypto.com API
         (Sees VPN IP)
```

**After (direct):**
```
Backend → AWS Elastic IP → Crypto.com API
         (Sees Elastic IP)
```

## Benefits

✅ **Cost Savings**: No NordVPN dedicated IP subscription  
✅ **Lower Latency**: Direct connection, no VPN overhead  
✅ **Simpler**: Fewer moving parts  
✅ **Fixed IP**: Elastic IP persists across restarts  

## Notes

- The backend-aws container doesn't use `network_mode: "service:gluetun"`, so it's already on the bridge network
- Setting `USE_CRYPTO_PROXY=false` makes it connect directly to Crypto.com
- The gluetun dependency is just for startup ordering, not actual routing
- You can keep gluetun running for other services if needed, just remove the dependency from backend-aws

