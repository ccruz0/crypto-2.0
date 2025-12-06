# Backend 502 Bad Gateway Fix - December 5, 2025

## Problem

The dashboard at https://dashboard.hilovivo.com was returning `502 Bad Gateway` errors for API requests, specifically `/api/config` and other endpoints.

## Root Cause

The issue was identified as **connection timeouts and connection resets** between nginx (reverse proxy) and the backend container. The symptoms were:

1. **Nginx error logs** showed: `recv() failed (104: Connection reset by peer) while reading response header from upstream`
2. **Backend was healthy** according to Docker health checks
3. **Direct backend access** (from inside container) worked fine (HTTP 200)
4. **Nginx proxy** was getting connection resets

The root cause was **insufficient timeout settings** in the gunicorn configuration:
- Original timeout: `30 seconds` - too short for some database-heavy requests
- No keepalive settings - connections were being closed prematurely
- No request limits - potential memory leaks from long-running processes

## Solution

### Changes Made

**File**: `docker-compose.yml` (line 188)

**Before**:
```yaml
command: sh -c "sleep 10 && python -m gunicorn app.main:app -w 1 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8002 --log-level info --access-logfile - --timeout 30"
```

**After**:
```yaml
command: sh -c "sleep 10 && python -m gunicorn app.main:app -w 1 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8002 --log-level info --access-logfile - --timeout 120 --max-requests 1000 --max-requests-jitter 50"
```

### Improvements

1. **Increased timeout**: `30s` → `120s`
   - Allows longer-running requests (database queries, portfolio calculations) to complete
   - Matches nginx proxy timeout settings (180s)
   - Prevents connection resets during long-running operations

2. **Added request limits**: `--max-requests 1000 --max-requests-jitter 50`
   - Prevents memory leaks by recycling worker processes after 1000 requests
   - Jitter (50) prevents all workers from restarting simultaneously
   - Ensures worker processes are periodically refreshed

**Note**: `--keepalive` is not a valid gunicorn option and was removed after initial testing showed it caused startup errors.

## Deployment Steps

1. **Updated docker-compose.yml locally**
2. **Copied to AWS**: `scp docker-compose.yml hilovivo-aws:/home/ubuntu/automated-trading-platform/`
3. **Recreated backend container**: `docker compose --profile aws up -d --force-recreate backend-aws`
4. **Waited for health check**: ~60 seconds for backend to become healthy
5. **Verified**: Tested `/api/config` endpoint returns HTTP 200

## Verification

### Before Fix
```bash
$ curl -s -o /dev/null -w '%{http_code}' https://dashboard.hilovivo.com/api/config
502
```

### After Fix
```bash
$ curl -s -o /dev/null -w '%{http_code}' https://dashboard.hilovivo.com/api/config
200
```

### Container Status
```bash
$ docker compose --profile aws ps backend-aws
NAME                                       STATUS
automated-trading-platform-backend-aws-1  Up X minutes (healthy)
```

## Additional Notes

- **Nginx configuration** already had appropriate timeouts (180s) and was not changed
- **Backend health checks** were working correctly - the issue was with request handling, not startup
- **No code changes** were required - this was purely a configuration issue
- **Frontend was not affected** - only backend API endpoints were impacted

## Monitoring

To monitor for similar issues in the future:

1. **Quick diagnostic script**: Run `bash scripts/debug_dashboard_remote.sh` for comprehensive diagnostics
   - Checks all containers, health status, API connectivity, and error logs
   - Provides color-coded output with clear status indicators
   - Tests both internal and external endpoints

2. **Check nginx error logs**: `sudo tail -f /var/log/nginx/error.log | grep -i "502\|reset\|upstream"`

3. **Check backend logs**: `docker compose --profile aws logs backend-aws --tail=100 | grep -iE "error|timeout|killed"`

4. **Test endpoint**: `curl -v https://dashboard.hilovivo.com/api/config`

5. **Check container health**: `docker compose --profile aws ps backend-aws`

For detailed troubleshooting workflows, see: [Dashboard Health Check Runbook](../runbooks/dashboard_healthcheck.md)

## Related Issues

- **Market-Updater Healthcheck**: See [Market-Updater Healthcheck Fix](./MARKET_UPDATER_HEALTHCHECK_FIX.md) for similar connection issues
- **Dashboard Diagnostics**: The diagnostic script now includes comprehensive checks for all services

## Files Changed

- `docker-compose.yml` (line 188): Updated gunicorn command with increased timeout and keepalive settings
