# Dashboard Health Check Runbook - Complete Guide

## Architecture Overview

The dashboard at https://dashboard.hilovivo.com uses the following architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                    User Browser                             │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTPS (443)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Nginx (Host-level Reverse Proxy)                           │
│  - Listens: 0.0.0.0:80, 0.0.0.0:443                         │
│  - SSL: Let's Encrypt certificates                          │
└──────┬──────────────────────────────┬───────────────────────┘
       │                              │
       │ /api/*                       │ /
       │                              │
       ▼                              ▼
┌──────────────────────┐    ┌──────────────────────┐
│  backend-aws         │    │  frontend-aws        │
│  (FastAPI + gunicorn)│    │  (Next.js)           │
│  Port: 8002 (host)   │    │  Port: 3000 (host)   │
│  Internal: 8000       │    │  Internal: 3000      │
└──────┬───────────────┘    └──────────────────────┘
       │
       │ PostgreSQL
       ▼
┌──────────────────────┐
│  db (PostgreSQL)      │
│  Port: 5432           │
└──────────────────────┘

Background Services:
┌──────────────────────┐    ┌──────────────────────┐
│  market-updater      │    │  gluetun (VPN)       │
│  (Price updates)     │    │  (Outbound traffic)  │
│  Healthcheck:        │    │  Required by:        │
│  backend-aws:8002    │    │  - backend-aws       │
└──────────────────────┘    │  - frontend-aws      │
                             └──────────────────────┘
```

## Request Flow

### API Request Flow
```
User → https://dashboard.hilovivo.com/api/config
  ↓
Nginx (reverse proxy)
  ↓
http://127.0.0.1:8002/api/config
  ↓
backend-aws container (port 8002)
  ↓
FastAPI application
  ↓
Database query (if needed)
  ↓
Response → Nginx → User
```

### Frontend Request Flow
```
User → https://dashboard.hilovivo.com/
  ↓
Nginx (reverse proxy)
  ↓
http://127.0.0.1:3000/
  ↓
frontend-aws container (port 3000)
  ↓
Next.js server
  ↓
Response → Nginx → User
```

## Service Dependencies

### Critical Path (Dashboard Functionality)
```
frontend-aws → depends_on: [gluetun, backend-aws]
backend-aws → depends_on: [gluetun, db]
```

**If any of these fail, the dashboard will not work.**

### Background Services (Non-Critical)
```
market-updater → depends_on: [db]
```

**Market-updater failures do NOT affect dashboard functionality.**

## Quick Diagnostic Script

**From your local Mac:**

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/debug_dashboard_remote.sh
```

This script automatically checks:
- ✅ All container statuses and health
- ✅ Backend API connectivity (host and container network)
- ✅ Database connectivity
- ✅ External endpoint tests (domain → nginx → backend/frontend)
- ✅ Recent error logs
- ✅ Nginx status

## Manual Diagnostic Workflow

### Step 1: Check Container Status

**From local Mac:**

```bash
cd /Users/carloscruz/automated-trading-platform
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws ps'
```

**What to look for:**
- All containers should be `Up`
- `backend-aws` should show `(healthy)` - **CRITICAL**
- `frontend-aws` should show `Up` (may not have healthcheck)
- `db` should show `(healthy)` - **CRITICAL**
- `gluetun` should show `(healthy)` - **CRITICAL for backend**
- `market-updater` health status (informational only)

### Step 2: Inspect Container Health Details

**Backend health:**

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker inspect automated-trading-platform-backend-aws-1 --format="{{json .State.Health}}" | python3 -m json.tool'
```

**What to look for:**
- `Status`: Should be `"healthy"` (not `"unhealthy"` or `"starting"`)
- `FailingStreak`: Should be `0`
- `Log`: Last healthcheck should show `ExitCode: 0`

**Market-updater health:**

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker ps --filter "name=market-updater" --format "{{.Names}}" | head -1 | xargs -I {} docker inspect {} --format="{{json .State.Health}}" | python3 -m json.tool'
```

**Note:** Market-updater healthcheck failures are informational only and do NOT break the dashboard.

### Step 3: Test Backend API from Host

**Test backend directly (bypassing nginx):**

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && curl -v http://127.0.0.1:8002/api/config'
```

**Expected:** HTTP 200 with JSON response

**If this fails:**
- Backend container may be down or unhealthy
- Port mapping issue (8002 not accessible)
- Backend crashed or not listening
- Check backend logs: `docker compose --profile aws logs backend-aws --tail=100`

### Step 4: Test Backend from Container Network

**Test Docker network connectivity:**

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec market-updater python3 -c "import urllib.request; resp = urllib.request.urlopen(\"http://backend-aws:8002/ping_fast\", timeout=5); print(\"HTTP\", resp.getcode())"'
```

**Expected:** `HTTP 200`

**If this fails:**
- Docker network issue
- Backend not accessible via service name
- Check if containers are in the same network

### Step 5: Test Domain Endpoints

**From local Mac:**

```bash
cd /Users/carloscruz/automated-trading-platform

# Test API endpoint
curl -v https://dashboard.hilovivo.com/api/config

# Test frontend root
curl -v https://dashboard.hilovivo.com/
```

**Expected:**
- `/api/config`: HTTP 200 with JSON
- `/`: HTTP 200 with HTML (or redirect)

**If `/api/config` returns 502:**
- Nginx cannot reach backend at `127.0.0.1:8002`
- Check backend container status
- Check nginx error logs: `sudo tail -f /var/log/nginx/error.log`
- Verify backend is listening: `curl http://127.0.0.1:8002/api/config` (from host)

**If `/` returns 502:**
- Frontend container may be down
- Check frontend container: `docker compose --profile aws ps frontend-aws`
- Check frontend logs: `docker compose --profile aws logs frontend-aws --tail=100`

### Step 6: Check Backend Logs

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs --tail=200 backend-aws'
```

**What to look for:**
- Application startup errors
- Database connection errors (`psycopg2`, `connection refused`)
- Python exceptions or tracebacks
- Gunicorn worker crashes
- Recent request logs
- Authentication errors

### Step 7: Check Market-Updater Logs

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs --tail=200 market-updater'
```

**What to look for:**
- Connection errors to backend (if healthcheck is failing)
- Database connection issues
- Python exceptions
- Price fetch errors

### Step 8: Check Nginx Error Logs

```bash
ssh hilovivo-aws 'sudo tail -50 /var/log/nginx/error.log'
```

**What to look for:**
- `Connection refused` → Backend/frontend not listening on expected port
- `Connection reset by peer` → Backend crashed during request
- `upstream timeout` → Backend taking too long to respond
- `502 Bad Gateway` → General upstream failure
- `504 Gateway Timeout` → Backend timeout

### Step 9: Check Database Connectivity

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec db psql -U trader -d atp -c "SELECT 1;"'
```

**Expected:** Returns `1` (connection successful)

**If this fails:**
- Database container may be down
- Database credentials incorrect
- Network issue between backend and database

## Decision Tree

### Scenario 1: API 200, Root 502, Backend Healthy, Frontend Missing

**Symptoms:**
- `curl https://dashboard.hilovivo.com/api/config` → HTTP 200
- `curl https://dashboard.hilovivo.com/` → HTTP 502
- `docker compose ps` shows backend-aws healthy, frontend-aws missing or down

**Likely Cause:**
- Frontend container is down or not running
- Frontend build failed or container crashed

**Action:**
1. Check frontend container: `docker compose --profile aws ps frontend-aws`
2. Check frontend logs: `docker compose --profile aws logs frontend-aws --tail=100`
3. Restart frontend: `docker compose --profile aws restart frontend-aws`
4. If frontend is missing, rebuild: `docker compose --profile aws build frontend-aws && docker compose --profile aws up -d frontend-aws`

### Scenario 2: API 502, Backend Unhealthy

**Symptoms:**
- `curl https://dashboard.hilovivo.com/api/config` → HTTP 502
- `docker compose ps` shows backend-aws as `(unhealthy)` or `(Exited)`

**Likely Cause:**
- Backend container crashed
- Database connection failure
- Environment variable issues
- Application startup error
- Gunicorn worker crash

**Action:**
1. Check backend logs: `docker compose --profile aws logs backend-aws --tail=200`
2. Check database: `docker compose --profile aws ps db`
3. Check backend health details: `docker inspect automated-trading-platform-backend-aws-1 --format="{{json .State.Health}}"`
4. Check database connectivity from backend
5. Restart backend: `docker compose --profile aws restart backend-aws`
6. If persistent, rebuild: `docker compose --profile aws build --no-cache backend-aws && docker compose --profile aws up -d backend-aws`

### Scenario 3: API Timeout, Backend Healthy

**Symptoms:**
- `curl https://dashboard.hilovivo.com/api/config` → Timeout
- `docker compose ps` shows backend-aws as `(healthy)`
- Direct backend test works: `curl http://127.0.0.1:8002/api/config` → HTTP 200

**Likely Cause:**
- Nginx proxy timeout too short
- Backend responding slowly
- Network issue between nginx and backend
- Backend under heavy load

**Action:**
1. Check nginx timeout settings: `sudo cat /etc/nginx/sites-enabled/dashboard.conf | grep timeout`
2. Check backend response time: `time curl http://127.0.0.1:8002/api/config`
3. Check nginx error logs for timeout errors
4. Check backend logs for slow queries or operations
5. Increase nginx timeout if needed (default should be 180s)

### Scenario 4: Both API and Root 502, Backend Healthy

**Symptoms:**
- Both endpoints return 502
- Backend shows as healthy
- Direct backend test works

**Likely Cause:**
- Nginx configuration issue
- Nginx not running
- SSL certificate issue
- Nginx cannot bind to ports 80/443

**Action:**
1. Check nginx status: `sudo systemctl status nginx`
2. Check nginx config: `sudo nginx -t`
3. Check nginx error logs: `sudo tail -f /var/log/nginx/error.log`
4. Check if ports are in use: `sudo netstat -tlnp | grep -E ':80|:443'`
5. Restart nginx: `sudo systemctl restart nginx`

### Scenario 5: Market-Updater Healthcheck Failing

**Symptoms:**
- `docker compose ps` shows market-updater as `(unhealthy)`
- Dashboard may or may not be affected

**Likely Cause:**
- Market-updater healthcheck configuration issue (now fixed)
- Backend not accessible from market-updater container
- Healthcheck timeout too short

**Action:**
1. Verify backend is accessible: `curl http://127.0.0.1:8002/api/config`
2. Test from market-updater container: `docker compose --profile aws exec market-updater python3 -c "import urllib.request; urllib.request.urlopen('http://backend-aws:8002/ping_fast', timeout=5)"`
3. **Note**: Market-updater healthcheck failure does NOT indicate dashboard problems
4. Market-updater is a background service and does not affect dashboard functionality

### Scenario 6: Database Connection Errors

**Symptoms:**
- Backend logs show: `psycopg2.OperationalError: connection refused`
- Backend shows as unhealthy
- API returns 502 or 500

**Likely Cause:**
- Database container down
- Database credentials incorrect
- Network issue between backend and database
- Database not accepting connections

**Action:**
1. Check database container: `docker compose --profile aws ps db`
2. Test database connection: `docker compose --profile aws exec db psql -U trader -d atp -c "SELECT 1;"`
3. Check database logs: `docker compose --profile aws logs db --tail=100`
4. Verify DATABASE_URL in backend environment
5. Restart database if needed: `docker compose --profile aws restart db`

### Scenario 7: Gluetun (VPN) Failure

**Symptoms:**
- Backend shows as unhealthy
- Backend logs show connection timeouts to external APIs
- Telegram bot not working

**Likely Cause:**
- VPN connection failed
- Gluetun container down or unhealthy
- VPN credentials incorrect

**Action:**
1. Check gluetun status: `docker compose --profile aws ps gluetun`
2. Check gluetun logs: `docker compose --profile aws logs gluetun --tail=100`
3. Verify VPN credentials in environment
4. Restart gluetun: `docker compose --profile aws restart gluetun`
5. **Note**: Backend depends on gluetun, so VPN failure will cause backend to fail

## Common Fixes

### Restart Backend

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart backend-aws'
```

Wait 60-180 seconds for healthcheck to pass, then test again.

### Restart All Services

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart'
```

### Rebuild and Restart Backend

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws build --no-cache backend-aws && docker compose --profile aws up -d backend-aws'
```

### Restart Nginx

```bash
ssh hilovivo-aws 'sudo systemctl restart nginx'
```

### Check Database Connection

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec db psql -U trader -d atp -c "SELECT 1;"'
```

## Interpreting Diagnostic Script Output

The diagnostic script (`scripts/debug_dashboard_remote.sh`) provides color-coded output:

- **✅ GREEN**: Service is healthy and working
- **⏳ YELLOW**: Service is starting (may be normal during startup)
- **❌ RED**: Service is unhealthy or failing (needs attention)
- **⚠️ YELLOW**: Warning (may not be critical)

### Key Sections to Check

1. **DOCKER COMPOSE STATUS**: Overall container status
2. **CONTAINER HEALTH DETAILS**: Detailed health information
3. **API CONNECTIVITY TESTS**: Network connectivity checks
4. **EXTERNAL ENDPOINT TESTS**: Domain accessibility
5. **RECENT ERROR LOGS**: Error messages and exceptions

### What "OK" Looks Like

```
✅ Backend-aws: HEALTHY
✅ Market-updater: HEALTHY (or starting, if just restarted)
✅ Database: HEALTHY
✅ Gluetun: HEALTHY
✅ Backend API (Host): HTTP 200
✅ Backend API (Container): HTTP 200
✅ Database Connectivity: Success
✅ Dashboard API: HTTP 200
✅ Dashboard Root: HTTP 200
✅ Nginx: running
```

## Notes

- **Port Mapping**: backend-aws listens on port 8000 internally, but is mapped to 8002 on the host. The healthcheck and nginx both use 8002 (host port).

- **Market-Updater Healthcheck**: The market-updater healthcheck connects to `backend-aws:8002` via Docker network. This is correct and should work. Healthcheck failures are informational only and do NOT affect dashboard functionality.

- **Nginx Timeouts**: Nginx proxy timeouts are set to 180s. If backend requests take longer, they will timeout. Check backend logs for slow queries or operations.

- **Healthcheck Intervals**: 
  - Backend healthcheck runs every 120s with 5 retries. It may take up to 10 minutes for a container to be marked unhealthy after a failure.
  - Market-updater healthcheck runs every 30s with 3 retries.

- **Service Isolation**: Market-updater healthcheck failures are isolated and do not cause 502 errors. The dashboard only depends on backend-aws, not market-updater.

- **Frontend Deployment**: The frontend may be deployed on Vercel or in the frontend-aws container. Check which one is configured in nginx.

## Related Documentation

- [Market-Updater Healthcheck Fix](../monitoring/MARKET_UPDATER_HEALTHCHECK_FIX.md)
- [Backend 502 Fix](../monitoring/BACKEND_502_FIX.md)
- [Dashboard Health Check Runbook](./dashboard_healthcheck.md) (this file)
