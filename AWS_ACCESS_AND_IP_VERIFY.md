# AWS Backend Access & IP Verification Guide

## Overview

This guide helps you:
1. ✅ Verify outbound IP used by EC2 backend (for Crypto.com whitelist)
2. ✅ Enable safe inbound access to backend health endpoint from your Mac
3. ✅ Confirm outbound IP remains unchanged (Crypto.com API continues working)

**Key Principle**: All changes are **inbound-only**. Outbound traffic from EC2 to Crypto.com remains unchanged.

---

## A) Proving Execution Context (Mac vs EC2)

### Why This Matters

When you run `docker compose --profile aws ps` on your Mac, you're seeing **local containers**, not EC2 containers. This proves you're on Mac, not EC2.

### Verify Context on Mac

Run this script on your Mac:

```bash
cd ~/automated-trading-platform
./scripts/verify_local_vs_ec2.sh
```

**Expected Output**:
- Shows Mac hostname, OS, user
- Shows Mac public IP (e.g., `185.250.39.133`)
- Shows local Docker containers (if any)
- **Proves**: Commands are running on Mac, NOT on EC2
- External health check will timeout (expected until Security Group is configured)

---

## B) Verify EC2 Outbound IP (Source of Truth)

### Access EC2 via AWS SSM Session Manager

1. Go to AWS Console → EC2 → Instances
2. Find your instance (e.g., `i-08726dc37133b2454`)
3. Click "Connect" → "Session Manager" → "Connect"

### Run Verification Script on EC2

Once connected via SSM, run:

```bash
cd ~/automated-trading-platform
./scripts/verify_ec2_ip_and_health.sh
```

**This script will**:
- ✅ Show EC2 host outbound IP
- ✅ Show backend container outbound IP
- ✅ Compare them (should match)
- ✅ Verify backend health on localhost
- ✅ Show container status
- ✅ Display EC2 public IP

**Expected Results**:
- Host IP == Container IP (both show AWS Elastic IP, e.g., `47.130.143.159` or current EIP)
- Backend health returns HTTP 200
- **Crypto.com whitelist should use the EC2 host outbound IP**

---

## C) Understanding the Real Issue

### Why External Tests Timeout

When you run `curl http://54.254.150.31:8002/api/health` from your Mac and it times out, **the backend is NOT down**. The issue is:

1. ✅ **Backend IS running** (confirmed by `docker compose --profile aws ps` on EC2)
2. ✅ **Backend IS listening** on port 8002 (confirmed by localhost health check)
3. ❌ **Security Group blocks inbound traffic** from your Mac's IP

### The Fix

We need to add **inbound Security Group rules** that allow:
- Port 8002 (backend API) from your Mac's IP only
- Port 3000 (frontend, optional) from your Mac's IP only

**This change is SAFE** because:
- ✅ Only affects **inbound** traffic
- ✅ Outbound traffic unchanged (backend still uses EC2 IP for Crypto.com)
- ✅ Restricted to your IP only (not open to the world)
- ✅ Does not modify container networking or docker-compose.yml

---

## D) Safe Inbound Access Setup

### Method 1: AWS Console Only (Recommended) ⭐

**No AWS CLI required** - works from any browser.

#### Step 1: Get Your Mac's Public IP

Run on your Mac:
```bash
curl -s https://api.ipify.org
```

Or check the output from `./scripts/verify_local_vs_ec2.sh`

**Example**: `185.250.39.133`

#### Step 2: Open AWS Console

1. Go to AWS Console → EC2 → Instances
2. Find your instance (e.g., `i-08726dc37133b2454`)
3. Click on the instance name
4. Open the "Security" tab
5. Click on the Security Group link (opens in new tab)

#### Step 3: Edit Inbound Rules

1. In the Security Group page, click "Edit inbound rules"
2. Click "Add rule"
3. Add rule for Backend API:
   - **Type**: Custom TCP
   - **Port range**: `8002`
   - **Source**: `<YOUR_MAC_IP>/32` (e.g., `185.250.39.133/32`)
   - **Description**: `Carlos health check - backend API`
4. (Optional) Add rule for Frontend:
   - **Type**: Custom TCP
   - **Port range**: `3000`
   - **Source**: `<YOUR_MAC_IP>/32`
   - **Description**: `Carlos health check - frontend`
5. Click "Save rules"

#### Step 4: Verify Rules

