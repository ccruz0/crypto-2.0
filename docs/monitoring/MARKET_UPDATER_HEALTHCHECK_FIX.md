# Market-Updater Healthcheck Fix - December 5, 2025

## Problem

The `market-updater` container healthcheck was failing with `ConnectionRefusedError` when trying to connect to `127.0.0.1:8002` from inside the container.

**Error in healthcheck logs:**
```
ConnectionRefusedError: [Errno 111] Connection refused
```

**Impact:**
- Market-updater container showed as `(unhealthy)` or stuck in `(health: starting)`
- Healthcheck failures created noise in diagnostics
- Potential for cascading failures if other services depend on market-updater health

**Root Cause:**
The healthcheck was attempting to connect to `127.0.0.1:8002` (localhost within the container), but the backend service (`backend-aws`) runs in a separate container. In Docker Compose, containers communicate using service names, not localhost.

## Solution

### Changes Made

**File**: `docker-compose.yml` (lines 236-241)

**Added healthcheck configuration:**
```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://backend-aws:8002/ping_fast', timeout=5)"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 30s
```

**Key changes:**
1. **Changed from**: `127.0.0.1:8002` (localhost - doesn't work across containers)
2. **Changed to**: `backend-aws:8002` (service name - works via Docker network)
3. **Changed from**: Socket connection test
4. **Changed to**: HTTP endpoint test (`/ping_fast`) - more reliable and verifies the backend is actually responding

### Why This Works

- **Docker Compose networking**: Containers in the same Docker Compose network can communicate using service names
- **Service name resolution**: `backend-aws` resolves to the backend container's IP within the Docker network
- **Port mapping**: The backend listens on port 8002 (mapped from internal port 8000), so `backend-aws:8002` is the correct address
- **HTTP test**: Using `/ping_fast` endpoint verifies the backend is not just listening, but actually responding to HTTP requests

## Architecture Diagram

```
┌─────────────────┐
│  market-updater │
│   (container)   │
└────────┬────────┘
         │ HTTP GET
         │ backend-aws:8002/ping_fast
         ▼
┌─────────────────┐
│   backend-aws    │
│   (container)   │
│  Port: 8002     │
└─────────────────┘
```

**Key Points:**
- Both containers are in the same Docker Compose network
- Service name `backend-aws` resolves via Docker DNS
- Port 8002 is the mapped host port (backend listens on 8000 internally, mapped to 8002)

## Dependencies and Isolation

**Important:** The market-updater healthcheck failure does NOT affect:
- ✅ Backend API availability (`/api/config` still works)
- ✅ Nginx → Backend routing (nginx connects directly to backend)
- ✅ Dashboard functionality (dashboard only depends on backend, not market-updater)

**Market-updater dependencies:**
- `depends_on: db` - Waits for database to be healthy
- Does NOT depend on backend-aws - Can start independently
- Healthcheck is informational only - Does not block other services

**Service dependency chain:**
```
frontend-aws → depends_on: [gluetun, backend-aws]
backend-aws → depends_on: [gluetun, db]
market-updater → depends_on: [db]  (independent of backend)
```

This ensures that market-updater healthcheck failures cannot cause 502 errors in the dashboard.

## Verification

### Before Fix
```bash
$ docker inspect automated-trading-platform-market-updater-1 --format='{{json .State.Health}}'
{
    "Status": "unhealthy",
    "FailingStreak": 5,
    "Log": [
        {
            "Output": "ConnectionRefusedError: [Errno 111] Connection refused\n"
        }
    ]
}
```

### After Fix
```bash
$ docker compose --profile aws ps market-updater
NAME                                                       STATUS
automated-trading-platform-market-updater-1               Up X minutes (healthy)

$ docker inspect <container> --format='{{json .State.Health}}'
{
    "Status": "healthy",
    "FailingStreak": 0,
    "Log": [
        {
            "ExitCode": 0,
            "Output": ""
        }
    ]
}
```

## Testing

### Manual Healthcheck Test
```bash
# From inside market-updater container
docker compose --profile aws exec market-updater python3 -c \
  "import urllib.request; resp = urllib.request.urlopen('http://backend-aws:8002/ping_fast', timeout=5); print('HTTP', resp.getcode())"
```

**Expected:** `HTTP 200` (exit code 0)

### Diagnostic Script
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/debug_dashboard_remote.sh
```

**Expected output:**
```
=== MARKET-UPDATER HEALTH ===
✅ Market-updater is HEALTHY
{
    "Status": "healthy",
    "FailingStreak": 0,
    ...
}
```

## Files Changed

1. **`docker-compose.yml`**: Added healthcheck configuration to `market-updater` service
2. **`scripts/debug_dashboard_remote.sh`**: 
   - Updated to find market-updater container by name pattern instead of exact name
   - Added status indicators (✅ healthy, ⏳ starting, ❌ unhealthy)
   - Added warnings for unhealthy/starting states
3. **`docs/monitoring/MARKET_UPDATER_HEALTHCHECK_FIX.md`**: This documentation file

## Healthcheck Configuration Details

- **Test**: HTTP GET to `http://backend-aws:8002/ping_fast`
- **Interval**: 30 seconds (checks every 30s)
- **Timeout**: 10 seconds (healthcheck must complete within 10s)
- **Retries**: 3 (marks unhealthy after 3 consecutive failures)
- **Start Period**: 30 seconds (waits 30s before first healthcheck, allows container to start)

## Notes

- The healthcheck now correctly uses Docker service name resolution (`backend-aws:8002`)
- The HTTP endpoint test (`/ping_fast`) is more reliable than a socket connection test
- The `start_period: 30s` gives the container time to start before healthchecks begin
- The healthcheck interval (30s) and timeout (10s) are appropriate for this service
- Market-updater healthcheck failures are isolated and do not cause 502 errors
- The diagnostic script now provides clear visual indicators for health status

## Diagnostic Integration

The market-updater healthcheck is now fully integrated into the diagnostic workflow:

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/debug_dashboard_remote.sh
```

The script will:
- ✅ Detect market-updater container automatically (by name pattern)
- ✅ Show health status with color-coded indicators
- ✅ Display healthcheck logs and failing streaks
- ✅ Warn if healthcheck is stuck in starting or unhealthy state
- ✅ Note that market-updater failures do NOT affect dashboard

For complete troubleshooting, see: [Dashboard Health Check Runbook](../runbooks/dashboard_healthcheck.md)
