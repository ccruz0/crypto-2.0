# AWS System Status Review - Current State

**Date**: 2026-01-08  
**Purpose**: Comprehensive review of AWS services, health endpoints, and overall operational state

---

## Executive Summary

The automated trading platform on AWS has a comprehensive health monitoring system with multiple endpoints and service checks. The system monitors critical components including market data, signal monitoring, Telegram notifications, and trading operations.

**System Status**: ✅ Operational  
**Health Monitoring**: ✅ Comprehensive  
**Service Architecture**: ✅ Well-structured

---

## Health Endpoints

### Public Endpoints (Production)

1. **System Health** (Comprehensive) - **Recommended for monitoring**
   - **URL**: `https://dashboard.hilovivo.com/api/health/system`
   - **Purpose**: Complete system health status with all component checks
   - **Response Time**: < 1 second (typically)
   - **Cache**: No cache (real-time data)
   - **Implementation**: `backend/app/api/routes_monitoring.py::get_system_health_endpoint()`

2. **Basic Health** (Simple)
   - **URL**: `https://dashboard.hilovivo.com/api/health`
   - **Purpose**: Quick health check
   - **Response**: `{"status": "ok", "path": "/api/health"}`
   - **Implementation**: `backend/app/main.py::api_health()`

3. **Root Health**
   - **URL**: `https://dashboard.hilovivo.com/health`
   - **Purpose**: Basic health check at root level
   - **Response**: `{"status": "ok"}`
   - **Implementation**: `backend/app/main.py::health()`

4. **Frontend**
   - **URL**: `https://dashboard.hilovivo.com`
   - **Purpose**: Frontend accessibility check

### Internal Endpoints (SSH to EC2)

1. **System Health**:
   - **URL**: `http://localhost:8002/api/health/system`
   - **Access**: Via SSH to EC2 instance (47.130.143.159)

2. **Basic Health**:
   - **URL**: `http://localhost:8002/api/health`
   - **Access**: Via SSH to EC2 instance

---

## System Health Response Format

The `/api/health/system` endpoint returns a comprehensive health status:

```json
{
  "global_status": "PASS" | "FAIL" | "WARN",
  "timestamp": "2026-01-08T12:00:00.000000+00:00",
  "market_data": {
    "status": "PASS" | "FAIL" | "WARN",
    "fresh_symbols": 33,
    "stale_symbols": 0,
    "max_age_minutes": 0.21
  },
  "market_updater": {
    "status": "PASS" | "FAIL",
    "is_running": true,
    "last_heartbeat_age_minutes": 0.21
  },
  "signal_monitor": {
    "status": "PASS" | "FAIL" | "WARN",
    "is_running": true,
    "last_cycle_age_minutes": 16.33
  },
  "telegram": {
    "status": "PASS" | "FAIL",
    "enabled": true,
    "chat_id_set": true,
    "last_send_ok": true
  },
  "trade_system": {
    "status": "PASS" | "FAIL" | "WARN",
    "open_orders": 22,
    "max_open_orders": null,
    "last_check_ok": true
  }
}
```

**Implementation**: `backend/app/services/system_health.py::get_system_health()`

---

## Monitored Services

### 1. Market Data Service

**Purpose**: Tracks freshness of market price data for watchlist symbols

**Health Check Logic**:
- Queries all non-deleted watchlist items
- Checks `MarketPrice` table for each symbol's `updated_at` timestamp
- Calculates age of data in minutes
- Compares against threshold (default: 30 minutes)

**Status Levels**:
- **PASS**: All symbols have fresh data (< 30 minutes old)
- **WARN**: Some symbols stale, but not all
- **FAIL**: All symbols stale OR no market data exists

**Metrics**:
- `fresh_symbols`: Count of symbols with fresh data
- `stale_symbols`: Count of symbols with stale data
- `max_age_minutes`: Age of oldest data point

