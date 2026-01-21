# Quick Deploy - Alert Fix

## Status
✅ Code committed and pushed to `main`  
✅ Commit: `e200dd9` - "fix: Alert system discrepancy - Enhanced logging and database migration"

## Deployment Options

### Option 1: SSH to AWS (Recommended)

```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
bash scripts/deploy_aws.sh
```

This will:
1. Pull latest code from git
2. Build backend services
3. Restart containers
4. Verify deployment

### Option 2: Use SSM (If Available)

```bash
./deploy_via_ssm.sh
```

### Option 3: Manual SSH Commands

```bash
ssh hilovivo-aws << 'EOF'
cd /home/ubuntu/automated-trading-platform
git pull origin main
docker compose --profile aws build backend-aws
docker compose --profile aws up -d --force-recreate --no-deps backend-aws
sleep 15
docker compose --profile aws ps
curl -sS http://127.0.0.1:8002/health
EOF
```

## After Deployment

### 1. Run Database Migration (REQUIRED)

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && ./RUN_ALERT_FIX_ON_AWS.sh'
```

### 2. Verify Deployment

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && ./VERIFY_ALERT_FIX.sh'
```

### 3. Check Startup Logs

```bash
ssh hilovivo-aws 'docker logs $(docker compose --profile aws ps -q backend-aws) | grep STARTUP_ALERT_CONFIG | head -30'
```

## Expected Results

After deployment:
- ✅ Backend restarted with new code
- ✅ Startup logs show: `[STARTUP_ALERT_CONFIG] total_active_coins=X alert_enabled_true=X alert_enabled_false=0`
- ✅ Database migration sets all coins to `alert_enabled=True`
- ✅ Verification script passes all checks

## Quick Commands Summary

```bash
# Deploy code
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && bash scripts/deploy_aws.sh'

# Run migration
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && ./RUN_ALERT_FIX_ON_AWS.sh'

# Verify
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && ./VERIFY_ALERT_FIX.sh'
```
