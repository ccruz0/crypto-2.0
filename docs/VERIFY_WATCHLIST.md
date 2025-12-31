# Watchlist Verification Guide

## Overview

The watchlist verification scripts (`watchlist_consistency_check.py` and `verify_watchlist_e2e.py`) must run inside the backend container to ensure they use the **same database** as the API. Running them on the host may connect to a different database and show false mismatches.

## Always Run Via Container Wrapper

**Use the wrapper script to run verification inside the container:**

```bash
# Consistency check
backend/scripts/run_in_backend_container.sh python3 scripts/watchlist_consistency_check.py

# End-to-end verification
backend/scripts/run_in_backend_container.sh python3 scripts/verify_watchlist_e2e.py

# Check API fingerprint headers
backend/scripts/run_in_backend_container.sh python3 scripts/print_api_fingerprints.py
```

## Checking API Headers

**If `curl -sI http://localhost:8002/api/dashboard` returns empty on your Mac:**
- You're likely running it locally, not on AWS
- The backend is not running on your Mac, or it's on a different port

**To check headers correctly:**

**On AWS host:**
```bash
ssh hilovivo-aws 'curl -sI http://localhost:8002/api/dashboard | head -20'
```

**From your laptop to AWS:**
```bash
curl -sI http://<aws-host>:8002/api/dashboard | head -20
```

**Or use the fingerprint script (works from anywhere):**
```bash
# On AWS host
python3 backend/scripts/print_api_fingerprints.py

# From Mac via wrapper
backend/scripts/run_in_backend_container.sh python3 scripts/print_api_fingerprints.py
```

The wrapper script:
- Finds the running `backend-aws` container
- Executes the command inside the container
- Shows container name and backend commit/build time
- Passes through exit codes

## Host Execution (Not Recommended)

By default, running scripts directly on the host will **refuse to run** with exit code 2:

```bash
# This will fail with a clear error message
python3 backend/scripts/watchlist_consistency_check.py
```

To override (advanced, may show mismatches):
```bash
ALLOW_HOST_RUN=1 python3 backend/scripts/watchlist_consistency_check.py
```

## Database Fingerprint Verification

The API includes DB fingerprint headers in all responses:
- `X-ATP-DB-Host`: Database hostname
- `X-ATP-DB-Name`: Database name
- `X-ATP-DB-Hash`: Short hash of DATABASE_URL (password stripped)

Verification scripts automatically check these headers. If the local `DATABASE_URL` fingerprint doesn't match the API's fingerprint, the script will:
- Print a clear error showing the mismatch
- Exit with code 3
- Instruct you to run via the container wrapper

## Build Fingerprint Headers

The API also includes build information:
- `X-ATP-Backend-Commit`: Git commit SHA
- `X-ATP-Backend-BuildTime`: Build timestamp (ISO 8601)

These help verify which code version is running.

## Troubleshooting

**Issue: Script refuses to run on host**
- Solution: Use `backend/scripts/run_in_backend_container.sh`

**Issue: Database mismatch error (exit code 3)**
- Solution: Script is using a different DB than the API. Run via container wrapper.

**Issue: API not reachable**
- Solution: Ensure backend container is running: `docker compose --profile aws ps backend-aws`

## Exit Codes

- `0`: Success
- `2`: Refused to run on host (use container wrapper)
- `3`: Database fingerprint mismatch (use container wrapper)
- Other: Script-specific errors

## Deployment Verification

After rebuilding the backend image, verify scripts are included:

```bash
cd /home/ubuntu/automated-trading-platform
docker compose --profile aws build --no-cache backend-aws
docker compose --profile aws up -d backend-aws
docker exec $(docker compose --profile aws ps -q backend-aws) sh -lc "ls -la /app/scripts | head -30"
docker exec $(docker compose --profile aws ps -q backend-aws) sh -lc "test -f /app/scripts/print_api_fingerprints.py && echo OK || echo MISSING"
```

### Complete Verification Script (All Steps)

Run this complete script to verify the fix end-to-end:

