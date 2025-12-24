# Fix 502 Recurring Issue

## Problem Summary

The 502 Bad Gateway error keeps recurring because Docker containers (`backend-aws` and `frontend-aws`) are stopping unexpectedly on the AWS server.

## Root Cause Analysis

1. **Exit Code 137**: Containers are being killed (likely OOM or manual termination)
2. **Memory Constraints**: Server has only 1.9GB RAM, which may be insufficient during peak loads
3. **No Auto-Recovery**: While `restart: always` is configured, containers may not restart if the entire stack stops

## Current Status

- ✅ All services are currently running
- ✅ Backend: Port 8002 - Healthy
- ✅ Frontend: Port 3000 - Healthy  
- ✅ Dashboard: https://dashboard.hilovivo.com - Working

## Solution: Auto-Restart Script

A script has been created to automatically monitor and restart containers if they stop:

**Script**: `auto_restart_containers.sh`

### Usage

**Manual execution:**
```bash
./auto_restart_containers.sh
```

**Set up as cron job (every 5 minutes):**
```bash
# SSH to AWS server
ssh hilovivo-aws

# Edit crontab
crontab -e

# Add this line:
*/5 * * * * /home/ubuntu/automated-trading-platform/auto_restart_containers.sh >> /var/log/auto_restart_containers.log 2>&1
```

### What the Script Does

1. Checks if backend and frontend containers are running
2. Verifies they're actually responding (HTTP health checks)
3. Restarts containers if they're down or not responding
4. Logs all actions for troubleshooting

## Quick Fix Commands

If 502 error occurs again, run these commands:

```bash
# Option 1: Use the auto-restart script
./auto_restart_containers.sh

# Option 2: Manual restart
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws up -d'

# Option 3: Quick diagnostic script
./quick_fix_502.sh
```

## Monitoring

### Check Container Status
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws ps'
```

### Check Logs
```bash
# Backend logs
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs --tail=100 backend-aws'

# Frontend logs  
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs --tail=100 frontend-aws'

# Auto-restart script logs
ssh hilovivo-aws 'tail -50 /tmp/auto_restart_containers.log'
```

### Check System Resources
```bash
ssh hilovivo-aws 'free -h && docker stats --no-stream'
```

## Recommendations

1. **Set up cron job** to run `auto_restart_containers.sh` every 5 minutes
2. **Monitor logs** regularly to identify patterns in container failures
3. **Consider upgrading server** if memory constraints are the issue (currently 1.9GB RAM)
4. **Set up alerts** to notify when containers stop (can extend the script)

## Notes

- Exit code 137 typically means the container was killed by the system (OOM killer)
- The server has limited memory (1.9GB total, ~400MB available)
- Containers have memory limits configured in docker-compose.yml:
  - Backend: 1GB limit
  - Frontend: 512MB limit
  - Database: Uses remaining memory

## Future Improvements

1. Add email/Slack notifications when containers restart
2. Increase server memory or optimize container resource usage
3. Set up more comprehensive monitoring (e.g., Prometheus + Grafana)
4. Investigate root cause of why containers are being killed

