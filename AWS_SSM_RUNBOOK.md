# AWS SSM Session Manager Runbook

## Overview

This runbook guides you through connecting to your EC2 instance via AWS Systems Manager (SSM) Session Manager to verify backend configuration and outbound IPs. SSM Session Manager does not require SSH access (port 22) and works through the AWS Console.

**Why SSM Session Manager?**
- ✅ No SSH key management required
- ✅ Works even if SSH (port 22) is blocked
- ✅ Secure access through AWS Console
- ✅ Session logs available in CloudWatch

---

## Step 1: Connect to EC2 via SSM Session Manager

### Via AWS Console

1. **Open AWS Console**
   - Go to https://console.aws.amazon.com
   - Sign in to your AWS account

2. **Navigate to EC2**
   - Services → Compute → EC2
   - Click "Instances" in the left sidebar

3. **Find Your Instance**
   - Look for instance ID: `i-08726dc37133b2454` (or your instance ID)
   - Verify instance state is "Running"

4. **Connect via Session Manager**
   - Select your instance (check the checkbox)
   - Click "Connect" button (top of the page)
   - In the "Connect to instance" dialog, select tab: **"Session Manager"**
   - Click **"Connect"**

5. **Terminal Opens**
   - A new browser tab/window opens with a terminal
   - You're now connected to the EC2 instance
   - You should see a Linux prompt (e.g., `ubuntu@ip-xxx-xx-xx-xx:~$`)

---

## Step 2: Navigate to Project Directory

In the SSM Session Manager terminal, run:

```bash
cd ~/automated-trading-platform
```

If that directory doesn't exist, try:

```bash
cd /home/ubuntu/automated-trading-platform
```

Verify you're in the right place:

```bash
pwd
ls -la scripts/verify_ec2_ip_and_health.sh
```

---

## Step 3: Generate and Run EC2 Verification Script

If the verification script doesn't exist or needs to be regenerated:

```bash
# Generate the script (avoids paste truncation issues)
python3 scripts/write_verify_ec2_ip_and_health.py

# Run the verification script
./scripts/verify_ec2_ip_and_health.sh
```

If the script already exists and is correct:

```bash
./scripts/verify_ec2_ip_and_health.sh
```

**Expected Output:**
- ✅ EC2 detection checks pass
- ✅ Shows EC2 host outbound IP
- ✅ Shows backend container outbound IP
- ✅ Compares IPs (should match)
- ✅ Shows backend health status
- ✅ Shows EC2 public IP

**Important:** If the script exits with "Not running on EC2", you're not actually on the EC2 instance. Double-check you connected via Session Manager and not a local terminal.

---

## Step 4: Verify Outbound IP for Crypto.com Whitelist

The script output shows:
- **EC2 Host Outbound IP**: This is the IP that Crypto.com sees when the backend makes API calls
- **Backend Container Outbound IP**: Should match the host IP

**Use the EC2 Host Outbound IP for Crypto.com IP whitelist.**

Example output:
```
✅ EC2 Host Outbound IP: 47.130.143.159
✅ Backend Container Outbound IP: 47.130.143.159
✅ Crypto.com Whitelist IP: 47.130.143.159 (use this for IP whitelisting)
```

---

## Step 5: Understanding External Access

### Why External Tests Fail on Mac

When you run `curl http://54.254.150.31:8002/api/health` from your Mac and it times out, **the backend is NOT down**. The issue is:

1. ✅ **Backend IS running** (verified by `verify_ec2_ip_and_health.sh` on EC2)
2. ✅ **Backend IS listening** on port 8002 (confirmed by localhost health check)
3. ❌ **Security Group blocks inbound traffic** from your Mac's IP

### Why IMDS Doesn't Work on Mac

The EC2 Instance Metadata Service (IMDS) at `http://169.254.169.254/` is only accessible from within the EC2 instance itself. When you try to access it from your Mac:
- ❌ The IP `169.254.169.254` is a link-local address (not routable on the internet)
- ❌ It's only available from inside the EC2 instance's network
- ✅ This is why `verify_ec2_ip_and_health.sh` uses IMDS as an EC2 detection signal

---

## Step 6: Enabling Safe Inbound Access

### Method: AWS Console (Recommended)