After saving, confirm:
- ✅ Port 8002 allows only `<YOUR_MAC_IP>/32`
- ✅ Port 3000 allows only `<YOUR_MAC_IP>/32` (if added)
- ✅ All other ports remain closed (or restricted as before)
- ✅ SSH (port 22) is NOT open to 0.0.0.0/0 (security best practice)

---

### Method 2: AWS CLI (Only if Configured)

**⚠️ Only use if AWS CLI is configured on your Mac**

#### Prerequisite Check

First, verify AWS CLI works:

```bash
aws sts get-caller-identity
```

If this fails, use **Method 1 (AWS Console)** instead.

#### Step 1: Get Your Mac's Public IP

```bash
MY_IP=$(curl -s https://api.ipify.org)
echo "Your Mac IP: $MY_IP"
```

#### Step 2: Get Security Group ID

```bash
INSTANCE_ID="i-08726dc37133b2454"  # Replace with your instance ID
REGION="ap-southeast-1"  # Replace with your region if different

SG_ID=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' \
  --output text)

echo "Security Group ID: $SG_ID"
```

#### Step 3: Check if Rules Already Exist

```bash
# Check port 8002
aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region "$REGION" \
  --query "SecurityGroups[0].IpPermissions[?FromPort==\`8002\` && ToPort==\`8002\` && IpProtocol==\`tcp\` && IpRanges[?CidrIp==\`$MY_IP/32\`]]" \
  --output json | jq -r 'length'

# If output is 0, rule doesn't exist. If 1, rule already exists.
```

#### Step 4: Add Rules (if not already present)

```bash
# Add rule for port 8002
aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --protocol tcp \
  --port 8002 \
  --cidr "$MY_IP/32" \
  --region "$REGION" \
  --description "Carlos health check - backend API"

# Add rule for port 3000 (optional)
aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --protocol tcp \
  --port 3000 \
  --cidr "$MY_IP/32" \
  --region "$REGION" \
  --description "Carlos health check - frontend"
```

**Note**: If rules already exist, AWS will return an error. This is safe - it means rules are already configured.

#### Step 5: Verify Rules

```bash
aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region "$REGION" \
  --query 'SecurityGroups[0].IpPermissions[?FromPort==`8002` || FromPort==`3000`].[IpProtocol,FromPort,ToPort,IpRanges[*].CidrIp]' \
  --output table
```

---

## E) Verification Steps

### After Adding Security Group Rules

#### 1. Test External Access from Mac

```bash
# Get EC2 public IP (from EC2 metadata or AWS Console)
EC2_PUBLIC_IP="54.254.150.31"  # Replace with actual IP

# Test backend health
curl -m 5 -v http://$EC2_PUBLIC_IP:8002/api/health
```

**Expected Result**: HTTP 200 OK with JSON response

**If it still fails**:
- Wait 30 seconds (Security Group changes can take a moment to propagate)
- Verify your Mac's IP hasn't changed: `curl -s https://api.ipify.org`
- Check Security Group rules in AWS Console
- Verify EC2 instance is running

#### 2. Verify Backend Still Works on EC2 (Localhost)

On EC2 via SSM:

```bash
curl -m 5 -v http://localhost:8002/api/health
```

**Expected Result**: HTTP 200 OK (should always work, regardless of Security Group)

#### 3. Verify Outbound IP Unchanged

On EC2 via SSM:

```bash
curl -s https://api.ipify.org
```

**Expected Result**: Same IP as before (e.g., `47.130.143.159` or current EIP)

**Verify Crypto.com API still works** (if you have test credentials):

```bash
# On EC2
docker compose --profile aws exec -T backend-aws python3 -c "
import requests
try:
    r = requests.get('https://api.crypto.com/exchange/v1/public/get-tickers?instrument_name=BTC_USDT', timeout=5)
    print(f'Crypto.com API: {r.status_code}')
except Exception as e:
    print(f'Crypto.com API error: {e}')
"
```

---

## F) Verification Report Template

Fill in this report after completing all steps:

