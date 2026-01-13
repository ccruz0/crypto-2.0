# Next Steps - BUY SIGNAL Decision Tracing Fix

## Current Status ✅

- ✅ Code changes complete (3 files modified)
- ✅ Deployment script ready (`deploy_decision_tracing_fix.sh`)
- ✅ Test script ready (`test_aws_ssh.sh`)
- ❌ SSH access not configured (connection timeout)

## Immediate Next Steps

### Step 1: Configure AWS Security Group (Required)

**Action**: Allow SSH access to your EC2 instance

1. Go to **AWS Console** → **EC2** → **Security Groups**
2. Find the security group attached to instance `i-08726dc37133b2454`
3. Click **Edit Inbound Rules**
4. Add/Edit SSH rule:
   - **Type**: SSH
   - **Protocol**: TCP
   - **Port**: 22
   - **Source**: 
     - Option A: `0.0.0.0/0` (allows from anywhere - use for testing)
     - Option B: Your current IP address (more secure)
   - **Description**: "SSH access for deployment"
5. Click **Save Rules**

**How to find your IP**: 
```bash
curl ifconfig.me
# Or visit: https://whatismyipaddress.com/
```

### Step 2: Verify Instance is Running

**Action**: Check AWS Console

1. Go to **AWS Console** → **EC2** → **Instances**
2. Find instance `i-08726dc37133b2454`
3. Verify status is **"Running"**
4. Note the **Public IPv4 address** (should be `47.130.143.159` or similar)

### Step 3: Test SSH Connection

**Action**: Run the test script

```bash
./test_aws_ssh.sh
```

**Expected**: Should show "✅ SSH connection is working!"

**If it fails**: 
- Double-check Security Group rules
- Verify instance is running
- Check if IP address has changed (update in script if needed)

### Step 4: Deploy the Fix

**Action**: Run deployment script

```bash
./deploy_decision_tracing_fix.sh
```

**What it does**:
1. Syncs 3 Python files to AWS
2. Restarts market-updater process
3. Restarts backend API (if running directly)

**Expected output**: Success messages confirming files synced and services restarted

### Step 5: Verify Deployment

**Action**: Test the new diagnostics endpoint

```bash
# Replace with your AWS server IP/domain
curl http://47.130.143.159:8000/api/diagnostics/recent-buy-signals?limit=10
```

**Expected**: JSON response with BUY SIGNAL messages and their decision traces

## Alternative: Manual Deployment

If SSH can't be configured right now, you can:

1. **Use AWS Session Manager** (browser-based):
   - AWS Console → EC2 → Instances
   - Select instance → Connect → Session Manager
   - Manually copy files via command line

2. **Use GitHub Actions** (if configured):
   - Push code to repository
   - Let automated workflow deploy

3. **Use AWS Console EC2 Instance Connect**:
   - Connect via browser
   - Upload files manually

## Quick Command Reference

```bash
# Test SSH
./test_aws_ssh.sh

# Deploy
./deploy_decision_tracing_fix.sh

# Verify (after deployment)
curl http://YOUR_AWS_IP:8000/api/diagnostics/recent-buy-signals?limit=10

# Check logs (SSH to server first)
ssh ubuntu@YOUR_AWS_IP
tail -50 ~/automated-trading-platform/backend/market_updater.log
```

## Files Ready to Deploy

These 3 files are ready and tested:
- `backend/app/api/routes_monitoring.py`
- `backend/app/services/signal_monitor.py`
- `backend/app/utils/decision_reason.py`

## Success Criteria

✅ Deployment is successful when:
1. SSH connection works
2. Files are synced to AWS
3. Services restart without errors
4. Diagnostics endpoint returns data
5. New BUY SIGNAL messages have decision traces (not NULL)

## Need Help?

- **SSH issues**: See `SSH_SETUP_GUIDE.md`
- **Deployment details**: See `DEPLOYMENT_SUMMARY.md`
- **Technical details**: See `BUY_SIGNAL_DECISION_TRACING_FIX.md`
