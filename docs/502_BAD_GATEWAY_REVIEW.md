# 502 Bad Gateway Error - Review & Troubleshooting Guide

## What is a 502 Bad Gateway Error?

A **502 Bad Gateway** error means that nginx (the reverse proxy) is running and receiving requests, but **cannot connect to the upstream services** (backend or frontend). This is a connectivity issue between nginx and the application containers.

## Architecture Overview

```
Internet → Nginx (port 443/80) → Backend (localhost:8002) or Frontend (localhost:3000)
```

Based on your nginx configuration (`nginx/dashboard.conf`):
- **Frontend**: `http://localhost:3000` (Next.js)
- **Backend API**: `http://localhost:8002` (FastAPI)

## Common Causes

### 1. **Backend/Frontend Containers Not Running**
   - Containers crashed or were stopped
   - Docker Compose services not started
   - Containers failed to start due to errors

### 2. **Services Not Listening on Expected Ports**
   - Backend not listening on port 8002
   - Frontend not listening on port 3000
   - Port conflicts or misconfiguration

### 3. **Services Unhealthy or Starting**
   - Containers are running but healthchecks are failing
   - Services are still starting up (may take 2-3 minutes)
   - Application errors preventing proper startup

### 4. **Network Connectivity Issues**
   - Docker network problems
   - Firewall blocking connections
   - nginx needs to reconnect after backend restart

### 5. **Nginx Configuration Issues**
   - Nginx needs restart after backend changes
   - Upstream server configuration incorrect
   - Timeout settings too low

## Quick Diagnostic Steps

### Step 1: Run Automated Diagnostic Script

The fastest way to diagnose the issue:

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/debug_dashboard_remote.sh
```

This script checks:
- ✅ All container statuses and health
- ✅ Backend API connectivity
- ✅ Frontend availability
- ✅ Nginx status
- ✅ Database connectivity
- ✅ Recent error logs

### Step 2: Manual Checks (if needed)

#### Check Container Status
```bash
# SSH to AWS server
ssh hilovivo-aws

# Check Docker Compose services
cd ~/automated-trading-platform
docker compose --profile aws ps

# Check specific containers
docker ps --filter "name=backend-aws"
docker ps --filter "name=frontend-aws"
```

#### Check Backend Health
```bash
# From AWS server
curl http://localhost:8002/health
curl http://localhost:8002/ping_fast

# Check if port is listening
sudo netstat -tlnp | grep 8002
# or
sudo ss -tlnp | grep 8002
```

#### Check Frontend Health
```bash
# From AWS server
curl http://localhost:3000/

# Check if port is listening
sudo netstat -tlnp | grep 3000
```

#### Check Nginx Status
```bash
# From AWS server
sudo systemctl status nginx
sudo nginx -t  # Test configuration

# Check nginx error logs
sudo tail -20 /var/log/nginx/error.log | grep -E "502|upstream|connect|refused"
```

## Solutions

### Solution 1: Restart Nginx (Most Common Fix)

If the backend/frontend are running but nginx can't connect:

```bash
# Option A: Use the automated script
bash restart_nginx_aws.sh

# Option B: SSH and restart manually
ssh hilovivo-aws "sudo systemctl restart nginx"
```

**Why this works**: After backend restarts, nginx may have stale connections. Restarting nginx forces it to reconnect.

### Solution 2: Restart Backend Container

If the backend container is unhealthy or not responding:

```bash
# SSH to AWS
ssh hilovivo-aws

# Restart backend
cd ~/automated-trading-platform
docker compose --profile aws restart backend-aws

# Wait for healthcheck (up to 180 seconds)
docker compose --profile aws ps backend-aws

# Then restart nginx
sudo systemctl restart nginx
```

### Solution 3: Restart All Services

If multiple services are affected:

```bash
# SSH to AWS
ssh hilovivo-aws

# Restart all services
cd ~/automated-trading-platform
docker compose --profile aws restart

# Wait for services to be healthy
sleep 30
docker compose --profile aws ps

# Restart nginx
sudo systemctl restart nginx
```

### Solution 4: Check Container Logs

If containers are crashing:

```bash
# SSH to AWS
ssh hilovivo-aws

# Check backend logs
cd ~/automated-trading-platform
docker compose --profile aws logs --tail=100 backend-aws

# Check frontend logs
docker compose --profile aws logs --tail=100 frontend-aws

# Check for errors
docker compose --profile aws logs --tail=200 | grep -iE "error|exception|traceback|fatal"
```

### Solution 5: Verify Docker Network

If there are network connectivity issues:

```bash
# SSH to AWS
ssh hilovivo-aws

# Check Docker networks
docker network ls
docker network inspect automated-trading-platform_default

# Test connectivity from another container
docker exec market-updater-aws curl http://backend-aws:8002/ping_fast
```

## Decision Tree

```
502 Bad Gateway
│
├─ Run: bash scripts/debug_dashboard_remote.sh
│
├─ Backend container not running?
│  └─→ docker compose --profile aws up -d backend-aws
│
├─ Backend unhealthy?
│  └─→ Check logs: docker compose --profile aws logs backend-aws
│  └─→ Restart: docker compose --profile aws restart backend-aws
│
├─ Frontend container not running?
│  └─→ docker compose --profile aws up -d frontend-aws
│
├─ Backend healthy but nginx can't connect?
│  └─→ sudo systemctl restart nginx
│
└─ All containers healthy but still 502?
   └─→ Check nginx config: sudo nginx -t
   └─→ Check nginx logs: sudo tail -50 /var/log/nginx/error.log
   └─→ Verify ports: sudo netstat -tlnp | grep -E "8002|3000"
```

## Prevention

### 1. Monitor Container Health
- Set up health monitoring (see `docs/runbooks/dashboard_healthcheck.md`)
- Use healthchecks in docker-compose.yml (already configured)

### 2. Automatic Nginx Reload
Consider adding a healthcheck script that automatically restarts nginx if backend becomes unreachable:

```bash
# Check if backend is reachable, restart nginx if not
if ! curl -f http://localhost:8002/health >/dev/null 2>&1; then
    sudo systemctl restart nginx
fi
```

### 3. Increase Timeouts
If you see 504 (Gateway Timeout) instead of 502, increase nginx timeouts in `nginx/dashboard.conf`:

```nginx
proxy_connect_timeout 120s;
proxy_send_timeout 120s;
proxy_read_timeout 120s;
```

## Related Documentation

- **Dashboard Health Check Runbook**: `docs/runbooks/dashboard_healthcheck.md`
- **Nginx Restart Instructions**: `INSTRUCCIONES_REINICIAR_NGINX.md`
- **Diagnostic Script**: `scripts/debug_dashboard_remote.sh`
- **Nginx Configuration**: `nginx/dashboard.conf`

## Quick Reference Commands

```bash
# Full diagnostic
bash scripts/debug_dashboard_remote.sh

# Restart nginx
bash restart_nginx_aws.sh

# Check container status
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws ps"

# Check backend health
ssh hilovivo-aws "curl http://localhost:8002/health"

# View backend logs
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws logs --tail=50 backend-aws"

# Restart all services
ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws restart && sudo systemctl restart nginx"
```

## Expected Behavior After Fix

After resolving the 502 error:
- ✅ Dashboard loads at `https://dashboard.hilovivo.com`
- ✅ API calls to `/api/*` return 200 OK
- ✅ All containers show "healthy" status
- ✅ No 502 errors in nginx error logs

---

**Last Updated**: Based on current nginx configuration and docker-compose setup
**Environment**: AWS production (hilovivo-aws)