```markdown
## Verification Report

**Date**: <FILL_IN>

### Execution Context
- ✅ Mac vs EC2 verified: <YES/NO>
- Mac Public IP: <FILL_IN>
- Mac hostname: <FILL_IN>

### EC2 Outbound IP (Source of Truth)
- EC2 Host Outbound IP: <FILL_IN>
- Backend Container Outbound IP: <FILL_IN>
- IPs Match: <YES/NO>
- **Crypto.com Whitelist IP**: <FILL_IN> (use this!)

### Backend Health Status
- Backend localhost health (on EC2): <HTTP_STATUS_CODE>
- External health from Mac (before SG fix): <TIMEOUT/REFUSED/ERROR>
- External health from Mac (after SG fix): <HTTP_STATUS_CODE>
- Backend response sample: <FILL_IN>

### Security Group Configuration
- Security Group ID: <FILL_IN>
- Region: <FILL_IN>
- Inbound rules added:
  - Port 8002: <YOUR_IP>/32 ✅
  - Port 3000: <YOUR_IP>/32 ✅ (if added)
- Method used: <AWS Console / AWS CLI>

### Outbound Verification
- Outbound IP unchanged: <YES/NO>
- Crypto.com API working: <YES/NO/UNTESTED>
- Notes: <FILL_IN>

### Remaining Blockers
- <NONE / List any issues>

### Summary
✅ Outbound IP confirmed: <EC2_HOST_IP>
✅ Security Group configured: Ports 8002/3000 restricted to <MY_IP>/32
✅ External access working: Backend health endpoint accessible from Mac
✅ Outbound unchanged: Crypto.com API still uses EC2 IP
```

---

## Troubleshooting

### External Access Still Fails After Security Group Fix

1. **Wait 30 seconds**: Security Group changes can take time to propagate

2. **Verify your IP hasn't changed**:
   ```bash
   curl -s https://api.ipify.org
   ```
   If it changed, update Security Group rules with new IP

3. **Check Security Group rules in AWS Console**:
   - Verify rules exist for ports 8002/3000
   - Verify source is `<YOUR_IP>/32` (not `/0`)
   - Verify protocol is TCP

4. **Check EC2 instance status**:
   - Instance should be "running"
   - No system status checks failing

5. **Check container status** (on EC2 via SSM):
   ```bash
   docker compose --profile aws ps
   ```
   Backend should be "Up" and "healthy"

6. **Check EC2 instance firewall** (if enabled):
   ```bash
   # On EC2
   sudo ufw status
   sudo iptables -L -n | grep 8002
   ```

### Outbound IP Changed (Should NOT Happen)

If outbound IP changed after Security Group changes:

1. **This should NOT happen** - Security Group changes are inbound-only
2. Check if docker-compose.yml was modified
3. Check if container network_mode was changed
4. Verify no VPN/proxy was added
5. Contact AWS support if issue persists

---

## Important Notes

### ✅ Safe Operations
- Adding Security Group inbound rules (restricted to your IP)
- Testing external access
- Verifying outbound IP
- Checking backend health

### ❌ Do NOT
- Change docker-compose.yml networking
- Modify container network_mode
- Add VPN/proxy for outbound traffic
- Open ports to 0.0.0.0/0
- Change outbound routing configuration

### 🔒 Security Best Practices
- ✅ Restrict inbound rules to your IP only (`/32`)
- ✅ Use Security Group descriptions for documentation
- ✅ Do not open SSH (port 22) to 0.0.0.0/0
- ✅ Regularly review Security Group rules
- ✅ Remove rules when no longer needed

---

## Quick Reference

### Scripts
- `scripts/verify_local_vs_ec2.sh` - Run on Mac to verify context
- `scripts/verify_ec2_ip_and_health.sh` - Run on EC2 via SSM to verify IPs and health

### Key Commands
```bash
# Get Mac IP
curl -s https://api.ipify.org

# Get EC2 IP (on EC2)
curl -s https://api.ipify.org

# Test external health (from Mac)
curl -m 5 -v http://<EC2_PUBLIC_IP>:8002/api/health

# Test local health (on EC2)
curl -m 5 -v http://localhost:8002/api/health
```

### AWS Resources
- EC2 Instance ID: `i-08726dc37133b2454` (example - verify yours)
- Region: `ap-southeast-1` (example - verify yours)
- Security Group: Check in AWS Console → EC2 → Instances → Your Instance → Security tab

---

## Summary

✅ **Outbound IP**: Verified via `scripts/verify_ec2_ip_and_health.sh` on EC2  
✅ **Inbound Access**: Configured via AWS Console or AWS CLI (Method 1 or 2)  
✅ **Safety**: Only inbound rules changed, outbound unchanged  
✅ **Security**: Restricted to your IP only (`/32`)  
✅ **Verification**: Test external health endpoint from Mac  

**Result**: You can now verify backend health from your Mac without affecting Crypto.com IP whitelist.



