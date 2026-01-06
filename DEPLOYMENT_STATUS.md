# Deployment Status

## Current Status

Deployment command has been sent to AWS instance `i-08726dc37133b2454`.

**Command ID**: `aa64b511-3d0f-4a9f-ae3b-e47efcaf1df5`

## What's Happening

The deployment script is:
1. ✅ Pulling latest code from git
2. 🔄 Building Docker image (backend-aws)
3. ⏳ Starting/restarting container
4. ⏳ Waiting for service to start
5. ⏳ Running audit script

This process typically takes **3-5 minutes**.

## Check Status

```bash
# Check deployment status
./check_deployment_status.sh

# Or manually
aws ssm get-command-invocation \
  --command-id aa64b511-3d0f-4a9f-ae3b-e47efcaf1df5 \
  --instance-id i-08726dc37133b2454 \
  --region ap-southeast-1 \
  --query "Status" \
  --output text
```

## What to Expect

### When Deployment Completes:

1. **Container Status**
   - Container should be running
   - Check: `docker compose --profile aws ps`

2. **Heartbeat Logs** (appear every ~5 minutes)
   ```
   [HEARTBEAT] SignalMonitorService alive - cycle=10 last_run=...
   ```

3. **Audit Report**
   - Location: `docs/reports/no-alerts-no-trades-audit-*.md`
   - Contains root causes and recommended fixes

4. **Global Blockers** (if any)
   ```
   [GLOBAL_BLOCKER] Telegram notifier is disabled
   [GLOBAL_BLOCKER] No watchlist items with alert_enabled=True found
   ```

## Next Steps After Deployment

1. **Check Status**
   ```bash
   ./check_deployment_status.sh
   ```

2. **Verify Deployment**
   ```bash
   # SSH into AWS server
   ssh your-aws-server
   
   # Check container
   docker compose --profile aws ps
   
   # Check logs
   docker logs automated-trading-platform-backend-aws-1 | grep HEARTBEAT
   ```

3. **View Audit Report**
   ```bash
   # On AWS server
   cat docs/reports/no-alerts-no-trades-audit-*.md | tail -1
   
   # Or download locally
   scp your-aws-server:/path/to/repo/docs/reports/no-alerts-no-trades-audit-*.md ./
   ```

4. **Fix Issues Based on Audit**
   - Review the audit report
   - Apply recommended fixes
   - Re-run audit to verify

## Troubleshooting

### If Deployment Fails

1. Check command output:
   ```bash
   aws ssm get-command-invocation \
     --command-id aa64b511-3d0f-4a9f-ae3b-e47efcaf1df5 \
     --instance-id i-08726dc37133b2454 \
     --region ap-southeast-1
   ```

2. Common issues:
   - Git pull failed (ownership issues) - Already handled in script
   - Container name mismatch - Script now auto-detects container name
   - Build timeout - May need to increase timeout

### If Audit Fails

1. Check container is running
2. Check database connectivity
3. Run audit manually:
   ```bash
   docker exec <container-name> python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24
   ```

## Manual Deployment (If SSM Fails)

If SSM deployment fails, you can deploy manually:

```bash
# SSH into AWS server
ssh your-aws-server

# Navigate to project
cd /home/ubuntu/automated-trading-platform

# Pull latest code
git pull origin main

# Deploy
./deploy_audit_fixes.sh

# Run audit
./run_audit_in_production.sh
```
