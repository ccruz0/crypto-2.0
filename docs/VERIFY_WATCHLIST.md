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

