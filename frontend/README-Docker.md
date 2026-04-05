# Docker Build and Run Instructions

This document provides instructions for building and running the frontend Docker image in production mode.

## Prerequisites

- Docker installed and running
- Node.js 20 (used in the Docker image)

## Build the Image

```bash
cd frontend

docker build --no-cache -t automated-trading-platform-frontend:latest .
```

## Run the Container

```bash
cd frontend

docker run --rm -p 3000:3000 automated-trading-platform-frontend:latest
```

The frontend will be available at `http://localhost:3000`.

## Health Check

The container includes a healthcheck that runs every 30 seconds. You can verify the health status with:

```bash
docker ps
```

Look for the "healthy" status in the STATUS column.

## Docker Scout

To scan for vulnerabilities in the built image:

```bash
docker scout cves automated-trading-platform-frontend:latest
```

Or use Docker Desktop's Docker Scout feature to visualize and track vulnerabilities over time.

## Notes

- The Dockerfile uses a multi-stage build for optimal image size
- The image runs as a non-root user for security
- Only production dependencies are included in the final image
- The standalone build output ensures minimal runtime footprint