```bash
ssh hilovivo-aws '
set -euo pipefail

REPO="/home/ubuntu/automated-trading-platform"
cd "$REPO"

echo "=============================="
echo "Complete Verification Process"
echo "=============================="

# Step 1: Verify Dockerfile has the fix
echo ""
echo "1) Checking Dockerfile..."
if grep -q "COPY scripts/ /app/scripts/" backend/Dockerfile && grep -q "RUN test -f /app/scripts/print_api_fingerprints.py" backend/Dockerfile; then
    echo "✅ Dockerfile contains both COPY and RUN test"
else
    echo "❌ Dockerfile missing required lines"
    exit 1
fi

# Step 2: Rebuild
echo ""
echo "2) Rebuilding backend-aws image..."
docker compose --profile aws build --no-cache backend-aws
echo "✅ Build completed"

# Step 3: Restart container
echo ""
echo "3) Restarting backend-aws container..."
docker compose --profile aws up -d --force-recreate backend-aws
sleep 5

# Step 4: Verify in container
echo ""
echo "4) Verifying in running container..."
CID=$(docker compose --profile aws ps -q backend-aws)
if docker exec "$CID" sh -lc "test -f /app/scripts/print_api_fingerprints.py" 2>/dev/null; then
    echo "✅ Container verification: File exists"
    docker exec "$CID" sh -lc "ls -lh /app/scripts/print_api_fingerprints.py"
else
    echo "❌ Container verification: File MISSING"
    exit 1
fi

# Step 5: Verify in image (robust method)
echo ""
echo "5) Verifying in image..."
CID=$(docker compose --profile aws ps -q backend-aws)

# Try to get image reference from docker compose config first
IMAGE_REF=$(docker compose --profile aws config 2>/dev/null | awk '\''/backend-aws:/{f=1} f && /image:/{print $2; exit}'\'' | head -1)

# If compose config doesn't have explicit image, get it from container
if [ -z "$IMAGE_REF" ] || [ "$IMAGE_REF" = "null" ]; then
    RAW=$(docker inspect "$CID" --format '\''{{.Image}}'\'' 2>/dev/null || echo "")
    if [ -n "$RAW" ]; then
        # Ensure sha256: prefix is present
        if [[ "$RAW" == sha256:* ]]; then
            IMAGE_REF="$RAW"
        else
            IMAGE_REF="sha256:$RAW"
        fi
    fi
fi

if [ -z "$IMAGE_REF" ]; then
    echo "❌ Could not determine image reference"
    exit 1
fi

echo "Testing image: $IMAGE_REF"
if docker run --rm "$IMAGE_REF" sh -lc "test -f /app/scripts/print_api_fingerprints.py" 2>/dev/null; then
    echo "✅ Image verification: File exists"
else
    echo "❌ Image verification: File MISSING"
    exit 1
fi

echo ""
echo "=============================="
echo "✅ ALL VERIFICATIONS PASSED"
echo "=============================="
'
```

### Step 4: Verify in Container (Standalone)

```bash
ssh hilovivo-aws '
set -euo pipefail

REPO="/home/ubuntu/automated-trading-platform"
cd "$REPO"

echo "=============================="
echo "Step 4: Verifying in running container"
echo "=============================="

# Get container ID
CID=$(docker compose --profile aws ps -q backend-aws)
if [ -z "$CID" ]; then
    echo "Starting backend-aws container..."
    docker compose --profile aws up -d backend-aws
    sleep 5
    CID=$(docker compose --profile aws ps -q backend-aws)
fi

echo "Container ID: $CID"
echo ""

# Verify script exists
docker exec "$CID" sh -lc "ls -la /app/scripts | head -10"
echo ""
docker exec "$CID" sh -lc "test -f /app/scripts/print_api_fingerprints.py && echo '\''✅ OK: File exists in container'\'' || echo '\''❌ MISSING: File not found in container'\''"
'
```

### Step 5: Verify in Image (Standalone - Robust Method)

```bash
ssh hilovivo-aws '
set -euo pipefail

REPO="/home/ubuntu/automated-trading-platform"
cd "$REPO"

echo "=============================="
echo "Step 5: Verifying in image (not container)"
echo "=============================="

# Get container ID to find its image
CID=$(docker compose --profile aws ps -q backend-aws)
if [ -z "$CID" ]; then
    echo "❌ Backend container not running"
    exit 1
fi

# Try to get image reference from docker compose config first
IMAGE_REF=$(docker compose --profile aws config 2>/dev/null | awk '\''/backend-aws:/{f=1} f && /image:/{print $2; exit}'\'' | head -1)

# If compose config doesn'\''t have explicit image, get it from container
if [ -z "$IMAGE_REF" ] || [ "$IMAGE_REF" = "null" ]; then
    RAW=$(docker inspect "$CID" --format '\''{{.Image}}'\'' 2>/dev/null || echo "")
    if [ -n "$RAW" ]; then
        # Ensure sha256: prefix is present
        if [[ "$RAW" == sha256:* ]]; then
            IMAGE_REF="$RAW"
        else
            IMAGE_REF="sha256:$RAW"
        fi
    fi
fi

if [ -z "$IMAGE_REF" ]; then
    echo "❌ Could not determine image reference"
    exit 1
fi

echo "Testing image: $IMAGE_REF"
docker run --rm "$IMAGE_REF" sh -lc "test -f /app/scripts/print_api_fingerprints.py && echo '\''✅ OK: File exists in image'\'' || echo '\''❌ MISSING: File not found in image'\''"
'
```

