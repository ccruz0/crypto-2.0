# Docker Build and Run Instructions for Backend

This document provides instructions for building and running the hardened backend Docker image in production mode.

## Prerequisites

- Docker installed and running
- Python 3.11 (used in the Docker image)
- bash (for running dependency locking scripts)

## Dependency Locking

Before building the image, generate or update `constraints.txt` to lock dependency versions with security patches:

```bash
cd backend

bash scripts/lock.sh
```

This script will:
1. Generate `constraints.txt` with pinned versions and hashes
2. Audit dependencies for vulnerabilities
3. Auto-upgrade only vulnerable packages to secure patch/minor versions
4. Validate the final constraints file

The `constraints.txt` file ensures deterministic, reproducible builds with locked secure versions.

## Build the Image

```bash
cd backend

docker build --no-cache -t automated-trading-platform-backend:latest .
```

The build process uses `constraints.txt` to ensure exact dependency versions and hashes are installed.

## Run the Container

```bash
cd backend

docker run --rm -p 8000:8000 \
  -e DATABASE_URL=postgresql://trader:traderpass@db:5432/atp \
  -e LIVE_TRADING=false \
  -e USE_CRYPTO_PROXY=false \
  automated-trading-platform-backend:latest
```

Or using docker-compose from the project root:

```bash
docker-compose up backend
```

## Quick Commands (Makefile)

You can also use the Makefile shortcuts:

```bash
cd backend

make lock    # Generate/update constraints.txt
make build   # Build Docker image
make run     # Run container
```

## Environment Variables

The following environment variables can be set to customize the backend:

- `DATABASE_URL`: PostgreSQL connection string (default: `postgresql://trader:traderpass@db:5432/atp`)
- `LIVE_TRADING`: Enable live trading (default: `false`)
- `USE_CRYPTO_PROXY`: Use crypto proxy service (default: `false`)
- `ENVIRONMENT`: Environment name (default: `local`)
- `API_BASE_URL`: API base URL (default: `http://localhost:8002`)
- `FRONTEND_URL`: Frontend URL (default: `http://localhost:3000`)

These can be set via:
- Environment variables in docker-compose.yml
- .env file in the project root
- Command line with `-e` flag

## Health Check

The container includes a healthcheck that runs every 30 seconds. You can verify the health status with:

```bash
docker ps
```

Look for the "healthy" status in the STATUS column.

To test the healthcheck manually:

```bash
curl http://localhost:8000/health
```

## Docker Scout

To scan for vulnerabilities in the built image:

```bash
docker scout cves automated-trading-platform-backend:latest
```

Or use Docker Desktop's Docker Scout feature:
1. Open Docker Desktop
2. Go to Images
3. Select `automated-trading-platform-backend:latest`
4. Click "Scan"

## Security Features

### Multi-Stage Build
- **Builder stage**: Compiles wheels for all dependencies
- **Runner stage**: Only installs runtime dependencies, excluding dev/test tools

### Non-Root User
- Container runs as `appuser` (UID 10001) instead of root
- Reduces attack surface in case of container escape

### Updated Dependencies
- **python-multipart**: Updated to >=0.0.18 (fixes CVE-2024-53981)
- **python-jose**: Updated to latest patch version
- **setuptools**: Automatically updated to latest stable version
- All dependencies pinned in `constraints.txt` with hashes for reproducibility and security

### Dependency Filtering
- Development dependencies (pytest, black, isort, flake8) are excluded from production image
- Only runtime dependencies are installed

### Dependency Locking
- `constraints.txt` is generated via `scripts/lock.sh` using pip-tools and pip-audit
- Ensures deterministic builds with locked secure versions
- Automatically upgrades vulnerable packages to safe patch/minor versions
- Includes dependency hashes for integrity verification

## Build Optimization

The Dockerfile uses several optimizations:

- **Wheel caching**: Dependencies are built as wheels in the builder stage
- **Layer caching**: Requirements are copied and installed in separate layers
- **Minimal base image**: Uses `python:3.11-slim-bookworm` for smaller image size
- **No build tools in runtime**: Build tools (gcc, build-essential) are only in builder stage

## Migration Notes

When migrating from the previous Dockerfile:

1. **User permissions**: The app now runs as `appuser` instead of root
2. **Healthcheck**: A healthcheck is now included for container monitoring
3. **Dependencies**: Only production dependencies are installed
4. **Security**: Vulnerable dependencies have been updated

## Production Recommendations

1. **Use environment variables**: Never hardcode credentials in Dockerfiles
2. **Use secrets**: For production, consider Docker secrets or external secret management
3. **Regular updates**: Rebuild the image periodically to get security patches
4. **Network security**: Limit backend exposure using Docker networks
5. **Monitoring**: Set up logging and monitoring for the healthcheck endpoint

