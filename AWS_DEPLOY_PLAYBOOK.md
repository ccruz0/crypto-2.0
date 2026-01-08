# AWS Deploy-by-Commit Playbook

**Purpose**: Standardized, repeatable, and safe deployment procedure for AWS EC2.

**Last Updated**: 2026-01-08

---

## Overview

The AWS deployment uses a **deploy-by-commit** workflow where:
- Each commit hash corresponds to exactly what's running on AWS
- GitHub is the single source of truth for code
- `.env.aws` is the single source of truth for environment variables (not in git)
- Deployment is automated via GitHub Actions or manual via standardized scripts

---

## Prerequisites

### On AWS EC2

- Docker and Docker Compose installed
- Repository cloned at `/home/ubuntu/automated-trading-platform`
- `.env.aws` file configured (not in git)
- SSH access configured
- Required ports open (22 for SSH, 80/443 for Nginx, 3000/8002 for services)

### In GitHub

- Repository secrets configured:
  - `EC2_HOST`: EC2 instance IP address
  - `EC2_KEY`: SSH private key for EC2 access

---

## Standard Deployment

### Option 1: Automated (GitHub Actions)

**Trigger**: Push to `main` branch

**Process**:
1. GitHub Actions workflow (`.github/workflows/deploy.yml`) triggers
2. Code is synced to EC2 via rsync
3. `scripts/deploy_aws.sh` is executed on EC2
4. Health checks verify deployment success

**Verification**:
- Check GitHub Actions workflow status
- Verify health endpoint: `curl https://dashboard.hilovivo.com/api/health/system`

### Option 2: Manual (On EC2)

**Command**:
```bash
ssh ubuntu@<EC2_IP>
cd ~/automated-trading-platform
bash scripts/deploy_aws.sh
```

**What it does**:
1. Fetches latest from `origin/main`
2. Resets to `origin/main` (ensures clean state)
3. Pulls Docker images (if applicable)
4. Builds and starts services with `docker compose --profile aws up -d --build`
5. Waits for services to start
6. Verifies service status
7. Checks health endpoint

**Expected Output**:
```
==========================================
AWS Deploy-by-Commit
==========================================

📁 Repository root: /home/ubuntu/automated-trading-platform

📥 Fetching latest from origin...
🔀 Checking out main branch...
🔄 Resetting to origin/main...

✅ Git state:
   HEAD: fd44bca (fd44bca06e6ff0ddd3147a46aaa6e89b06a6f580)
   Branch: main
   Status: 0 uncommitted files

🐳 Pulling Docker images...
🚀 Building and starting services...
⏳ Waiting for services to start (15 seconds)...

✅ Service status:
[Service list]

🏥 Health check...
   Market Updater: PASS
   Market Data Stale Symbols: 0
   Market Data Max Age: 1.07 minutes
   Telegram Enabled: false

==========================================
✅ Deployment completed successfully!
==========================================
```

---

## Rollback Procedure

### When to Rollback

- Deployment fails health checks
- Services fail to start
- Critical bugs detected in new code
- Performance degradation

### Rollback Command

```bash
# On EC2
cd ~/automated-trading-platform
bash scripts/rollback_aws.sh <commit-sha>
```

**Example**:
```bash
# Rollback to previous known good commit
bash scripts/rollback_aws.sh fd44bca06e6ff0ddd3147a46aaa6e89b06a6f580

# Or use short SHA
bash scripts/rollback_aws.sh fd44bca
```

**What it does**:
1. Fetches latest from origin
2. Verifies target commit exists
3. Checks out target commit
4. Rebuilds and restarts services
5. Verifies health

**Finding Previous Commits**:
```bash
# List recent commits
git log --oneline -10

# Show commit details
git show <commit-sha>
```

---

## Health Checks

### Local Health Check

```bash
# Basic health
curl -s http://localhost:8002/api/health | jq .

# System health (detailed)
curl -s http://localhost:8002/api/health/system | jq .
```

### Public Health Check

```bash
# Frontend
curl -sI https://dashboard.hilovivo.com | head -5

# API health
curl -s https://dashboard.hilovivo.com/api/health/system | jq .
```

### Expected Health Status

**Market Updater**: `PASS`
- `is_running`: `true`
- `last_heartbeat_age_minutes`: < 5 minutes

