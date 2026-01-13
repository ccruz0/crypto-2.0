# AWS Health Monitoring - Executive Summary

**Date**: 2026-01-08  
**Purpose**: Quick overview of AWS system health monitoring capabilities

---

## Quick Status Check

### Public Endpoint (Recommended)
```bash
curl -s https://dashboard.hilovivo.com/api/health/system | jq .
```

### Internal Endpoint (SSH to EC2)
```bash
ssh ubuntu@47.130.143.159
curl -s http://localhost:8002/api/health/system | jq .
```

---

## System Health Components

The system monitors **5 critical components**:

1. **Market Data** - Price data freshness (30 min threshold)
2. **Market Updater** - Background price update service
3. **Signal Monitor** - Trading signal monitoring service
4. **Telegram** - Notification service status
5. **Trade System** - Open orders and trading operations

**Global Status**: `PASS` | `WARN` | `FAIL` (computed from all components)

---

## Available Tools

### Automated Monitoring
- **Health Monitor** (`scripts/health_monitor.sh`) - Auto-recovery every 60s
- **Dashboard Health Check** (`scripts/dashboard_health_check.sh`) - Data quality every 20 min

### Manual Checks
- **Runtime Health** (`scripts/check_runtime_health_aws.sh`) - One-time comprehensive check
- **EC2 IP Verification** (`scripts/verify_ec2_ip_and_health.sh`) - IP whitelisting verification
- **Market Data Status** (`scripts/verify_market_data_status.sh`) - Data freshness check

### Health Endpoints
- `/api/health/system` - Comprehensive system health (recommended)
- `/api/health` - Basic health check

---

## Recommended Setup

1. **Install Health Monitor** (auto-recovery):
   ```bash
   ./install_health_monitor.sh
   ```

2. **Install Dashboard Health Check** (data quality):
   ```bash
   ./install_dashboard_health_check.sh
   ```

3. **Set Up External Monitoring**:
   - UptimeRobot: Monitor `https://dashboard.hilovivo.com/api/health/system`
   - Alert on: `global_status != "PASS"`

---

## Documentation

- **Comprehensive Review**: `docs/AWS_SYSTEM_STATUS_REVIEW.md`
- **Tools Reference**: `docs/AWS_HEALTH_MONITORING_TOOLS.md`
- **External Monitoring**: `docs/monitoring/HEALTH_MONITORING.md`

---

## Quick Troubleshooting

### Services Unhealthy
```bash
# Check Docker services
docker compose --profile aws ps

# Check health endpoint
curl -s http://localhost:8002/api/health/system | jq .

# Restart services
docker compose --profile aws restart
```

### Market Data Stale
```bash
# Check market updater
docker compose --profile aws ps market-updater-aws

# Restart market updater
docker compose --profile aws restart market-updater-aws

# Check logs
docker compose --profile aws logs --tail 100 market-updater-aws
```

---

**For detailed information, see the full documentation files listed above.**


