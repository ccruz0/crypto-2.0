# Deploy Audit Fixes to AWS - Step by Step

## Prerequisites

- Access to AWS server where the application is deployed
- SSH access or ability to run commands on the server
- Docker and docker-compose installed on AWS server
- Repository checked out on AWS server

## Step 1: Connect to AWS Server

```bash
# SSH into your AWS server
ssh your-aws-server

# Navigate to project directory
cd /path/to/automated-trading-platform
```

## Step 2: Pull Latest Changes

```bash
# Make sure you have the latest code
git status
git pull origin main  # or your branch name

# Verify the new files exist
ls -la deploy_audit_fixes.sh run_audit_in_production.sh
ls -la backend/scripts/audit_no_alerts_no_trades.py
```

## Step 3: Deploy Fixes

```bash
# Make scripts executable
chmod +x deploy_audit_fixes.sh run_audit_in_production.sh

# Deploy the fixes
./deploy_audit_fixes.sh
```

This will:
- Build the backend-aws container with new fixes
- Start/restart the container
- Load environment variables

## Step 4: Verify Deployment

```bash
# Check container is running
docker compose --profile aws ps backend-aws

# Check logs for heartbeat (should appear every ~5 minutes)
docker logs -f backend-aws | grep HEARTBEAT

# Check for global blockers
docker logs backend-aws | grep GLOBAL_BLOCKER

# Verify SignalMonitorService started
docker logs backend-aws | grep "Signal monitor service"
```

**Expected output:**
- Container status: `Up`
- Logs show: `Signal monitor service start() scheduled`
- After ~5 minutes: `[HEARTBEAT] SignalMonitorService alive`

## Step 5: Run Audit

```bash
# Run full audit (last 7 days)
./run_audit_in_production.sh

# Or run for specific symbols
docker exec backend-aws python backend/scripts/audit_no_alerts_no_trades.py \
  --symbols ETH_USDT,BTC_USD --since-hours 24

# Or last 24 hours only
./run_audit_in_production.sh 24
```

## Step 6: Review Audit Report

```bash
# View the report
cat docs/reports/no-alerts-no-trades-audit.md

# Or download it locally
scp your-aws-server:/path/to/repo/docs/reports/no-alerts-no-trades-audit.md ./
```

**What to look for:**
1. **GLOBAL STATUS** - Should be PASS if everything is working
2. **Root Causes** - Ranked list of what's blocking alerts/trades
3. **Recommended Fixes** - Specific actions to take

## Step 7: Fix Issues Based on Audit

### If Scheduler Not Running:

```bash
# Check startup logs
docker logs backend-aws | grep "Signal monitor service"

# Check if disabled
docker exec backend-aws env | grep DEBUG_DISABLE_SIGNAL_MONITOR

# If not set, start manually via API
curl -X POST http://localhost:8002/api/control/start-signal-monitor
```

### If Telegram Disabled:

```bash
# Check environment variables
docker exec backend-aws env | grep -E "ENVIRONMENT|TELEGRAM"

# Edit .env.aws file
nano .env.aws

# Add/verify:
# ENVIRONMENT=aws
# TELEGRAM_BOT_TOKEN=your_token_here
# TELEGRAM_CHAT_ID_AWS=your_chat_id_here

# Restart to load new env vars
docker compose --profile aws restart backend-aws
```

### If Market Data Stale:

```bash
# Check market-updater logs
docker logs market-updater-aws --tail 100

# Verify it's running
docker compose --profile aws ps market-updater-aws

# If not running, start it
docker compose --profile aws up -d market-updater-aws
```

## Step 8: Verify Fixes

```bash
# Re-run audit
./run_audit_in_production.sh 24

# Check heartbeat is working
docker logs backend-aws | grep HEARTBEAT | tail -5

# Check no global blockers
docker logs backend-aws | grep GLOBAL_BLOCKER
```

## Troubleshooting

### Container Won't Start

```bash
# Check logs for errors
docker logs backend-aws --tail 100

# Check docker-compose config
docker compose --profile aws config

# Try rebuilding
docker compose --profile aws build --no-cache backend-aws
```

### Audit Script Fails

```bash
# Check Python dependencies
docker exec backend-aws python -c "import app.models.watchlist; print('OK')"

# Check database connection
docker exec backend-aws python -c "from app.database import SessionLocal; db = SessionLocal(); db.close(); print('OK')"

# Run with verbose output
docker exec backend-aws python backend/scripts/audit_no_alerts_no_trades.py --since-hours 1 -v
```

### No Heartbeat Messages

```bash
# Check if SignalMonitorService is running
docker logs backend-aws | grep "Signal monitor service"

# Check for errors
docker logs backend-aws | grep -i error | tail -20

# Check if disabled
docker exec backend-aws env | grep DEBUG_DISABLE_SIGNAL_MONITOR
```

## Quick Commands Reference

```bash
# Deploy
./deploy_audit_fixes.sh

# Run audit
./run_audit_in_production.sh

# Check heartbeat
docker logs backend-aws | grep HEARTBEAT

# Check blockers
docker logs backend-aws | grep GLOBAL_BLOCKER

# View logs
docker logs backend-aws --tail 100 -f

# Restart
docker compose --profile aws restart backend-aws

# Check status
docker compose --profile aws ps
```

## Success Indicators

You'll know it's working when:

✅ Heartbeat logs appear every ~5 minutes  
✅ No [GLOBAL_BLOCKER] warnings  
✅ Audit report shows GLOBAL STATUS: PASS  
✅ SignalMonitorService is running  
✅ Telegram is enabled (if alerts should be sent)  

## Next Steps After Fixes

1. Set up monitoring for heartbeat (alert if missing for 10+ minutes)
2. Set up alerts for [GLOBAL_BLOCKER] warnings
3. Schedule daily audits
4. Monitor audit reports for trends




