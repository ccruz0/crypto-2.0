# AWS Health Monitoring Tools - Quick Reference

**Purpose**: Quick reference guide for all health monitoring scripts and tools available in the AWS deployment.

**Last Updated**: 2026-01-08

---

## Overview

The platform includes multiple health monitoring tools for different purposes:
- **Automated health monitoring** (runs continuously)
- **One-time health checks** (manual verification)
- **Dashboard health checks** (data quality verification)
- **Runtime health checks** (service status verification)

---

## Automated Monitoring Scripts

### 1. Health Monitor (`scripts/health_monitor.sh`)

**Purpose**: Continuous monitoring with automatic recovery

**Features**:
- Monitors all Docker services (backend, frontend, market-updater, db)
- Automatically restarts unhealthy services
- Rebuilds services after max restart attempts
- Checks database connectivity
- Monitors Nginx status (if accessible)
- Logs all actions to `logs/health_monitor.log`

**Usage**:
```bash
# Run manually
./scripts/health_monitor.sh

# Install as systemd service (on EC2)
./install_health_monitor.sh
```

**Configuration**:
- Check interval: 60 seconds
- Max restart attempts: 3 per service
- Log file: `logs/health_monitor.log`

**What it checks**:
- Docker service health status
- Container running state
- Healthcheck results
- Database connectivity
- Nginx service status

**Recovery actions**:
1. Restart unhealthy services
2. Rebuild services after max restarts
3. Restart database if not ready
4. Restart Nginx if not running

---

### 2. Dashboard Health Check (`scripts/dashboard_health_check.sh`)

**Purpose**: Verifies dashboard data quality and sends Telegram alerts

**Features**:
- Checks `/api/market/top-coins-data` endpoint
- Validates JSON response
- Verifies minimum coin count (default: 5)
- Validates data quality (prices, instrument names)
- Sends Telegram notifications on failure
- Sends success notification once per hour

**Usage**:
```bash
# Run manually
./scripts/dashboard_health_check.sh

# Install as systemd timer (runs every 20 minutes)
./install_dashboard_health_check.sh
```

**Configuration**:
- API URL: `http://localhost:8002/api` (default)
- Timeout: 30 seconds
- Minimum coins: 5
- Log file: `/tmp/dashboard_health_check.log`

**What it checks**:
- Endpoint connectivity
- JSON response validity
- Coin count >= minimum
- Data quality (prices, instrument names)
- Source of data

**Alert conditions**:
- Endpoint not responding
- Invalid JSON response
- Insufficient coins (< 5)
- Data quality issues (missing prices)

---

## Manual Health Check Scripts

### 3. Runtime Health Check (`scripts/check_runtime_health_aws.sh`)

**Purpose**: One-time comprehensive health check of AWS backend

**Usage**:
```bash
# From local machine (SSH to AWS)
bash scripts/check_runtime_health_aws.sh
```

**What it checks**:
- Backend container status
- Runs Python health check script inside container
- Reports warnings and failures

**Output**:
- ✅ Green: All checks passed
- ⚠️ Yellow: Warnings detected
- ❌ Red: Failures detected

---

### 4. EC2 IP and Health Verification (`scripts/verify_ec2_ip_and_health.sh`)

**Purpose**: Verify EC2 outbound IP and backend health (for IP whitelisting)

**Usage**:
```bash
# Run INSIDE EC2 via AWS SSM Session Manager
./scripts/verify_ec2_ip_and_health.sh
```

**What it checks**:
1. System information (hostname, OS, user)
2. EC2 host outbound IP
3. Backend container outbound IP
4. IP comparison (host vs container)
5. Backend health check (localhost)
6. Container status
7. EC2 public IP

**Use case**: 
- Verify IP for Crypto.com whitelisting
- Confirm backend uses EC2's public IP
- Check backend health status

---

### 5. Backend Status Check (`check_backend_status.sh`)

**Purpose**: Quick backend status check

**Usage**:
```bash
./check_backend_status.sh
```

**What it checks**:
- Backend container status
- Health endpoint response
- Service availability

---

### 6. Market Data Status (`scripts/verify_market_data_status.sh`)

**Purpose**: Verify market data freshness and quality

**Usage**:
```bash
# From local machine
./scripts/verify_market_data_status.sh

# Or Python version
python scripts/verify_market_data_status.py
```

**What it checks**:
- Market data freshness
- Stale symbols count
- Data quality metrics

---

### 7. Telegram Status Check (`check_telegram_status.sh`)

**Purpose**: Verify Telegram bot configuration and status

**Usage**:
```bash
./check_telegram_status.sh
```

**What it checks**:
- Telegram bot token configured
- Chat ID configured
- Telegram service enabled
- Last send status

---

## Health Endpoint Checks

### Quick Health Check Commands

**Public Endpoint (from anywhere)**:
```bash
# Full system health
curl -s https://dashboard.hilovivo.com/api/health/system | jq .

# Specific components
curl -s https://dashboard.hilovivo.com/api/health/system | jq '.market_updater, .market_data'

# Global status only
curl -s https://dashboard.hilovivo.com/api/health/system | jq -r '.global_status'

# Market data freshness
curl -s https://dashboard.hilovivo.com/api/health/system | jq '.market_data | {fresh_symbols, stale_symbols, max_age_minutes}'
```

