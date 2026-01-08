# Health Monitoring Setup

**Purpose**: External health monitoring for AWS deployment to detect failures and alert.

**Last Updated**: 2026-01-08

---

## Overview

The AWS deployment exposes health endpoints that can be monitored externally. This document describes how to set up monitoring and alerts.

---

## Health Endpoints

### Public Endpoints

**System Health** (Recommended):
```
https://dashboard.hilovivo.com/api/health/system
```

**Basic Health**:
```
https://dashboard.hilovivo.com/api/health
```

**Frontend**:
```
https://dashboard.hilovivo.com
```

### Internal Endpoints (SSH to EC2)

**System Health**:
```
http://localhost:8002/api/health/system
```

**Basic Health**:
```
http://localhost:8002/api/health
```

---

## Health Check Response Format

### `/api/health/system`

```json
{
  "global_status": "PASS" | "FAIL",
  "timestamp": "2026-01-08T12:00:00.000000+00:00",
  "market_data": {
    "status": "PASS" | "FAIL",
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
    "status": "PASS" | "FAIL",
    "is_running": true,
    "last_cycle_age_minutes": 16.33
  },
  "telegram": {
    "status": "PASS" | "FAIL",
    "enabled": false,
    "chat_id_set": true,
    "last_send_ok": null
  },
  "trade_system": {
    "status": "PASS" | "FAIL",
    "open_orders": 22,
    "max_open_orders": null,
    "last_check_ok": true
  }
}
```

---

## Monitoring Setup Options

### Option 1: UptimeRobot (Free Tier)

**Setup**:
1. Create account at https://uptimerobot.com
2. Add new monitor:
   - **Type**: HTTP(s)
   - **URL**: `https://dashboard.hilovivo.com/api/health/system`
   - **Interval**: 5 minutes
   - **Alert Contacts**: Email, SMS, or webhook

**Alert Conditions**:
- HTTP status != 200
- Response time > 10 seconds
- Response contains `"global_status": "FAIL"`

**Advanced Check** (using keyword monitoring):
- **Keyword**: `"market_updater":{"status":"PASS"`
- **Alert if**: Keyword not found

### Option 2: AWS CloudWatch

**Setup**:
1. Create CloudWatch Synthetics canary:
   ```bash
   aws synthetics create-canary \
     --name atp-health-check \
     --artifact-s3-location s3://your-bucket/atp-health \
     --execution-role-arn arn:aws:iam::ACCOUNT:role/CloudWatchSyntheticsRole \
     --schedule "rate(5 minutes)" \
     --code '{
       "Handler": "pageLoadBlueprint.handler",
       "Script": "var synthetics = require(\"Synthetics\");\nvar log = require(\"Log\");\n\nconst apiRequestStep = async function () {\n  const requestOptions = {\n    hostname: \"dashboard.hilovivo.com\",\n    method: \"GET\",\n    path: \"/api/health/system\",\n    port: 443,\n    protocol: \"https:\"\n  };\n  \n  const response = await synthetics.executeHttpStep(\"health-check\", requestOptions);\n  const body = JSON.parse(response.body);\n  \n  if (body.global_status !== \"PASS\") {\n    throw new Error(\"Health check failed: \" + JSON.stringify(body));\n  }\n  \n  if (body.market_updater.status !== \"PASS\") {\n    throw new Error(\"Market updater failed\");\n  }\n  \n  if (body.market_data.stale_symbols > 0) {\n    throw new Error(\"Market data has stale symbols: \" + body.market_data.stale_symbols);\n  }\n};\n\nexports.handler = async () => {\n  return await apiRequestStep();\n};"
     }'
   ```

2. Set up CloudWatch Alarm:
   ```bash
   aws cloudwatch put-metric-alarm \
     --alarm-name atp-health-failure \
     --alarm-description "Alert when ATP health check fails" \
     --metric-name Failed \
     --namespace CloudWatchSynthetics \
     --statistic Sum \
     --period 300 \
     --evaluation-periods 1 \
     --threshold 1 \
     --comparison-operator GreaterThanOrEqualToThreshold
   ```

### Option 3: Custom Script with Cron

**On EC2 or monitoring server**:

