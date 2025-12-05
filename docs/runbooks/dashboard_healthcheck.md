# Dashboard Health Check Runbook

## Architecture Overview

The dashboard at https://dashboard.hilovivo.com consists of:

1. **Nginx** (host-level reverse proxy)
   - Listens on ports 80/443
   - Routes `/api/*` → `http://127.0.0.1:8002/api/*` (backend-aws)
   - Routes `/` → `http://127.0.0.1:3000/` (frontend)

2. **backend-aws** (FastAPI + gunicorn)
   - Container: `automated-trading-platform-backend-aws-1`
   - Internal port: 8000
   - Host port mapping: `8002:8002`
   - Healthcheck: `http://localhost:8002/ping_fast`

3. **market-updater** (background service)
   - Container: `automated-trading-platform-market-updater-1`
   - Healthcheck: Connects to `127.0.0.1:8002` (host network)
   - **Note**: This healthcheck may fail if backend-aws is not accessible from host network

4. **db** (PostgreSQL)
   - Container: `postgres_hardened`
   - Required by backend-aws and market-updater

5. **gluetun** (VPN container)
   - Required by backend-aws for outbound traffic

## Quick Diagnostic Script

**From your local Mac:**

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/debug_dashboard_remote.sh
```

This script runs all diagnostics automatically and shows:
- Container status and health
- Backend API connectivity
- Recent logs from backend and market-updater

## Manual Diagnostic Workflow

### Step 1: Check Container Status

**From local Mac:**

```bash
cd /Users/carloscruz/automated-trading-platform
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws ps'
```

**What to look for:**
- All containers should be `Up`
- `backend-aws` should show `(healthy)`
- `market-updater` health status (may show `(health: starting)` or `(unhealthy)`)

### Step 2: Inspect Container Health Details

**Backend health:**

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker inspect automated-trading-platform-backend-aws-1 --format="{{json .State.Health}}" | python3 -m json.tool'
```

**Market-updater health:**

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker inspect automated-trading-platform-market-updater-1 --format="{{json .State.Health}}" | python3 -m json.tool'
```

**What to look for:**
- `Status`: Should be `"healthy"` or `"starting"` (not `"unhealthy"`)
- `FailingStreak`: Should be `0` for healthy containers
- `Log`: Check last healthcheck result

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

### Step 4: Test Domain Endpoints

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

**If `/` returns 502:**
- Frontend container may be down
- Check frontend container: `docker compose --profile aws ps frontend-aws`

### Step 5: Check Backend Logs

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs --tail=200 backend-aws'
```

**What to look for:**
- Application startup errors
- Database connection errors
- Python exceptions or tracebacks
- Gunicorn worker crashes
- Recent request logs

### Step 6: Check Market-Updater Logs

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs --tail=200 market-updater'
```

**What to look for:**
- Connection errors to backend
- Database connection issues
- Python exceptions

### Step 7: Check Nginx Error Logs

```bash
ssh hilovivo-aws 'sudo tail -50 /var/log/nginx/error.log'
```

**What to look for:**
- `Connection refused` → Backend not listening on 8002
- `Connection reset by peer` → Backend crashed during request
- `upstream timeout` → Backend taking too long to respond
- `502 Bad Gateway` → General upstream failure

## Decision Tree

### Scenario 1: API 200, Root 502, Backend Healthy, Market-Updater Unhealthy

**Symptoms:**
- `curl https://dashboard.hilovivo.com/api/config` → HTTP 200
- `curl https://dashboard.hilovivo.com/` → HTTP 502
- `docker compose ps` shows backend-aws healthy, market-updater unhealthy

**Likely Cause:**
- Frontend container is down or not running
- Market-updater healthcheck is failing (may be unrelated to dashboard)

**Action:**
1. Check frontend container: `docker compose --profile aws ps frontend-aws`
2. Check frontend logs: `docker compose --profile aws logs frontend-aws --tail=100`
3. Market-updater healthcheck may be failing due to port/host mismatch (see Note below)