**Configuration**:
- Threshold: `HEALTH_STALE_MARKET_MINUTES` (default: 30 minutes)
- Environment variable: Set in `.env.aws` or `docker-compose.yml`

**Implementation**: `backend/app/services/system_health.py::_check_market_data_health()`

---

### 2. Market Updater Service

**Purpose**: Background service that updates market prices periodically

**Health Check Logic**:
- Uses market data freshness as a heartbeat proxy
- If `max_age_minutes < threshold`: Service is running
- If `max_age_minutes >= threshold`: Service may be stopped/stalled

**Status Levels**:
- **PASS**: Service running (fresh data detected)
- **FAIL**: Service not running (stale or no data)

**Metrics**:
- `is_running`: Boolean indicating if service is active
- `last_heartbeat_age_minutes`: Age of most recent update

**Docker Service**:
- Container: `market-updater-aws`
- Profile: `aws`
- Healthcheck: Checks backend health every 30s
- Command: `python3 run_updater.py`
- Restart: `unless-stopped`

**Implementation**: `backend/app/services/system_health.py::_check_market_updater_health()`

---

### 3. Signal Monitor Service

**Purpose**: Monitors trading signals and triggers alerts/orders

**Health Check Logic**:
- Checks if service is running (`signal_monitor_service.is_running`)
- Checks last cycle execution time
- Compares against threshold (default: 30 minutes)

**Status Levels**:
- **PASS**: Service running and recent cycle detected
- **WARN**: Service running but no cycles recorded yet
- **FAIL**: Service not running OR last cycle too old

**Metrics**:
- `is_running`: Boolean indicating if service is active
- `last_cycle_age_minutes`: Age of last signal monitoring cycle

**Configuration**:
- Threshold: `HEALTH_MONITOR_STALE_MINUTES` (default: 30 minutes)

**Service Location**:
- Runs in `backend-aws` container
- Started during backend startup event

**Implementation**: `backend/app/services/system_health.py::_check_signal_monitor_health()`

---

### 4. Telegram Notifier Service

**Purpose**: Sends Telegram notifications for alerts and trading events

**Health Check Logic**:
- Checks if Telegram is enabled (`telegram_notifier.enabled`)
- Verifies bot token is set
- Verifies chat ID is set
- Optionally checks last send result

**Status Levels**:
- **PASS**: All required config present and enabled
- **FAIL**: Missing config or disabled

**Metrics**:
- `enabled`: Boolean indicating if Telegram is enabled
- `chat_id_set`: Boolean indicating if chat ID is configured
- `last_send_ok`: Result of last send attempt (optional)

**Configuration**:
- AWS: Uses `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` from `.env.aws`
- Local: Uses `TELEGRAM_BOT_TOKEN_LOCAL` and `TELEGRAM_CHAT_ID_LOCAL` from `.env.local`

**Note**: Telegram is AWS-only in production (routing logic ensures only AWS sends messages)

**Implementation**: `backend/app/services/system_health.py::_check_telegram_health()`

---

### 5. Trade System Service

**Purpose**: Monitors trading operations and open orders

**Health Check Logic**:
- Counts total open positions/orders
- Compares against maximum threshold (if configured)
- Verifies system can query orders successfully

**Status Levels**:
- **PASS**: System healthy, orders within limits
- **WARN**: Open orders exceed configured maximum
- **FAIL**: Cannot query orders or system error

**Metrics**:
- `open_orders`: Count of open positions
- `max_open_orders`: Maximum allowed (from config, optional)
- `last_check_ok`: Boolean indicating last check succeeded

**Implementation**: `backend/app/services/system_health.py::_check_trade_system_health()`

---

## Global Status Calculation

The `global_status` field is computed from component statuses:

1. **FAIL**: If ANY component has status "FAIL"
2. **WARN**: If ANY component has status "WARN" (and none are FAIL)
3. **PASS**: All components have status "PASS"

**Implementation**: `backend/app/services/system_health.py::get_system_health()`