**Internal Endpoint (SSH to EC2)**:
```bash
# SSH to EC2
ssh ubuntu@47.130.143.159

# Full system health
curl -s http://localhost:8002/api/health/system | jq .

# Basic health
curl -s http://localhost:8002/api/health
```

---

## Docker Service Health Checks

### Check All Services
```bash
# From EC2
docker compose --profile aws ps

# Check specific service
docker compose --profile aws ps backend-aws
docker compose --profile aws ps market-updater-aws
```

### Service Logs
```bash
# Backend logs
docker compose --profile aws logs --tail 100 backend-aws

# Market updater logs
docker compose --profile aws logs --tail 100 market-updater-aws

# All services
docker compose --profile aws logs --tail 50
```

### Service Restart
```bash
# Restart specific service
docker compose --profile aws restart backend-aws

# Restart all services
docker compose --profile aws restart
```

---

## Installation Scripts

### Install Health Monitor Service
```bash
# On EC2
./install_health_monitor.sh
```

**What it does**:
- Creates systemd service file
- Enables and starts the service
- Sets up automatic startup on boot

**Service file**: `scripts/health_monitor.service`

---

### Install Dashboard Health Check Timer
```bash
# On EC2
./install_dashboard_health_check.sh
```

**What it does**:
- Creates systemd timer file
- Creates systemd service file
- Enables timer to run every 20 minutes
- Sets up automatic startup on boot

**Files**:
- `scripts/dashboard_health_check.service`
- `scripts/dashboard_health_check.timer`

---

## Monitoring Best Practices

### 1. Set Up External Monitoring

**Recommended**: Use UptimeRobot or CloudWatch to monitor:
- `https://dashboard.hilovivo.com/api/health/system`
- Alert on: `global_status != "PASS"`

### 2. Enable Automated Health Monitor

**On EC2**:
```bash
./install_health_monitor.sh
```

This ensures services are automatically restarted if they fail.

### 3. Enable Dashboard Health Check

**On EC2**:
```bash
./install_dashboard_health_check.sh
```

This monitors data quality and sends Telegram alerts.

### 4. Regular Manual Checks

**Daily**:
- Check system health endpoint
- Review service logs
- Verify market data freshness

**Weekly**:
- Review health monitor logs
- Check for recurring issues
- Verify all services are running

---

## Troubleshooting

### Health Monitor Not Running

**Check service status**:
```bash
# On EC2
systemctl status health-monitor
```

**View logs**:
```bash
journalctl -u health-monitor -f
```

**Restart service**:
```bash
sudo systemctl restart health-monitor
```

---

### Dashboard Health Check Failing

**Check timer status**:
```bash
# On EC2
systemctl status dashboard-health-check.timer
```

**View logs**:
```bash
tail -f /tmp/dashboard_health_check.log
```

**Run manually**:
```bash
./scripts/dashboard_health_check.sh
```

---

### Services Unhealthy

**Check Docker services**:
```bash
docker compose --profile aws ps
```

**Check health endpoint**:
```bash
curl -s http://localhost:8002/api/health/system | jq .
```

**Review logs**:
```bash
docker compose --profile aws logs --tail 200 backend-aws
```

**Restart services**:
```bash
docker compose --profile aws restart
```

---

## Quick Reference Table

| Tool | Purpose | Frequency | Location |
|------|---------|-----------|----------|
| `health_monitor.sh` | Auto-recovery | Continuous (60s) | `scripts/` |
| `dashboard_health_check.sh` | Data quality | Every 20 min | `scripts/` |
| `/api/health/system` | System status | On-demand | Backend API |
| `/api/health` | Basic health | On-demand | Backend API |
| `check_runtime_health_aws.sh` | One-time check | Manual | `scripts/` |
| `verify_ec2_ip_and_health.sh` | IP verification | Manual | `scripts/` |

---

## Integration with External Monitoring

### UptimeRobot Setup

1. **Create Monitor**:
   - Type: HTTP(s)
   - URL: `https://dashboard.hilovivo.com/api/health/system`
   - Interval: 5 minutes

2. **Alert Conditions**:
   - HTTP status != 200
   - Response contains `"global_status": "FAIL"`
   - Response time > 10 seconds

3. **Keyword Monitoring** (optional):
   - Keyword: `"market_updater":{"status":"PASS"`
   - Alert if: Keyword not found

---

### CloudWatch Synthetics

See `docs/monitoring/HEALTH_MONITORING.md` for CloudWatch setup instructions.

---

## Summary

The platform has comprehensive health monitoring:

✅ **Automated monitoring** with auto-recovery  
✅ **Data quality checks** with Telegram alerts  
✅ **Manual verification tools** for troubleshooting  
✅ **Health endpoints** for external monitoring  
✅ **Docker healthchecks** for container monitoring  

**Recommended Setup**:
1. Install health monitor service (auto-recovery)
2. Install dashboard health check timer (data quality)
3. Set up external monitoring (UptimeRobot/CloudWatch)
4. Review health status daily

---

**Related Documentation**:
- `docs/AWS_SYSTEM_STATUS_REVIEW.md` - Comprehensive system status review
- `docs/monitoring/HEALTH_MONITORING.md` - External monitoring setup
- `AWS_DEPLOY_PLAYBOOK.md` - Deployment procedures