```bash
#!/bin/bash
# /home/ubuntu/scripts/monitor_health.sh

HEALTH_URL="https://dashboard.hilovivo.com/api/health/system"
ALERT_EMAIL="your-email@example.com"

RESPONSE=$(curl -sS "$HEALTH_URL" || echo "")
if [ -z "$RESPONSE" ]; then
  echo "Health endpoint not responding" | mail -s "ATP Health Check Failed" "$ALERT_EMAIL"
  exit 1
fi

# Check global status
GLOBAL_STATUS=$(echo "$RESPONSE" | jq -r '.global_status // "UNKNOWN"')
if [ "$GLOBAL_STATUS" != "PASS" ]; then
  echo "Global status: $GLOBAL_STATUS" | mail -s "ATP Health Check Failed" "$ALERT_EMAIL"
  exit 1
fi

# Check market updater
MARKET_UPDATER_STATUS=$(echo "$RESPONSE" | jq -r '.market_updater.status // "UNKNOWN"')
if [ "$MARKET_UPDATER_STATUS" != "PASS" ]; then
  echo "Market updater status: $MARKET_UPDATER_STATUS" | mail -s "ATP Market Updater Failed" "$ALERT_EMAIL"
  exit 1
fi

# Check stale symbols
STALE_SYMBOLS=$(echo "$RESPONSE" | jq -r '.market_data.stale_symbols // "UNKNOWN"')
if [ "$STALE_SYMBOLS" != "0" ] && [ "$STALE_SYMBOLS" != "null" ]; then
  echo "Market data has $STALE_SYMBOLS stale symbols" | mail -s "ATP Market Data Stale" "$ALERT_EMAIL"
  exit 1
fi

echo "Health check passed"
```

**Add to crontab**:
```bash
# Run every 5 minutes
*/5 * * * * /home/ubuntu/scripts/monitor_health.sh
```

### Option 4: GitHub Actions Scheduled Workflow

**Create `.github/workflows/health_monitor.yml`**:
```yaml
name: Health Monitor

on:
  schedule:
    - cron: '*/5 * * * *'  # Every 5 minutes
  workflow_dispatch:

jobs:
  check-health:
    runs-on: ubuntu-latest
    steps:
      - name: Check Health Endpoint
        run: |
          RESPONSE=$(curl -sS https://dashboard.hilovivo.com/api/health/system)
          GLOBAL_STATUS=$(echo "$RESPONSE" | jq -r '.global_status')
          MARKET_UPDATER=$(echo "$RESPONSE" | jq -r '.market_updater.status')
          STALE_SYMBOLS=$(echo "$RESPONSE" | jq -r '.market_data.stale_symbols')
          
          if [ "$GLOBAL_STATUS" != "PASS" ] || [ "$MARKET_UPDATER" != "PASS" ] || [ "$STALE_SYMBOLS" != "0" ]; then
            echo "Health check failed"
            echo "Global: $GLOBAL_STATUS"
            echo "Market Updater: $MARKET_UPDATER"
            echo "Stale Symbols: $STALE_SYMBOLS"
            exit 1
          fi
```

---

## Alert Thresholds

### Critical (Immediate Alert)

- **Global Status**: `FAIL`
- **Market Updater**: `status != "PASS"` or `is_running != true`
- **Market Data**: `stale_symbols > 0` or `max_age_minutes > 30`
- **HTTP Status**: `!= 200`
- **Response Time**: `> 10 seconds`

### Warning (Alert After 2 Failures)

- **Market Data**: `max_age_minutes > 15` but `<= 30`
- **Signal Monitor**: `status != "PASS"` or `last_cycle_age_minutes > 60`
- **Trade System**: `last_check_ok != true`

### Info (Log Only)

- **Telegram**: `enabled: false` (expected if not configured)
- **Trade System**: `open_orders` count changes

---

## Integration with Telegram

If Telegram is enabled, you can send alerts to the configured channel:

```bash
# On EC2
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}" \
  -d "text=🚨 ATP Health Check Failed: Market updater not running"
```

---

## Monitoring Best Practices

1. **Monitor from External Location**: Don't monitor from the same EC2 instance
2. **Multiple Endpoints**: Monitor both public (via domain) and internal (via SSH) endpoints
3. **Alert Fatigue**: Set appropriate thresholds to avoid false positives
4. **Documentation**: Keep alert runbooks updated
5. **Regular Testing**: Test alert delivery monthly

---

## Quick Health Check Commands

**From Local Machine**:
```bash
# Public endpoint
curl -s https://dashboard.hilovivo.com/api/health/system | jq .

# Check specific metrics
curl -s https://dashboard.hilovivo.com/api/health/system | jq '{
  market_updater: .market_updater.status,
  market_data: .market_data.stale_symbols,
  telegram: .telegram.enabled
}'
```

**From EC2 (SSH)**:
```bash
ssh ubuntu@47.130.143.159 "curl -s http://localhost:8002/api/health/system | jq ."
```

---

**Note**: This monitoring setup is optional but recommended for production deployments. Choose the option that best fits your infrastructure and alerting needs.