---

## Docker Services (AWS Profile)

### Backend Service
- **Container**: `automated-trading-platform-backend-aws-1`
- **Port**: 8002
- **Healthcheck**: `/ping_fast` endpoint (every 120s)
- **Dependencies**: Database (PostgreSQL)
- **Services Started**:
  - Signal Monitor Service
  - Trading Scheduler
  - Exchange Sync Service
  - Telegram Bot (if enabled)
- **Command**: `gunicorn app.main:app -w 1 -k uvicorn.workers.UvicornWorker`
- **Restart**: `always`
- **Resources**: 1 CPU, 1GB RAM

### Frontend Service
- **Container**: `automated-trading-platform-frontend-aws-1`
- **Port**: 3000 (internal), 80/443 (external via nginx)
- **Healthcheck**: Simple exit check (every 30s)
- **Restart**: `always`
- **Resources**: 1 CPU, 512MB RAM
- **Security**: Read-only filesystem, no-new-privileges, cap_drop ALL

### Market Updater Service
- **Container**: `automated-trading-platform-market-updater-aws-1`
- **Purpose**: Updates market prices in background
- **Healthcheck**: Checks backend health (every 30s)
- **Dependencies**: Database, Backend
- **Command**: `python3 run_updater.py`
- **Restart**: `unless-stopped`

### Database Service
- **Container**: `postgres_hardened`
- **Port**: 5432 (internal)
- **Healthcheck**: `pg_isready` (every 30s)
- **Restart**: `always`
- **Security**: Hardened configuration with scram-sha-256 auth

---

## Health Check Thresholds

### Market Data
- **Stale Threshold**: 30 minutes (configurable via `HEALTH_STALE_MARKET_MINUTES`)
- **Critical**: All symbols stale
- **Warning**: Some symbols stale

### Signal Monitor
- **Stale Threshold**: 30 minutes (configurable via `HEALTH_MONITOR_STALE_MINUTES`)
- **Critical**: Service not running OR last cycle > 30 minutes
- **Warning**: No cycles recorded yet

### Market Updater
- **Stale Threshold**: 30 minutes (uses market data freshness)
- **Critical**: No fresh data detected (service likely stopped)

---

## Monitoring Tools Available

### Automated Monitoring Scripts

1. **Health Monitor** (`scripts/health_monitor.sh`)
   - **Purpose**: Continuous monitoring with automatic recovery
   - **Features**:
     - Monitors all Docker services
     - Automatically restarts unhealthy services
     - Rebuilds services after max restart attempts
     - Checks database connectivity
     - Logs to `logs/health_monitor.log`
   - **Installation**: `./install_health_monitor.sh` (creates systemd service)
   - **Interval**: 60 seconds

2. **Dashboard Health Check** (`scripts/dashboard_health_check.sh`)
   - **Purpose**: Verifies dashboard data quality and sends Telegram alerts
   - **Features**:
     - Checks `/api/market/top-coins-data` endpoint
     - Validates JSON response
     - Verifies minimum coin count (default: 5)
     - Sends Telegram notifications on failure
   - **Installation**: `./install_dashboard_health_check.sh` (creates systemd timer)
   - **Interval**: Every 20 minutes

### Manual Health Check Scripts

1. **Runtime Health Check** (`scripts/check_runtime_health_aws.sh`)
   - One-time comprehensive health check
   - Reports warnings and failures

2. **EC2 IP and Health Verification** (`scripts/verify_ec2_ip_and_health.sh`)
   - Verify EC2 outbound IP and backend health
   - For IP whitelisting verification

3. **Backend Status Check** (`check_backend_status.sh`)
   - Quick backend status check

4. **Market Data Status** (`scripts/verify_market_data_status.sh`)
   - Verify market data freshness and quality

5. **Telegram Status Check** (`check_telegram_status.sh`)
   - Verify Telegram bot configuration and status

---

## Quick Health Check Commands

