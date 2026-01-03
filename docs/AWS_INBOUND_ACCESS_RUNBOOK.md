# AWS Inbound Access Runbook

## Overview

This runbook explains how to enable safe inbound access to the EC2 backend and frontend from your Mac, **without affecting the outbound IP used for Crypto.com API calls**.

**Key Principle**: Inbound Security Group changes do **NOT** change outbound IP. The backend will continue using the same EC2 public IP (`47.130.143.159` or current EIP) for Crypto.com API calls.

---

## Prerequisites

1. ✅ EC2 instance is running
2. ✅ Backend is healthy (verified via `./scripts/verify_ec2_ip_and_health.sh` on EC2)
3. ✅ You know your Mac's public IP (run `curl -s https://api.ipify.org` on Mac)
4. ✅ You know the EC2 public IP (from verification script output)

---

## Step 1: Get Your Mac's Public IP

On your Mac, run:

```bash
curl -s https://api.ipify.org
```

Or use the verification script:

```bash
./scripts/verify_local_vs_ec2.sh
```

**Example output**: `185.250.39.133`

**Important**: If your IP changes (e.g., you connect to a different network), you'll need to update the Security Group rules.

---

## Step 2: Add Security Group Inbound Rules

### Via AWS Console (Recommended)

1. **Open AWS Console**
   - Go to https://console.aws.amazon.com
   - Services → Compute → EC2 → Instances

2. **Select Your Instance**
   - Find instance ID: `i-08726dc37133b2454` (or your instance ID)
   - Click on the instance name

3. **Open Security Tab**
   - Click on the "Security" tab (bottom panel)
   - Click on the Security Group link (opens in new tab)

4. **Edit Inbound Rules**
   - Click "Edit inbound rules"
   - Click "Add rule"
   - Configure Backend API access:
     - **Type**: Custom TCP
     - **Port range**: `8002`
     - **Source**: `<YOUR_MAC_IP>/32` (e.g., `185.250.39.133/32`)
     - **Description**: `Backend API access from my IP only`
   - Click "Add rule" again for Frontend (optional):
     - **Type**: Custom TCP
     - **Port range**: `3000`
     - **Source**: `<YOUR_MAC_IP>/32`
     - **Description**: `Frontend access from my IP only`
   - Click "Save rules"

5. **Verify Rules**
   - Confirm port 8002 allows only `<YOUR_MAC_IP>/32`
   - Confirm port 3000 allows only `<YOUR_MAC_IP>/32` (if added)
   - All other ports remain closed or restricted as before
   - SSH (port 22) is NOT open to 0.0.0.0/0

### Via AWS CLI (Optional)

**⚠️ Only if AWS CLI is configured: `aws sts get-caller-identity`**

```bash
INSTANCE_ID="i-08726dc37133b2454"  # Replace with your instance ID
REGION="ap-southeast-1"  # Replace with your region
MY_IP="185.250.39.133"  # Replace with your Mac's public IP

# Get Security Group ID
SG_ID=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' \
  --output text)

# Add rule for port 8002
aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --protocol tcp \
  --port 8002 \
  --cidr "$MY_IP/32" \
  --region "$REGION" \
  --description "Backend API access from my IP only"

# Add rule for port 3000 (optional)
aws ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --protocol tcp \
  --port 3000 \
  --cidr "$MY_IP/32" \
  --region "$REGION" \
  --description "Frontend access from my IP only"
```

---

## Step 3: Verify Inbound Access from Mac

After adding Security Group rules, wait 30 seconds for changes to propagate, then test from your Mac:

```bash
# Get EC2 public IP (from verification script output on EC2)
EC2_IP="54.254.150.31"  # Replace with actual EC2 public IP

# Test using the verification script
./scripts/verify_inbound_access_from_mac.sh "$EC2_IP"

# Or test manually
curl -m 5 -v http://$EC2_IP:8002/api/health
curl -m 5 -v http://$EC2_IP:3000/
```

**Expected Result**: HTTP 200 OK with JSON health response for backend, HTML for frontend.

---

## Step 4: Verify Outbound IP Unchanged

**Important**: Verify that outbound IP remains unchanged after adding inbound rules.

On EC2 (via SSM Session Manager):

```bash
# Verify outbound IP (should still be the same)
curl -s https://api.ipify.org

# Should show: 47.130.143.159 (or your current EIP)
# This IP is still used for Crypto.com API calls
```

**Why Outbound IP Doesn't Change:**
- Security Group inbound rules only affect **incoming** traffic
- Outbound traffic uses the EC2 instance's public IP (unchanged)
- Container networking is not modified
- Crypto.com whitelist continues to work with the same IP