**⚠️ Important:** Adding Security Group inbound rules does **NOT** change outbound IP. The backend will continue using the same EC2 public IP for Crypto.com API calls.

#### Get Your Mac's Public IP

On your Mac, run:
```bash
curl -s https://api.ipify.org
```

Or use the script:
```bash
./scripts/verify_local_vs_ec2.sh
```

Example output: `185.250.39.133`

#### Add Security Group Rules

1. **In AWS Console**, go to EC2 → Instances
2. **Select your instance** (check the checkbox)
3. **Open the "Security" tab** (bottom panel)
4. **Click on the Security Group link** (opens in new tab)
5. **Click "Edit inbound rules"**
6. **Click "Add rule"** and configure:
   - **Type**: Custom TCP
   - **Port range**: `8002`
   - **Source**: `<YOUR_MAC_IP>/32` (e.g., `185.250.39.133/32`)
   - **Description**: `Backend API access from my IP only`
7. **(Optional)** Add rule for frontend:
   - **Type**: Custom TCP
   - **Port range**: `3000`
   - **Source**: `<YOUR_MAC_IP>/32`
   - **Description**: `Frontend access from my IP only`
8. **Click "Save rules"**

#### Verify Rules

After saving, confirm:
- ✅ Port 8002 allows only `<YOUR_MAC_IP>/32`
- ✅ Port 3000 allows only `<YOUR_MAC_IP>/32` (if added)
- ✅ All other ports remain closed (or restricted as before)
- ✅ SSH (port 22) is NOT open to 0.0.0.0/0

---

## Step 7: Test Inbound Access from Mac

After adding Security Group rules, wait 30 seconds for changes to propagate, then test from your Mac:

```bash
# Get EC2 public IP from the verification script output (Step 3)
EC2_IP="54.254.150.31"  # Replace with actual IP from Step 3

# Test using the verification script
./scripts/verify_inbound_access_from_mac.sh "$EC2_IP"

# Or test manually
curl -m 5 -v http://$EC2_IP:8002/api/health
```

**Expected Result**: HTTP 200 OK with JSON health response

**If it still fails:**
- Wait another 30 seconds (Security Group changes can take time to propagate)
- Verify your Mac's IP hasn't changed: `curl -s https://api.ipify.org`
- Check Security Group rules in AWS Console
- Verify EC2 instance is running

---

## Step 8: Verify Outbound IP Unchanged

After adding inbound rules, verify that outbound IP remains unchanged:

**On EC2 (via SSM Session Manager):**

```bash
# Verify outbound IP (should be the same as before)
curl -s https://api.ipify.org

# Should show the same IP as in Step 3
# This IP is still used for Crypto.com API calls
```

**Why Outbound IP Doesn't Change:**
- Security Group inbound rules only affect **incoming** traffic
- Outbound traffic uses the EC2 instance's public IP (unchanged)
- Container networking is not modified
- Crypto.com whitelist continues to work with the same IP

---

## Verification Checklist

After completing all steps, verify:

- [ ] ✅ Connected to EC2 via SSM Session Manager
- [ ] ✅ Ran `verify_ec2_ip_and_health.sh` successfully
- [ ] ✅ EC2 detection checks passed (not running on Mac)
- [ ] ✅ EC2 host outbound IP recorded
- [ ] ✅ Backend container outbound IP matches host IP
- [ ] ✅ Backend health check returns HTTP 200 (on EC2 localhost)
- [ ] ✅ Crypto.com whitelist IP identified (EC2 host outbound IP)
- [ ] ✅ Security Group inbound rules added (port 8002 from Mac IP/32)
- [ ] ✅ External health check works from Mac (HTTP 200)
- [ ] ✅ Outbound IP unchanged after Security Group changes
- [ ] ✅ Crypto.com API still works (if testable)

---

## Troubleshooting

### Script Says "Not Running on EC2"

**Symptom**: `verify_ec2_ip_and_health.sh` exits with "Not running on EC2"

**Solutions**:
1. Verify you're in SSM Session Manager terminal (not local Mac terminal)
2. Check terminal prompt shows EC2 hostname (e.g., `ubuntu@ip-xxx-xx-xx-xx`)
3. Verify instance is running in AWS Console
4. Check SSM agent is running (should be automatic on Amazon Linux/Ubuntu AMIs)