**Market Data**: `PASS`
- `stale_symbols`: `0`
- `max_age_minutes`: < 5 minutes

**Telegram**: `FAIL` (expected if disabled)
- `enabled`: `false` (unless `RUN_TELEGRAM=1` and secrets configured)

**Trade System**: `PASS`
- `open_orders`: Number of open orders
- `last_check_ok`: `true`

---

## Failure Modes and Recovery

### Failure: Health Check Fails

**Symptoms**:
- `market_updater.status` is not `PASS`
- `market_data.stale_symbols` > 0
- Services not responding

**Recovery**:
1. Check service logs: `docker compose --profile aws logs --tail 100 <service-name>`
2. Check service status: `docker compose --profile aws ps`
3. Restart failed service: `docker compose --profile aws restart <service-name>`
4. If persistent, rollback: `bash scripts/rollback_aws.sh <previous-commit>`

### Failure: Services Won't Start

**Symptoms**:
- `docker compose --profile aws ps` shows services as "Exited" or "Restarting"
- Health endpoint returns 503 or connection refused

**Recovery**:
1. Check logs: `docker compose --profile aws logs <service-name>`
2. Verify `.env.aws` exists and has required variables
3. Check Docker resources: `docker system df`
4. Rebuild: `docker compose --profile aws up -d --build --force-recreate`
5. If persistent, rollback

### Failure: Git State Mismatch

**Symptoms**:
- Deployed code doesn't match expected commit
- `git rev-parse HEAD` doesn't match expected SHA

**Recovery**:
1. Verify git state: `git status` and `git rev-parse HEAD`
2. Reset to expected commit: `git fetch origin && git reset --hard origin/main`
3. Redeploy: `bash scripts/deploy_aws.sh`

### Failure: Database Connection Errors

**Symptoms**:
- Backend logs show database connection errors
- Health endpoint shows database errors

**Recovery**:
1. Verify database is running: `docker compose --profile aws ps db`
2. Check database logs: `docker compose --profile aws logs db`
3. Verify `DATABASE_URL` in `.env.aws` is correct
4. Restart database: `docker compose --profile aws restart db`
5. Wait for database to be healthy before restarting backend

### Failure: Port Conflicts

**Symptoms**:
- Services fail to start with "port already in use" errors
- `ss -lntp | grep <port>` shows unexpected listeners

**Recovery**:
1. Identify process using port: `sudo lsof -i :<port>`
2. Stop conflicting service or change port in `docker-compose.yml`
3. Redeploy

---

## Environment Variables

### Required Variables (`.env.aws`)

**Database**:
- `POSTGRES_DB` (default: `atp`)
- `POSTGRES_USER` (default: `trader`)
- `POSTGRES_PASSWORD` (default: `traderpass`)
- `DATABASE_URL` (format: `postgresql://user:pass@db:5432/dbname`)

**API Configuration**:
- `API_BASE_URL` (e.g., `http://54.254.150.31:8000`)
- `FRONTEND_URL` (e.g., `http://54.254.150.31:3000`)
- `NEXT_PUBLIC_API_URL` (e.g., `http://54.254.150.31:8000/api`)

**Exchange API** (Crypto.com):
- `EXCHANGE_CUSTOM_API_KEY` (required)
- `EXCHANGE_CUSTOM_API_SECRET` (required)
- `EXCHANGE_CUSTOM_BASE_URL` (e.g., `https://api.crypto.com/exchange/v1`)
- `USE_CRYPTO_PROXY` (set to `false` for direct connection)
- `LIVE_TRADING` (set to `true` for production)

**Security**:
- `ADMIN_ACTIONS_KEY` (generated, 32-byte hex string)
- `DIAGNOSTICS_API_KEY` (generated, 32-byte hex string)

**Telegram** (optional, disabled by default):
- `RUN_TELEGRAM` (set to `1` or `true` to enable, defaults to `false`)
- `TELEGRAM_BOT_TOKEN` (required if `RUN_TELEGRAM=1`)
- `TELEGRAM_CHAT_ID` (required if `RUN_TELEGRAM=1`)

**Note**: Values are secrets and must not be committed to git. Only variable names are documented here.

---

## Telegram Configuration

### Default Behavior

