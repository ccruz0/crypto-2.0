# Backend Stability Fixes - Summary

## Problem Identified

The backend was crashing repeatedly due to:
1. **Excessive simultaneous requests** to `/api/alert-ratio` endpoint (30+ requests at once)
2. **High CPU usage** (89.87%) causing the backend to become unresponsive
3. **Memory pressure** from too many concurrent requests
4. **503 Service Unavailable** errors when backend couldn't handle the load

## Root Cause

The frontend was calling `getAlertRatio()` for every coin on every signal update, without throttling or batching. With multiple coins updating simultaneously, this created a flood of requests that overwhelmed the backend.

## Solutions Implemented

### 1. Throttled Alert Ratio Fetching (Frontend)

**Location**: `frontend/src/app/page.tsx`

**Changes**:
- Added `alertRatioFetchQueue` to batch alert ratio requests
- Added `fetchAlertRatiosBatch()` function that processes requests sequentially with 200ms delays
- Added `queueAlertRatioFetch()` function with 2-second debounce
- Alert ratio requests are now batched and throttled instead of firing simultaneously

**Impact**:
- Reduces simultaneous requests from 30+ to 1-2 at a time
- Prevents backend overload
- Maintains functionality while protecting backend stability

### 2. Improved Error Handling

**Location**: `frontend/src/lib/api.ts`

**Changes**:
- Enhanced `toggleLiveTrading()` function with better error messages
- Added timeout handling (10 seconds)
- Improved error detection and reporting

### 3. Cache Prevention Headers

**Location**: `frontend/next.config.ts` and `frontend/src/app/layout.tsx`

**Changes**:
- Added HTTP headers to prevent browser caching
- Ensures users always get the latest version after deployments

## Monitoring & Prevention

### Check Backend Health
```bash
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'docker compose --profile aws ps backend-aws'
```

### Monitor Request Volume
```bash
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'docker compose --profile aws logs --tail=100 backend-aws | grep "alert-ratio" | wc -l'
```

### Check CPU/Memory Usage
```bash
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" | grep backend'
```

## Best Practices Going Forward

1. **Always throttle/batch API requests** when calling endpoints for multiple items
2. **Use debouncing** for user-triggered actions that might fire multiple times
3. **Monitor backend logs** regularly for unusual request patterns
4. **Set appropriate timeouts** for API calls
5. **Implement circuit breakers** for endpoints that might fail under load

## Backend Resource Limits

Current limits (from `docker-compose.yml`):
- **CPU**: 1.0 core
- **Memory**: 768MB
- **Workers**: 2 (for backend-aws)

If backend continues to crash, consider:
- Increasing memory limit to 1GB
- Reducing number of workers to 1
- Adding request rate limiting in backend
- Implementing request queuing in backend

## Testing

After deployment, verify:
1. Backend stays up for extended periods
2. Alert ratios still update (may be slightly delayed due to throttling)
3. No 503 errors in frontend
4. CPU usage stays below 80%