### External Access Still Fails After Security Group Fix

**Symptom**: `verify_inbound_access_from_mac.sh` still times out

**Solutions**:
1. Wait 30-60 seconds (Security Group changes can take time)
2. Verify your Mac's IP hasn't changed: `curl -s https://api.ipify.org`
3. Check Security Group rules in AWS Console (verify CIDR is `/32`)
4. Verify EC2 instance is running
5. Check container status on EC2: `docker compose --profile aws ps`

### Outbound IP Changed (Should NOT Happen)

**Symptom**: Outbound IP differs after Security Group changes

**This should NOT happen**. Security Group inbound rules don't affect outbound traffic.

**If it happens**:
1. Check if docker-compose.yml was modified
2. Check if container network_mode was changed
3. Verify no VPN/proxy was added
4. Check EC2 instance metadata: `curl -s http://169.254.169.254/latest/meta-data/public-ipv4`

---

## Quick Reference

### Commands on EC2 (via SSM Session Manager)
```bash
# Navigate to project
cd ~/automated-trading-platform

# Run verification
./scripts/verify_ec2_ip_and_health.sh

# Check backend health (localhost)
curl -m 5 -v http://localhost:8002/api/health

# Check outbound IP
curl -s https://api.ipify.org

# Get EC2 public IP
curl -s http://169.254.169.254/latest/meta-data/public-ipv4
```

### Commands on Mac
```bash
# Verify context (proves Mac execution)
./scripts/verify_local_vs_ec2.sh

# Get Mac public IP
curl -s https://api.ipify.org

# Test external access
./scripts/verify_inbound_access_from_mac.sh <EC2_PUBLIC_IP>

# Manual test
curl -m 5 -v http://<EC2_PUBLIC_IP>:8002/api/health
```

---

## Security Notes

✅ **Safe Operations:**
- Adding Security Group inbound rules (restricted to your IP only)
- Testing external access
- Verifying outbound IP
- Checking backend health

❌ **Do NOT:**
- Change docker-compose.yml networking
- Modify container network_mode
- Open ports to 0.0.0.0/0
- Change outbound routing configuration

🔒 **Best Practices:**
- Restrict inbound rules to your IP only (`/32`)
- Use Security Group descriptions for documentation
- Remove rules when no longer needed
- Regularly review Security Group rules

---

## Step 9: Running the Verification Script (Generator Method)

### Why Use the Generator?

If you encounter paste truncation issues when creating the script on EC2 (e.g., heredoc gets cut off), use the Python generator script instead.

### On EC2 (via SSM Session Manager)

```bash
cd ~/automated-trading-platform

# Generate the verification script
python3 scripts/write_verify_ec2_ip_and_health.py

# Run the generated script
./scripts/verify_ec2_ip_and_health.sh
```

### Expected Output

The script will print:
- ✅ System information (hostname, OS, user)
- ✅ EC2 host outbound IP (via python urllib)
- ✅ Backend container outbound IP (via docker compose exec + python urllib)
- ✅ IP comparison (should match)
- ✅ Backend health status (HTTP 200 if healthy)
- ✅ Container status
- ✅ EC2 public IP (for external access)

**Key Output to Note:**
```
✅ Crypto.com Whitelist IP: <EC2_HOST_OUTBOUND_IP>
```
Use this IP for Crypto.com IP whitelisting.

### Interpreting Results

**If IPs match:**
- ✅ Backend uses EC2's public IP for outbound
- ✅ Crypto.com whitelist should use the EC2 host outbound IP

**If IPs don't match:**
- ⚠️ Backend may be routing through VPN/proxy
- ⚠️ Investigate docker-compose networking configuration

---

## Step 10: Diagnosing Inbound Timeouts

### Understanding Inbound Timeouts

When `curl http://<EC2_PUBLIC_IP>:8002/api/health` from your Mac times out, the backend is **NOT down**. The timeout is caused by network access controls blocking inbound traffic.

### Root Cause Checklist

Inbound timeouts can be caused by:

1. **Security Group** (most common)
   - Inbound rules don't allow your IP on ports 8002/3000
   
2. **Network ACL (NACL)**
   - Subnet-level rules blocking inbound traffic
   
