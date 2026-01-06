# Verify AWS Connection via SSM Port-Forward

## Quick Verification

```bash
cd ~/automated-trading-platform
curl -i http://localhost:8002/api/health | grep -E "(HTTP|X-ATP-Backend)"
```

**Expected output:**
```
HTTP/1.1 200 OK
X-ATP-Backend-Commit: <git-sha>
X-ATP-Backend-Buildtime: <timestamp>
X-ATP-Backend-BuildTime: <timestamp>
```

**If headers show "unknown":**
- Backend may not have build metadata set
- Check: `docker exec backend-aws env | grep -E "(ATP_GIT_SHA|ATP_BUILD_TIME)"`
- These are set during Docker build via `docker-compose.yml` or `.env.aws`

## Full Health Check

```bash
cd ~/automated-trading-platform
curl -sS http://localhost:8002/api/health | python3 -m json.tool
```

**Expected:** JSON response with `status: "ok"` or similar.

## Verify Dashboard State

```bash
cd ~/automated-trading-platform
curl -sS -w "\nHTTP Status: %{http_code}\n" "http://localhost:8002/api/dashboard/state" | head -50
```

**Expected:** HTTP Status: 200, JSON response with portfolio data.