### Scenario 2: API 502, Backend Unhealthy

**Symptoms:**
- `curl https://dashboard.hilovivo.com/api/config` → HTTP 502
- `docker compose ps` shows backend-aws as `(unhealthy)` or `(Exited)`

**Likely Cause:**
- Backend container crashed
- Database connection failure
- Environment variable issues
- Application startup error

**Action:**
1. Check backend logs: `docker compose --profile aws logs backend-aws --tail=200`
2. Check database: `docker compose --profile aws ps db`
3. Check backend health details: `docker inspect automated-trading-platform-backend-aws-1 --format="{{json .State.Health}}"`
4. Restart backend: `docker compose --profile aws restart backend-aws`

### Scenario 3: API Timeout, Backend Healthy

**Symptoms:**
- `curl https://dashboard.hilovivo.com/api/config` → Timeout
- `docker compose ps` shows backend-aws as `(healthy)`
- Direct backend test works: `curl http://127.0.0.1:8002/api/config` → HTTP 200

**Likely Cause:**
- Nginx proxy timeout too short
- Backend responding slowly
- Network issue between nginx and backend

**Action:**
1. Check nginx timeout settings: `sudo cat /etc/nginx/sites-enabled/dashboard.conf | grep timeout`
2. Check backend response time: `time curl http://127.0.0.1:8002/api/config`
3. Check nginx error logs for timeout errors

### Scenario 4: Both API and Root 502, Backend Healthy

**Symptoms:**
- Both endpoints return 502
- Backend shows as healthy
- Direct backend test works

**Likely Cause:**
- Nginx configuration issue
- Nginx not running
- SSL certificate issue

**Action:**
1. Check nginx status: `sudo systemctl status nginx`
2. Check nginx config: `sudo nginx -t`
3. Check nginx error logs: `sudo tail -f /var/log/nginx/error.log`
4. Restart nginx: `sudo systemctl restart nginx`

### Scenario 5: Market-Updater Healthcheck Failing

**Symptoms:**
- `docker compose ps` shows market-updater as `(unhealthy)`
- Dashboard may or may not be affected

**Likely Cause:**
- Market-updater healthcheck connects to `127.0.0.1:8002` (host network)
- Backend-aws listens on `0.0.0.0:8002` inside container, mapped to host `8002`
- Healthcheck may fail if backend is not accessible from host network perspective
- **Note**: This is a known configuration issue - the healthcheck should connect to backend via Docker network, not host network

**Action:**
1. Verify backend is accessible: `curl http://127.0.0.1:8002/api/config`
2. If backend is accessible but healthcheck fails, this is a healthcheck configuration issue (not a dashboard issue)
3. Market-updater healthcheck failure does not necessarily indicate dashboard problems

## Common Fixes

### Restart Backend

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart backend-aws'
```

Wait 60-90 seconds for healthcheck to pass, then test again.

### Restart All Services

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart'
```

### Rebuild and Restart Backend

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws build --no-cache backend-aws && docker compose --profile aws up -d backend-aws'
```

### Check Database Connection

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec db psql -U trader -d atp -c "SELECT 1;"'
```

## Notes

- **Port Mapping**: backend-aws listens on port 8000 internally, but is mapped to 8002 on the host. The healthcheck and nginx both use 8002 (host port).

- **Market-Updater Healthcheck**: The market-updater healthcheck attempts to connect to `127.0.0.1:8002` from within the container. This may fail if the backend is not accessible via the host network from the container's perspective. This is a known configuration issue and does not necessarily indicate a dashboard problem.

- **Nginx Timeouts**: Nginx proxy timeouts are set to 180s. If backend requests take longer, they will timeout. Check backend logs for slow queries or operations.

- **Healthcheck Intervals**: Backend healthcheck runs every 60s with 5 retries. It may take up to 5 minutes for a container to be marked unhealthy after a failure.