3. **Route Table**
   - No Internet Gateway (IGW) route for outbound
   - (Less likely to cause inbound timeout, but affects outbound)

4. **Instance Configuration**
   - Instance doesn't have a public IPv4 address
   - (Very unlikely if you can access via SSM)

### Diagnostic Commands (AWS CLI)

**⚠️ Only run if AWS CLI is configured: `aws sts get-caller-identity`**

```bash
# Set variables
INSTANCE_ID="i-08726dc37133b2454"  # Replace with your instance ID
REGION="ap-southeast-1"  # Replace with your region
MY_IP="185.250.39.133"  # Replace with your Mac's public IP

# 1. Get Security Group ID
SG_ID=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' \
  --output text)

echo "Security Group ID: $SG_ID"

# 2. Check Security Group inbound rules for ports 8002 and 3000
aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region "$REGION" \
  --query 'SecurityGroups[0].IpPermissions[?FromPort==`8002` || FromPort==`3000` || FromPort==`80` || FromPort==`443`]' \
  --output table

# 3. Check if your IP is allowed
aws ec2 describe-security-groups \
  --group-ids "$SG_ID" \
  --region "$REGION" \
  --query "SecurityGroups[0].IpPermissions[?IpRanges[?CidrIp==\`$MY_IP/32\`]]" \
  --output table

# 4. Get subnet ID
SUBNET_ID=$(aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Reservations[0].Instances[0].SubnetId' \
  --output text)

echo "Subnet ID: $SUBNET_ID"

# 5. Check Network ACL rules
aws ec2 describe-network-acls \
  --filters "Name=association.subnet-id,Values=$SUBNET_ID" \
  --region "$REGION" \
  --query 'NetworkAcls[0].Entries[?PortRange.From<=`8002` && PortRange.To>=`8002`]' \
  --output table

# 6. Check instance public IP and route table
aws ec2 describe-instances \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'Reservations[0].Instances[0].[PublicIpAddress,PublicDnsName]' \
  --output table

# 7. Get route table for subnet
ROUTE_TABLE_ID=$(aws ec2 describe-route-tables \
  --filters "Name=association.subnet-id,Values=$SUBNET_ID" \
  --region "$REGION" \
  --query 'RouteTables[0].RouteTableId' \
  --output text)

echo "Route Table ID: $ROUTE_TABLE_ID"

# 8. Check for Internet Gateway route
aws ec2 describe-route-tables \
  --route-table-ids "$ROUTE_TABLE_ID" \
  --region "$REGION" \
  --query 'RouteTables[0].Routes[?GatewayId!=`null`]' \
  --output table
```

### Minimum Safe Inbound Rule Recommendation

Add these Security Group inbound rules (via AWS Console or CLI):

```
Type: Custom TCP
Port: 8002
Source: <YOUR_MAC_IP>/32
Description: Backend API access from my IP only

Type: Custom TCP
Port: 3000
Source: <YOUR_MAC_IP>/32
Description: Frontend access from my IP only (optional)
```

**Important:** These rules only affect **inbound** traffic. Outbound traffic (used by Crypto.com API) remains unchanged.

### Alternative: Cloudflare Tunnel (No Inbound Ports)

If you want to avoid opening any inbound ports:

1. Install cloudflared on EC2
2. Create tunnels for backend (port 8002) and frontend (port 3000)
3. Access via Cloudflare-provided URLs
4. No Security Group changes needed

See `OUTBOUND_IP_REPORT.md` for detailed Cloudflare Tunnel setup.

**Note:** Cloudflare Tunnel does NOT change outbound IP. Backend still uses EC2 IP for Crypto.com API calls.

---

## Summary

✅ **Outbound IP**: Verified via `verify_ec2_ip_and_health.sh` on EC2 (via SSM)  
✅ **Inbound Access**: Configured via AWS Console Security Group rules  
✅ **Safety**: Only inbound rules changed, outbound unchanged  
✅ **Security**: Restricted to your IP only (`/32`)  
✅ **Verification**: Test external health endpoint from Mac  

**Result**: You can now verify backend health from your Mac without affecting Crypto.com IP whitelist.

**Key Point**: Inbound Security Group changes do **NOT** affect outbound IP used for Crypto.com whitelist.

