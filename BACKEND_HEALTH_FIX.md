# Backend Health Error - Diagnostic and Fix Guide

## Problem
The dashboard shows "Backend Health: ERROR" with the message:
> "Backend service temporarily unavailable. Please ensure services are running."

This error comes from nginx when it cannot reach the backend service on port 8002.

## Root Cause
The backend container (`backend-aws`) is either:
1. Not running
2. Running but not responding on port 8002
3. Crashed or in an unhealthy state

## Diagnostic Steps

### Step 1: Check Backend Container Status

**On AWS Server (SSH):**
```bash
cd ~/automated-trading-platform
docker compose --profile aws ps backend-aws
```

**Expected Output:**
```
NAME                IMAGE                    STATUS
backend-aws         ...                      Up X minutes (healthy)
```

**If container is not running:**
- Status will show "Exited" or container won't appear
- Check logs: `docker compose --profile aws logs --tail=50 backend-aws`

### Step 2: Check Backend Health Endpoint

**On AWS Server:**
```bash
# Test if backend responds locally
curl -s http://localhost:8002/ping_fast
curl -s http://localhost:8002/health
curl -s http://localhost:8002/api/monitoring/summary
```

**Expected:**
- `/ping_fast` should return quickly
- `/health` should return JSON with status
- `/api/monitoring/summary` should return monitoring data

**If these fail:**
- Backend is not listening on port 8002
- Check container logs for startup errors

### Step 3: Check Backend Logs

```bash
# Recent logs
docker compose --profile aws logs --tail=100 backend-aws

# Follow logs in real-time
docker compose --profile aws logs -f backend-aws
```

**Look for:**
- Startup errors
- Database connection issues
- Port binding errors
- Import/module errors

## Fix Steps

### Option 1: Restart Backend Container (Recommended)

**On AWS Server:**
```bash
cd ~/automated-trading-platform

# Restart backend
docker compose --profile aws restart backend-aws

# Wait 30 seconds for startup
sleep 30

# Verify it's running
docker compose --profile aws ps backend-aws

# Test health endpoint
curl -s http://localhost:8002/ping_fast && echo "✅ Backend is responding"
```

**Or use the restart script from local machine:**
```bash
./restart_backend_aws.sh
```

### Option 2: Rebuild and Restart (If restart doesn't work)

**On AWS Server:**
```bash
cd ~/automated-trading-platform

# Stop backend
docker compose --profile aws stop backend-aws

# Rebuild (if code changed)
docker compose --profile aws build backend-aws

# Start backend
docker compose --profile aws up -d backend-aws

# Wait for health check
sleep 60

# Verify
docker compose --profile aws ps backend-aws
curl -s http://localhost:8002/ping_fast && echo "✅ Backend is responding"
```

### Option 3: Full Service Restart (If other services are affected)

**On AWS Server:**
```bash
cd ~/automated-trading-platform

# Restart all AWS services
docker compose --profile aws restart

# Or restart specific services
docker compose --profile aws restart backend-aws market-updater-aws

# Verify all services
docker compose --profile aws ps
```

## Verification

After restarting, verify the fix:

1. **Check container status:**
   ```bash
   docker compose --profile aws ps backend-aws
   ```
   Should show "Up" and "(healthy)"

2. **Test health endpoint:**
   ```bash
   curl -s http://localhost:8002/ping_fast
   ```
   Should return quickly without errors

3. **Test monitoring endpoint:**
   ```bash
   curl -s http://localhost:8002/api/monitoring/summary | jq '.backend_health'
   ```
   Should return `"healthy"`, `"degraded"`, or `"unhealthy"` (not `"error"`)

4. **Check dashboard:**
   - Refresh the monitoring tab
   - Backend Health should show "HEALTHY" (green) instead of "ERROR" (red)
   - Error message should disappear

## Common Issues and Solutions

### Issue: Container keeps restarting
**Solution:**
- Check logs: `docker compose --profile aws logs backend-aws`
- Look for startup errors (database connection, missing env vars, etc.)
- Verify database is running: `docker compose --profile aws ps db`

### Issue: Port 8002 already in use
**Solution:**
```bash
# Find what's using port 8002
sudo lsof -i :8002
# Or
sudo netstat -tulpn | grep 8002

# Stop conflicting service or change backend port in docker-compose.yml
```

### Issue: Database connection errors
**Solution:**
```bash
# Check database is running
docker compose --profile aws ps db

# Check database health
docker compose --profile aws exec db pg_isready

# Restart database if needed
docker compose --profile aws restart db
```

### Issue: Backend starts but health check fails
**Solution:**
- Check if `/ping_fast` endpoint exists and responds
- Increase health check timeout in docker-compose.yml
- Check backend logs for slow startup

## Prevention

To prevent this issue in the future:

1. **Monitor container health:**
   ```bash
   # Set up monitoring script
   watch -n 60 'docker compose --profile aws ps'
   ```

2. **Set up auto-restart:**
   - Docker Compose `restart: always` is already configured
   - Consider adding external monitoring (e.g., CloudWatch)

3. **Regular health checks:**
   - Add cron job to check backend health
   - Alert on failures

## Quick Reference Commands

### Using the Diagnostic Script (Recommended)

**From your local machine:**
```bash
# Run diagnostics
./diagnose_backend_health.sh

# Run diagnostics and attempt fix
./diagnose_backend_health.sh --fix
```

**On AWS server:**
```bash
# Run diagnostics
./diagnose_backend_health.sh

# Run diagnostics and attempt fix
./diagnose_backend_health.sh --fix
```

### Manual Commands

```bash
# Check status
docker compose --profile aws ps

# View logs
docker compose --profile aws logs --tail=50 backend-aws

# Restart backend
docker compose --profile aws restart backend-aws

# Test health
curl -s http://localhost:8002/ping_fast

# Full restart
docker compose --profile aws restart
```

