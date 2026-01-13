# Docker Build Context for Backend

## Why Build Context Must Be "." (Repo Root)

The backend Dockerfile requires access to files from multiple locations:
- `backend/scripts/` - Verification and utility scripts
- `backend/requirements.txt` - Python dependencies
- `backend/entrypoint.sh` - Container entrypoint
- `backend/app/` - Application code

**CRITICAL**: The docker-compose.yml for `backend-aws` service must use:
```yaml
build:
  context: .           # Repo root, NOT ./backend
  dockerfile: backend/Dockerfile
```

If `context: ./backend` is used, the Dockerfile cannot access `backend/scripts/` because the build context would only include files within the `./backend` directory. The Dockerfile expects the build context to be the repo root, so it can copy `backend/scripts/`, `backend/requirements.txt`, etc.

## Verification

After building the backend image, verify scripts are included:

```bash
cd /home/ubuntu/automated-trading-platform
docker compose --profile aws build --no-cache backend-aws
docker compose --profile aws up -d backend-aws
./backend/scripts/verify_image_scripts.sh
```

Or manually:
```bash
# Check in running container
docker exec $(docker compose --profile aws ps -q backend-aws) sh -lc "test -f /app/scripts/print_api_fingerprints.py && echo OK || echo MISSING"

# Check in image
IMAGE_SHA=$(docker inspect $(docker compose --profile aws ps -q backend-aws) --format '{{.Image}}')
docker run --rm "$IMAGE_SHA" sh -lc "test -f /app/scripts/print_api_fingerprints.py && echo OK || echo MISSING"
```

## Failure Symptoms

If build context is wrong (`context: ./backend`), you'll see:
- Build succeeds (because COPY commands fail silently if source doesn't exist in context)
- File exists in repo: `ls backend/scripts/print_api_fingerprints.py` ✅
- File missing in container: `docker exec <container> test -f /app/scripts/print_api_fingerprints.py` ❌
- Build-time assertion may pass if COPY silently fails (scripts directory doesn't exist in context)

The Dockerfile includes build-time assertions that will fail if scripts are missing, but only if the COPY command actually runs. If the build context doesn't include the scripts directory, the COPY will fail the build, which is the desired behavior.