**Telegram is OFF by default** for safety. Even if `RUN_TELEGRAM=1`, Telegram will be disabled if:
- `TELEGRAM_BOT_TOKEN` is missing
- `TELEGRAM_CHAT_ID` is missing

### Enabling Telegram

1. Set `RUN_TELEGRAM=1` in `.env.aws`
2. Set `TELEGRAM_BOT_TOKEN` in `.env.aws`
3. Set `TELEGRAM_CHAT_ID` in `.env.aws`
4. Restart backend: `docker compose --profile aws restart backend-aws`
5. Verify: `curl -s http://localhost:8002/api/health/system | jq .telegram`

**Expected Result**:
```json
{
  "status": "PASS",
  "enabled": true,
  "chat_id_set": true,
  "last_send_ok": true
}
```

### Disabling Telegram

1. Set `RUN_TELEGRAM=0` or remove it from `.env.aws`
2. Restart backend: `docker compose --profile aws restart backend-aws`
3. Verify: `curl -s http://localhost:8002/api/health/system | jq .telegram`

**Expected Result**:
```json
{
  "status": "FAIL",
  "enabled": false,
  "chat_id_set": true,
  "last_send_ok": null
}
```

---

## Verification Commands

### Pre-Deployment

```bash
# Verify git state
git status
git rev-parse HEAD
git log -1 --oneline

# Verify .env.aws exists
ls -la .env.aws

# Verify Docker is running
docker ps
docker compose --profile aws config
```

### Post-Deployment

```bash
# Verify git state matches expected commit
git rev-parse HEAD
# Should match expected commit SHA

# Verify services are running
docker compose --profile aws ps
# All services should show "Up" and "healthy"

# Verify health
curl -s http://localhost:8002/api/health/system | jq '{
  market_updater: .market_updater.status,
  market_data: .market_data.stale_symbols,
  telegram: .telegram.enabled
}'

# Verify public endpoints
curl -sI https://dashboard.hilovivo.com | head -1
curl -s https://dashboard.hilovivo.com/api/health/system | jq .status
```

---

## Troubleshooting

### Services Not Starting

1. **Check logs**: `docker compose --profile aws logs <service-name>`
2. **Check status**: `docker compose --profile aws ps`
3. **Check resources**: `docker system df` and `free -h`
4. **Rebuild**: `docker compose --profile aws up -d --build --force-recreate`

### Health Check Fails

1. **Check service logs**: `docker compose --profile aws logs backend-aws --tail 100`
2. **Check database**: `docker compose --profile aws logs db --tail 100`
3. **Check market updater**: `docker compose --profile aws logs market-updater-aws --tail 100`
4. **Verify env vars**: `docker compose --profile aws config | grep -A 5 <service-name>`

### Git State Issues

1. **Check current state**: `git status` and `git rev-parse HEAD`
2. **Reset to clean state**: `git fetch origin && git reset --hard origin/main`
3. **Verify remote**: `git remote -v`

### Database Issues

1. **Check database status**: `docker compose --profile aws ps db`
2. **Check database logs**: `docker compose --profile aws logs db --tail 100`
3. **Verify connection**: `docker exec automated-trading-platform-backend-aws-1 python -c "import psycopg2; conn = psycopg2.connect('postgresql://trader:traderpass@db:5432/atp'); print('OK'); conn.close()"`

---

## Best Practices

1. **Always verify git state** before and after deployment
2. **Always check health** after deployment
3. **Keep rollback commit SHA** handy
4. **Never commit `.env.aws`** to git
5. **Test rollback procedure** periodically
6. **Monitor health endpoints** after deployment
7. **Document any manual changes** made on EC2

---

## Quick Reference

### Deploy
```bash
bash scripts/deploy_aws.sh
```

### Rollback
```bash
bash scripts/rollback_aws.sh <commit-sha>
```

### Check Health
```bash
curl -s http://localhost:8002/api/health/system | jq .
```

### Check Services
```bash
docker compose --profile aws ps
```

### Check Logs
```bash
docker compose --profile aws logs --tail 100 <service-name>
```

### Check Git State
```bash
git rev-parse HEAD
git status
```

---

**Report Issues**: If deployment fails or unexpected behavior occurs, check logs and health endpoints before rolling back. Document the issue and commit SHA for investigation.

