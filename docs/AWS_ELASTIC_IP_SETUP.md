# AWS Elastic IP Setup - Skip NordVPN Dedicated IP

This guide shows how to use AWS Elastic IP instead of NordVPN dedicated IP, saving you money on VPN subscription.

## Overview

**Current Setup:**
- Backend uses VPN (NordVPN via Gluetun) for outbound traffic
- Requires NordVPN dedicated IP subscription

**New Setup:**
- Backend connects directly to Crypto.com from AWS
- Uses AWS Elastic IP (free while instance is running)
- Whitelist the Elastic IP in Crypto.com

## Cost Comparison

- **NordVPN Dedicated IP**: ~$70/year (varies by plan)
- **AWS Elastic IP**: Free while EC2 instance is running, ~$0.005/hour (~$3.65/month) if instance is stopped

## Step 1: Allocate AWS Elastic IP

### Via AWS Console

1. Go to **EC2 Console** → **Elastic IPs**
2. Click **Allocate Elastic IP address**
3. Choose **Amazon's pool of IPv4 addresses**
4. Click **Allocate**
5. Select the Elastic IP and click **Actions** → **Associate Elastic IP address**
6. Select your EC2 instance
7. Click **Associate**

### Via AWS CLI

```bash
# Allocate Elastic IP
ALLOCATION_ID=$(aws ec2 allocate-address --domain vpc --query 'AllocationId' --output text)
echo "Allocation ID: $ALLOCATION_ID"

# Get your instance ID
INSTANCE_ID=$(aws ec2 describe-instances \
  --filters "Name=tag:Name,Values=your-instance-name" \
  --query 'Reservations[0].Instances[0].InstanceId' \
  --output text)
echo "Instance ID: $INSTANCE_ID"

# Associate Elastic IP to instance
aws ec2 associate-address \
  --instance-id $INSTANCE_ID \
  --allocation-id $ALLOCATION_ID

# Get the Elastic IP address
ELASTIC_IP=$(aws ec2 describe-addresses \
  --allocation-ids $ALLOCATION_ID \
  --query 'Addresses[0].PublicIp' \
  --output text)
echo "Elastic IP: $ELASTIC_IP"
```

## Step 2: Verify Your Elastic IP

From your AWS instance, check the public IP:

```bash
# SSH into your AWS instance
ssh ubuntu@your-aws-instance

# Check public IP (should match your Elastic IP)
curl https://api.ipify.org
```

## Step 3: Whitelist Elastic IP in Crypto.com

1. Go to https://exchange.crypto.com/
2. Settings → **API Keys**
3. Edit your API Key
4. Add your Elastic IP to the whitelist
5. Save

## Step 4: Configure Backend to Connect Directly

Update your `.env.aws` file:

```bash
# Disable VPN/proxy for Crypto.com
USE_CRYPTO_PROXY=false
LIVE_TRADING=true

# Direct connection to Crypto.com
EXCHANGE_CUSTOM_BASE_URL=https://api.crypto.com/exchange/v1
CRYPTO_REST_BASE=https://api.crypto.com/exchange/v1

# Your API credentials (already configured)
EXCHANGE_CUSTOM_API_KEY=your_api_key
EXCHANGE_CUSTOM_API_SECRET=your_api_secret
```

## Step 5: Make VPN Optional (Optional)

If you want to keep VPN for other purposes but not for Crypto.com:

1. Update `docker-compose.yml` to make gluetun optional
2. Remove `depends_on: gluetun` from `backend-aws`
3. Or keep VPN but ensure backend doesn't route through it

## Step 6: Deploy Changes

```bash
# Restart backend to apply new configuration
ssh ubuntu@your-aws-instance "cd automated-trading-platform && docker compose --profile aws restart backend-aws"

# Or if you want to remove VPN dependency entirely:
ssh ubuntu@your-aws-instance "cd automated-trading-platform && docker compose --profile aws up -d db backend-aws frontend-aws"
```

## Step 7: Verify Connection

```bash
# Test from AWS instance
ssh ubuntu@your-aws-instance "docker compose --profile aws exec backend-aws python -c \"import requests; print(requests.get('https://api.ipify.org').text)\""

# Should show your Elastic IP

# Test Crypto.com connection
ssh ubuntu@your-aws-instance "docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py"
```

## Troubleshooting

### Error: "IP illegal (40103)"
- Verify Elastic IP is whitelisted in Crypto.com
- Check that backend is using direct connection (not VPN)
- Verify Elastic IP is associated to your instance

### Error: "Authentication failed (40101)"
- Check API credentials are correct
- Verify IP whitelist includes your Elastic IP
- Ensure `USE_CRYPTO_PROXY=false` is set

### Backend still using VPN IP
- Check `docker-compose.yml` - backend-aws should NOT have `network_mode: "service:gluetun"`
- Verify `USE_CRYPTO_PROXY=false` in `.env.aws`
- Restart backend: `docker compose --profile aws restart backend-aws`

## Benefits

✅ **Cost Savings**: No need for NordVPN dedicated IP subscription  
✅ **Simpler Architecture**: Direct connection, fewer moving parts  
✅ **Better Performance**: No VPN overhead  
✅ **Fixed IP**: Elastic IP stays with your instance  

## Notes

- Elastic IP is free while your EC2 instance is running
- If you stop/terminate the instance, you'll pay ~$0.005/hour for the unassociated Elastic IP
- You can release the Elastic IP if you no longer need it
- The Elastic IP persists across instance restarts

