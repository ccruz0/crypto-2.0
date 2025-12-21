# Skip NordVPN Dedicated IP - Use AWS Elastic IP Instead

## Answer: Yes, you can skip the NordVPN dedicated IP!

You can use **AWS Elastic IP** instead, which is:
- ✅ **Free** while your EC2 instance is running
- ✅ **Fixed IP** that persists across restarts
- ✅ **Simpler** architecture (direct connection, no VPN)

## Quick Answer

**Do you still need a fixed IP in VPN when running from AWS?**
- **No!** You can use AWS Elastic IP instead.

**Can you create a fixed IP in AWS?**
- **Yes!** AWS Elastic IP is exactly what you need.

## Cost Comparison

| Solution | Cost |
|----------|------|
| NordVPN Dedicated IP | ~$70/year |
| AWS Elastic IP | Free (while instance running) |

## How It Works

### Current Setup (with VPN)
```
Your Backend → NordVPN (Dedicated IP) → Crypto.com API
             (Crypto.com sees VPN IP)
```

### New Setup (with Elastic IP)
```
Your Backend → AWS Elastic IP → Crypto.com API
             (Crypto.com sees Elastic IP)
```

## Setup Steps

### 1. Allocate AWS Elastic IP

**Option A: Use the automated script:**
```bash
./scripts/setup_aws_elastic_ip.sh
```

**Option B: Manual via AWS Console:**
1. EC2 Console → Elastic IPs
2. Allocate Elastic IP address
3. Associate it to your EC2 instance

**Option C: AWS CLI:**
```bash
# Allocate
ALLOCATION_ID=$(aws ec2 allocate-address --domain vpc --query 'AllocationId' --output text)

# Associate (replace INSTANCE_ID)
aws ec2 associate-address --instance-id i-xxxxx --allocation-id $ALLOCATION_ID

# Get the IP
aws ec2 describe-addresses --allocation-ids $ALLOCATION_ID --query 'Addresses[0].PublicIp' --output text
```

### 2. Whitelist Elastic IP in Crypto.com

1. Go to https://exchange.crypto.com/
2. Settings → **API Keys**
3. Edit your API Key
4. Add your Elastic IP to the whitelist
5. Save

### 3. Configure Backend for Direct Connection

Update `.env.aws`:
```bash
USE_CRYPTO_PROXY=false
LIVE_TRADING=true
```

### 4. Make VPN Optional (Recommended)

Edit `docker-compose.yml`, in the `backend-aws` section, remove the gluetun dependency:

**Change this:**
```yaml
depends_on:
  gluetun:
    condition: service_healthy
  db:
    condition: service_healthy
```

**To this:**
```yaml
depends_on:
  db:
    condition: service_healthy
```

### 5. Deploy

```bash
ssh ubuntu@your-aws-instance "cd automated-trading-platform && docker compose --profile aws restart backend-aws"
```

### 6. Verify

```bash
# Check what IP Crypto.com sees
ssh ubuntu@your-aws-instance "docker compose --profile aws exec backend-aws python -c 'import requests; print(requests.get(\"https://api.ipify.org\").text)'"

# Should show your Elastic IP, not VPN IP
```

## Documentation

- **Full setup guide**: `docs/AWS_ELASTIC_IP_SETUP.md`
- **Configuration guide**: `docs/CONFIGURE_DIRECT_CONNECTION.md`
- **Automated script**: `scripts/setup_aws_elastic_ip.sh`

## Important Notes

1. **Elastic IP is free** while your EC2 instance is running
2. If you stop the instance, you'll pay ~$0.005/hour (~$3.65/month) for the unassociated Elastic IP
3. The backend doesn't actually route through VPN currently (no `network_mode: "service:gluetun"`), so this change is mainly about removing the dependency and ensuring direct connection
4. You can cancel your NordVPN dedicated IP subscription after this is working

## Troubleshooting

**Backend still using VPN IP?**
- Check `USE_CRYPTO_PROXY=false` in `.env.aws`
- Verify backend-aws doesn't have `network_mode: "service:gluetun"`
- Restart backend: `docker compose --profile aws restart backend-aws`

**Crypto.com rejects connection?**
- Verify Elastic IP is whitelisted in Crypto.com
- Check IP matches: `curl https://api.ipify.org` from backend container

## Summary

✅ **Yes, you can skip NordVPN dedicated IP**  
✅ **Yes, AWS Elastic IP works perfectly**  
✅ **It's free while your instance is running**  
✅ **Much simpler architecture**  

Just allocate an Elastic IP, whitelist it in Crypto.com, set `USE_CRYPTO_PROXY=false`, and you're done!

