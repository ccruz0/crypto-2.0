# Fix Backend Docker Build Script

## Overview

The `fix_backend_docker_build.sh` script fixes the Docker build issue where `gunicorn` is not being installed in the backend container, and rebuilds the image properly.

## Problem

The backend container fails to start because `gunicorn` is missing, even though it's listed in `requirements.txt`. This causes:
- Container restart loops
- "Backend Health: ERROR" in dashboard
- 502 Bad Gateway errors

## Solution

The script:
1. ✅ Verifies `gunicorn` is in `requirements.txt`
2. ✅ Stops and removes old container
3. ✅ Removes old Docker image
4. ✅ Cleans Docker build cache
5. ✅ Rebuilds image with `--no-cache` (ensures fresh build)
6. ✅ Verifies `gunicorn` is installed in new image
7. ✅ Starts the container
8. ✅ Tests health endpoints
9. ✅ Verifies external access

## Usage

```bash
# Run the fix script
./fix_backend_docker_build.sh
```

**Expected Duration:** 5-7 minutes
- Build time: 3-5 minutes
- Container startup: 30-60 seconds
- Verification: 1-2 minutes

## What It Does

### Step-by-Step Process

1. **Verification**: Checks that `gunicorn==21.2.0` is in `backend/requirements.txt`
2. **Cleanup**: Removes old container and image to force fresh build
3. **Cache Clean**: Prunes Docker build cache
4. **Rebuild**: Builds new image with `--no-cache` flag
5. **Verification**: Tests that `gunicorn` is installed in the new image
6. **Start**: Starts the backend container
7. **Health Check**: Tests `/ping_fast` and `/api/monitoring/summary` endpoints
8. **External Test**: Verifies dashboard access

## Requirements

- AWS CLI installed and configured
- SSM access to instance `i-08726dc37133b2454`
- Proper AWS credentials with SSM permissions

## Output

The script provides:
- ✅ Status messages for each step
- 📋 Container status after rebuild
- 📋 Build logs (last 30 lines)
- 🧪 Health endpoint test results
- 🌐 External access verification

## Troubleshooting

### If build fails:
1. Check build logs: `/tmp/docker_build.log` on server
2. Verify `requirements.txt` has `gunicorn==21.2.0`
3. Check Docker build context is correct (should be `.` not `./backend`)

### If gunicorn still missing:
1. Manually verify: `docker exec backend-aws-1 pip list | grep gunicorn`
2. Check if wheels were built: `docker run --rm <image> ls /wheels | grep gunicorn`
3. Rebuild with verbose output: `docker compose --profile aws build --progress=plain backend-aws`

### If container won't start:
1. Check logs: `docker compose --profile aws logs backend-aws`
2. Verify database is running: `docker compose --profile aws ps db`
3. Check port 8002 is available

## Manual Alternative

If the script doesn't work, you can run commands manually:

```bash
# On AWS server
cd ~/automated-trading-platform

# Stop and remove
docker compose --profile aws stop backend-aws
docker compose --profile aws rm -f backend-aws

# Remove image
docker rmi automated-trading-platform-backend-aws

# Rebuild
docker compose --profile aws build --no-cache backend-aws

# Start
docker compose --profile aws up -d backend-aws

# Verify
docker exec backend-aws-1 pip list | grep gunicorn
curl http://localhost:8002/ping_fast
```

## Success Indicators

After running the script, you should see:
- ✅ Container status: `Up X minutes (healthy)`
- ✅ Health endpoint responds
- ✅ Monitoring endpoint returns JSON with `backend_health`
- ✅ Dashboard shows "Backend Health: HEALTHY" (green)

## Next Steps

After successful rebuild:
1. Wait 1-2 minutes for full startup
2. Refresh dashboard Monitoring tab
3. Verify "Backend Health" shows "HEALTHY"
4. Check that other metrics are populated