### From Local Machine (Public Endpoint)

```bash
# Full health status
curl -s https://dashboard.hilovivo.com/api/health/system | jq .

# Check specific components
curl -s https://dashboard.hilovivo.com/api/health/system | jq '{
  global_status: .global_status,
  market_updater: .market_updater.status,
  market_data: .market_data.stale_symbols,
  signal_monitor: .signal_monitor.status,
  telegram: .telegram.enabled
}'

# Check market data freshness
curl -s https://dashboard.hilovivo.com/api/health/system | jq '.market_data'

# Check market updater
curl -s https://dashboard.hilovivo.com/api/health/system | jq '.market_updater'

# Global status only
curl -s https://dashboard.hilovivo.com/api/health/system | jq -r '.global_status'
```

### From EC2 (SSH - Internal Endpoint)

```bash
# SSH to EC2
ssh ubuntu@47.130.143.159

# Full health status
curl -s http://localhost:8002/api/health/system | jq .

# Check Docker services
docker compose --profile aws ps

# Check service logs
docker compose --profile aws logs --tail 100 backend-aws
docker compose --profile aws logs --tail 100 market-updater-aws

# Check service health
docker compose --profile aws ps --format "table {{.Name}}\t{{.Status}}\t{{.Health}}"
```

---

## Service Dependencies

```
Frontend (nginx) → Backend (8002) → Database (5432)
                              ↓
                    Market Updater → Database
                              ↓
                    Signal Monitor → Database
                              ↓
                    Telegram Notifier → Telegram API
```

**Critical Path**:
1. Database must be healthy (all services depend on it)
2. Backend must be healthy (frontend and market updater depend on it)
3. Market Updater must be running (for fresh market data)
4. Signal Monitor must be running (for trading signals)

---

## Common Issues and Troubleshooting

### Issue: Market Data Stale

**Symptoms**:
- `market_data.stale_symbols > 0`
- `market_data.max_age_minutes > 30`
- `market_updater.status = "FAIL"`

**Possible Causes**:
1. Market updater service stopped
2. Database connection issues
3. Exchange API rate limiting
4. Network connectivity problems

**Resolution**:
```bash
# Check market updater container
docker compose --profile aws ps market-updater-aws

# Restart market updater
docker compose --profile aws restart market-updater-aws

# Check logs
docker compose --profile aws logs --tail 100 market-updater-aws
```

### Issue: Signal Monitor Not Running

**Symptoms**:
- `signal_monitor.status = "FAIL"`
- `signal_monitor.is_running = false`
- `signal_monitor.last_cycle_age_minutes > 30`

**Possible Causes**:
1. Backend service restart
2. Signal monitor service failed to start
3. Database connection issues

**Resolution**:
```bash
# Check backend container
docker compose --profile aws ps backend-aws

# Restart backend
docker compose --profile aws restart backend-aws

# Check logs for signal monitor errors
docker compose --profile aws logs --tail 200 backend-aws | grep -i "signal"
```

### Issue: Telegram Not Enabled

**Symptoms**:
- `telegram.status = "FAIL"`
- `telegram.enabled = false`

**Possible Causes**:
1. `RUN_TELEGRAM` not set to `true` in `.env.aws`
2. Missing `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID`
3. Telegram service disabled intentionally

**Resolution**:
```bash
# Check .env.aws file (on EC2)
ssh ubuntu@47.130.143.159
cat .env.aws | grep TELEGRAM

# Verify Telegram config
curl -s http://localhost:8002/api/health/system | jq .telegram

# If needed, update .env.aws and restart
docker compose --profile aws restart backend-aws
```

### Issue: Global Status FAIL

**Symptoms**:
- `global_status = "FAIL"`

**Action**:
1. Check all component statuses individually
2. Identify which component(s) are failing
3. Follow component-specific troubleshooting steps
4. Check Docker service status
5. Review application logs

---

## Configuration Files

