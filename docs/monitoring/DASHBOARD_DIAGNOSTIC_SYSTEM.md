# Dashboard Diagnostic System - Complete Overview

## Overview

The dashboard diagnostic system provides a unified, automated workflow for diagnosing all types of dashboard failures, including 502 errors, backend health issues, frontend load failures, and market-updater problems.

## Quick Start

**From your local Mac:**

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/debug_dashboard_remote.sh
```

This single command runs comprehensive diagnostics and shows:
- ✅ All container statuses and health
- ✅ Backend API connectivity (host and Docker network)
- ✅ Database connectivity
- ✅ External endpoint tests (domain → nginx → services)
- ✅ Recent error logs from all services
- ✅ Nginx status and error logs

## System Architecture

### Components Checked

1. **Nginx** (Reverse Proxy)
   - Status: Running/stopped
   - Error logs: Connection issues, upstream failures
   - Configuration: Valid/invalid

2. **Backend-aws** (FastAPI + gunicorn)
   - Container status: Up/down/restarting
   - Health status: Healthy/unhealthy/starting
   - API connectivity: Host and container network
   - Restart count: Indicates crashes
   - Error logs: Exceptions, database errors, startup failures

3. **Frontend-aws** (Next.js)
   - Container status: Up/down
   - Port accessibility: 3000
   - Build status: Successful/failed

4. **Database** (PostgreSQL)
   - Container status: Up/down
   - Health status: Healthy/unhealthy
   - Connectivity: From backend container

5. **Market-updater** (Background Service)
   - Container status: Up/down
   - Health status: Healthy/unhealthy/starting
   - **Note**: Failures do NOT affect dashboard

6. **Gluetun** (VPN)
   - Container status: Up/down
   - Health status: Healthy/unhealthy
   - **Note**: Required for backend external API calls

## Diagnostic Script Features

### Automatic Detection

The script automatically:
- ✅ Finds containers by name pattern (handles hash-prefixed names)
- ✅ Detects health status from Docker inspect
- ✅ Tests connectivity from multiple perspectives
- ✅ Parses error logs for relevant issues
- ✅ Provides color-coded status indicators

### Status Indicators

- **✅ GREEN**: Service is healthy and working correctly
- **⏳ YELLOW**: Service is starting (normal during startup)
- **❌ RED**: Service is unhealthy or failing (needs attention)
- **⚠️ YELLOW**: Warning (may not be critical, but worth noting)

### Connectivity Tests

1. **Host → Backend**: Tests `http://127.0.0.1:8002/api/config`
   - Verifies backend is accessible from host network
   - Bypasses nginx

2. **Container → Backend**: Tests `http://backend-aws:8002/ping_fast`
   - Verifies Docker network connectivity
   - Uses service name resolution

3. **Backend → Database**: Tests PostgreSQL connection
   - Verifies database is reachable from backend
   - Tests credentials and network

4. **External → API**: Tests `https://dashboard.hilovivo.com/api/config`
   - Full end-to-end test through nginx
   - Verifies SSL, routing, and backend

5. **External → Frontend**: Tests `https://dashboard.hilovivo.com/`
   - Verifies frontend is serving
   - Tests nginx routing to frontend

## Common Failure Modes

### 1. Backend Unhealthy

**Symptoms:**
- Container shows `(unhealthy)` or `(Exited)`
- API returns 502
- Restart count > 0

**Diagnostic Output:**
```
❌ Status: UNHEALTHY
⚠️  Restart count: 3
```

**Action:**
- Check backend logs for exceptions
- Verify database connectivity
- Check environment variables
- Review healthcheck logs

### 2. Nginx Cannot Reach Backend

**Symptoms:**
- API returns 502
- Backend is healthy
- Direct backend test works

**Diagnostic Output:**
```
✅ Backend API (Host): HTTP 200
❌ Dashboard API: HTTP 502
```

**Action:**
- Check nginx error logs
- Verify nginx configuration
- Check if backend is listening on 127.0.0.1:8002
- Restart nginx if needed

### 3. Frontend Not Serving

**Symptoms:**
- Root returns 502
- API works fine
- Frontend container may be down

