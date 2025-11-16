# Docker Build and Run Instructions for PostgreSQL Hardened

This document provides instructions for building and running the hardened PostgreSQL Docker image based on Alpine Linux.

## Prerequisites

- Docker installed and running
- PostgreSQL 15 (Alpine-based)

## Build the Image

```bash
cd docker/postgres

docker build --no-cache -t postgres-hardened:15 .
```

## Run the Container

```bash
cd docker/postgres

docker run --rm -p 5432:5432 \
  -e POSTGRES_USER=trader \
  -e POSTGRES_PASSWORD=traderpass \
  -e POSTGRES_DB=atp \
  postgres-hardened:15
```

Or using docker-compose from the project root:

```bash
docker-compose up db
```

## Environment Variables

The following environment variables can be set to customize the PostgreSQL instance:

- `POSTGRES_USER`: Database user (default: `trader`)
- `POSTGRES_PASSWORD`: Database password (default: `traderpass`)
- `POSTGRES_DB`: Database name (default: `atp`)
- `TZ`: Timezone (default: `UTC`)

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
docker exec <container_name> pg_isready -U trader
```

## Docker Scout

To scan for vulnerabilities in the built image:

```bash
docker scout cves postgres-hardened:15
```

Or use Docker Desktop's Docker Scout feature:
1. Open Docker Desktop
2. Go to Images
3. Select `postgres-hardened:15`
4. Click "Scan"

## Benefits of Alpine-based Image

- **Smaller size**: ~250 MB vs ~650 MB (Debian-based)
- **Reduced attack surface**: Alpine uses musl libc instead of glibc
- **Fewer vulnerabilities**: Eliminates CVE-2025-58xxx related to Debian and Golang stdlib
- **Faster startup**: Minimal base image with essential packages only
- **Security updates**: Alpine receives frequent security patches

## Migration Notes

When migrating from `postgres:15` (Debian) to this hardened Alpine image:

1. **Data persistence**: Existing volumes remain compatible
2. **Configuration**: Environment variables work the same way
3. **Backups**: Use standard PostgreSQL backup tools (pg_dump, pg_restore)
4. **Compatibility**: All PostgreSQL 15 features are available

## Production Recommendations

1. **Use environment variables**: Never hardcode credentials in Dockerfiles
2. **Use secrets**: For production, consider Docker secrets or external secret management
3. **Regular updates**: Rebuild the image periodically to get security patches
4. **Backup strategy**: Implement automated backups using cron or orchestration tools
5. **Network security**: Limit database exposure using Docker networks