### Environment Variables (`.env.aws`)

Key variables for health monitoring:
- `HEALTH_STALE_MARKET_MINUTES`: Market data stale threshold (default: 30)
- `HEALTH_MONITOR_STALE_MINUTES`: Signal monitor stale threshold (default: 30)
- `RUN_TELEGRAM`: Enable Telegram (true/false)
- `TELEGRAM_BOT_TOKEN`: Telegram bot token
- `TELEGRAM_CHAT_ID`: Telegram chat ID

### Docker Compose

- **File**: `docker-compose.yml`
- **Profile**: `aws`
- **Services**: `backend-aws`, `frontend-aws`, `market-updater-aws`, `db`

---

## Monitoring Setup Recommendations

### External Monitoring (Recommended)

1. **UptimeRobot** (Free Tier)
   - Monitor: `https://dashboard.hilovivo.com/api/health/system`
   - Interval: 5 minutes
   - Alert on: HTTP != 200 OR `global_status != "PASS"`

2. **AWS CloudWatch Synthetics**
   - Create canary to check health endpoint
   - Set up alarms for failures

3. **Custom Script** (Cron)
   - Run every 5 minutes
   - Check `global_status`, `market_updater.status`, `market_data.stale_symbols`
   - Send alerts via email/webhook

### Internal Monitoring

1. **Docker Healthchecks**
   - All services have healthchecks configured
   - Docker Compose monitors container health
   - Auto-restart on failure

2. **Application Logs**
   - Backend logs include health check results
   - Monitor for repeated failures

3. **Health Monitor Service**
   - Install: `./install_health_monitor.sh`
   - Runs every 60 seconds
   - Auto-recovery for unhealthy services

---

## Best Practices

1. **Monitor Public Endpoint**: Use `https://dashboard.hilovivo.com/api/health/system` for external monitoring
2. **Check Regularly**: Set up automated checks every 5 minutes
3. **Alert on FAIL**: Immediate alert when `global_status = "FAIL"`
4. **Monitor Trends**: Track `stale_symbols` and `max_age_minutes` over time
5. **Log Analysis**: Review logs when health checks fail
6. **Service Restarts**: Monitor restart frequency (may indicate instability)
7. **Install Health Monitor**: Enable automated health monitoring with recovery

---

## Summary

The AWS system has comprehensive health monitoring with:

✅ **Multiple Health Endpoints**: Basic and system-level checks  
✅ **Component Monitoring**: 5 critical services monitored  
✅ **Real-time Status**: No caching, always fresh data  
✅ **Docker Healthchecks**: Automatic container health monitoring  
✅ **Detailed Metrics**: Granular status for each component  
✅ **External Monitoring Ready**: Public endpoints for external tools  
✅ **Automated Recovery**: Health monitor with auto-restart  
✅ **Data Quality Checks**: Dashboard health check with Telegram alerts  

**Recommended Actions**:
1. ✅ Set up external monitoring (UptimeRobot or CloudWatch)
2. ✅ Configure alerts for `global_status = "FAIL"`
3. ✅ Monitor `market_data.stale_symbols` trend
4. ✅ Review health status daily
5. ✅ Install health monitor service (auto-recovery)
6. ✅ Install dashboard health check timer (data quality)

---

## Related Documentation

- **Health Monitoring Tools**: `docs/AWS_HEALTH_MONITORING_TOOLS.md` - Quick reference for all monitoring scripts and tools
- **Executive Summary**: `docs/AWS_HEALTH_MONITORING_SUMMARY.md` - Quick overview and status check commands
- **External Monitoring Setup**: `docs/monitoring/HEALTH_MONITORING.md` - External monitoring configuration (UptimeRobot, CloudWatch)
- **Comprehensive Review**: `docs/AWS_SYSTEM_STATUS_REVIEW.md` - Detailed system status review

---

**Last Updated**: 2026-01-08  
**Next Review**: After any major deployment or service changes