**Diagnostic Output:**
```
✅ Dashboard API: HTTP 200
❌ Dashboard Root: HTTP 502
```

**Action:**
- Check frontend container status
- Review frontend logs
- Verify frontend build
- Restart frontend container

### 4. Database Connection Failure

**Symptoms:**
- Backend unhealthy
- Backend logs show database errors
- API returns 500 or 502

**Diagnostic Output:**
```
❌ Database Connectivity: Connection failed
```

**Action:**
- Check database container status
- Verify database credentials
- Test database connection directly
- Review database logs

### 5. Market-Updater Healthcheck Failing

**Symptoms:**
- Market-updater shows `(unhealthy)`
- Dashboard still works

**Diagnostic Output:**
```
❌ Market-updater: UNHEALTHY
⚠️  NOTE: Market-updater healthcheck failure does NOT break the dashboard
```

**Action:**
- Verify backend is accessible from market-updater
- Check healthcheck configuration
- **Note**: This is informational only, does not require immediate action

## Integration with Runbook

The diagnostic script is designed to work with the [Dashboard Health Check Runbook](./runbooks/dashboard_healthcheck.md):

1. **Run diagnostic script** → Get quick overview
2. **Review runbook** → Understand architecture and flow
3. **Follow decision tree** → Identify specific failure mode
4. **Apply fixes** → Use common fixes section

## Files in Diagnostic System

1. **`scripts/debug_dashboard_remote.sh`**
   - Main diagnostic script
   - Runs all checks automatically
   - Provides color-coded output

2. **`docs/runbooks/dashboard_healthcheck.md`**
   - Complete troubleshooting guide
   - Architecture diagrams
   - Decision trees
   - Step-by-step workflows

3. **`docs/monitoring/BACKEND_502_FIX.md`**
   - Backend-specific fixes
   - Timeout configuration
   - Gunicorn settings

4. **`docs/monitoring/MARKET_UPDATER_HEALTHCHECK_FIX.md`**
   - Market-updater healthcheck fix
   - Docker network connectivity
   - Service name resolution

## Usage Examples

### Quick Health Check

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/debug_dashboard_remote.sh
```

### After Making Changes

```bash
# 1. Make changes locally
# 2. Copy files to AWS
scp docker-compose.yml hilovivo-aws:/home/ubuntu/automated-trading-platform/

# 3. Restart services
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart'

# 4. Run diagnostics
bash scripts/debug_dashboard_remote.sh
```

### When Dashboard is Down

```bash
# 1. Run diagnostics
bash scripts/debug_dashboard_remote.sh

# 2. Identify the failing component (look for ❌)

# 3. Check the runbook for that specific scenario

# 4. Apply fixes from the runbook

# 5. Re-run diagnostics to verify
bash scripts/debug_dashboard_remote.sh
```

## Best Practices

1. **Run diagnostics first**: Always start with the diagnostic script to get a complete picture

2. **Check health status**: Look for `(healthy)` status on critical services (backend, db, gluetun)

3. **Review error logs**: Check the "RECENT ERROR LOGS" section for exceptions

4. **Test connectivity**: Verify both internal (host) and external (domain) endpoints

5. **Check restart counts**: High restart counts indicate crashes or healthcheck failures

6. **Isolate issues**: Use the decision tree to identify the specific failure mode

7. **Verify fixes**: Always re-run diagnostics after applying fixes

## Troubleshooting the Diagnostic Script

If the diagnostic script itself fails:

1. **SSH connection issue**: Verify SSH config for `hilovivo-aws`
2. **Permission issue**: Ensure SSH key has access to the server
3. **Docker not running**: Check if Docker is running on the remote server
4. **Path issue**: Verify the remote path `/home/ubuntu/automated-trading-platform` exists

## Related Documentation

- [Dashboard Health Check Runbook](./runbooks/dashboard_healthcheck.md) - Complete troubleshooting guide
- [Backend 502 Fix](./BACKEND_502_FIX.md) - Backend-specific fixes
- [Market-Updater Healthcheck Fix](./MARKET_UPDATER_HEALTHCHECK_FIX.md) - Market-updater configuration
- [README.md](../README.md) - Project overview and quick start