---

## Troubleshooting

### External Access Still Times Out

**Symptoms**: `curl http://<EC2_IP>:8002/api/health` from Mac still times out after adding Security Group rules.

**Diagnostic Steps:**

1. **Wait 30-60 seconds**
   - Security Group changes can take time to propagate

2. **Verify your Mac's IP hasn't changed**
   ```bash
   curl -s https://api.ipify.org
   ```
   If it changed, update Security Group rules with new IP

3. **Check Security Group rules in AWS Console**
   - Verify rules exist for ports 8002/3000
   - Verify source is `<YOUR_IP>/32` (not `/0` or other)
   - Verify protocol is TCP

4. **Check Network ACL (NACL) rules**
   - Subnet-level rules may be blocking inbound traffic
   - Check NACL inbound rules for your subnet
   - Ensure rules allow TCP ports 8002/3000 from 0.0.0.0/0 (NACL allows/denies at subnet level)

5. **Verify EC2 instance status**
   - Instance should be "running"
   - No system status checks failing

6. **Check container status on EC2**
   ```bash
   # On EC2 via SSM
   docker compose --profile aws ps
   ```
   Backend should be "Up" and "healthy"

7. **Verify instance has public IPv4**
   - Check in AWS Console: EC2 → Instances → Your Instance → Details tab
   - Verify "Public IPv4 address" is set

8. **Check route table**
   - Verify subnet has route to Internet Gateway (IGW)
   - Check: EC2 → Route Tables → Your Subnet's Route Table
   - Should have: `0.0.0.0/0 -> igw-xxxxx`

### AWS CLI Diagnostic Commands

**⚠️ Only if AWS CLI is configured**

```bash
INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"
MY_IP="185.250.39.133"

# Get Security Group ID
SG_ID=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' \
  --output text)

# Check Security Group inbound rules
aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region "$REGION" \
  --query 'SecurityGroups[0].IpPermissions[?FromPort==`8002` || FromPort==`3000`]' \
  --output table

# Get subnet ID
SUBNET_ID=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Reservations[0].Instances[0].SubnetId' \
  --output text)

# Check Network ACL rules
aws ec2 describe-network-acls \
  --filters "Name=association.subnet-id,Values=$SUBNET_ID" \
  --region "$REGION" \
  --query 'NetworkAcls[0].Entries[?PortRange.From<=`8002` && PortRange.To>=`8002`]' \
  --output table

# Check instance public IP
aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Reservations[0].Instances[0].[PublicIpAddress,PublicDnsName]' \
  --output table

# Check route table
ROUTE_TABLE_ID=$(aws ec2 describe-route-tables \
  --filters "Name=association.subnet-id,Values=$SUBNET_ID" \
  --region "$REGION" \
  --query 'RouteTables[0].RouteTableId' \
  --output text)

aws ec2 describe-route-tables \
  --route-table-ids "$ROUTE_TABLE_ID" \
  --region "$REGION" \
  --query 'RouteTables[0].Routes[?GatewayId!=`null`]' \
  --output table
```

---

## Security Best Practices

✅ **Do:**
- Restrict inbound rules to your IP only (`/32`)
- Use Security Group descriptions for documentation
- Regularly review Security Group rules
- Remove rules when no longer needed
- Monitor Security Group changes in CloudTrail

❌ **Do NOT:**
- Open ports to `0.0.0.0/0` (any IP)
- Open SSH (port 22) to `0.0.0.0/0`
- Commit `.env.aws` with real secrets
- Change docker-compose networking
- Modify container network_mode

---

## Alternative: Cloudflare Tunnel (No Inbound Ports)

If you want to avoid opening any inbound ports:

1. Install cloudflared on EC2
2. Create tunnels for backend (port 8002) and frontend (port 3000)
3. Access via Cloudflare-provided URLs
4. No Security Group changes needed

**Note**: Cloudflare Tunnel does NOT change outbound IP. Backend still uses EC2 IP for Crypto.com API calls.

See `OUTBOUND_IP_REPORT.md` for detailed Cloudflare Tunnel setup.

---

## Summary

✅ **Inbound Access**: Configured via Security Group rules (restricted to your IP only)  
✅ **Outbound IP**: Unchanged (still uses EC2 public IP for Crypto.com API)  
✅ **Security**: Restricted to `/32` CIDR (your IP only)  
✅ **Crypto.com Whitelist**: Continues to use EC2 outbound IP (`47.130.143.159` or current EIP)  

**Result**: You can verify backend health from your Mac without affecting Crypto.com IP whitelist.

