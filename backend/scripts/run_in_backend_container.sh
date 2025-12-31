#!/bin/bash
# Wrapper script to run verification scripts inside the backend container
# Ensures scripts use the same database as the API

set -euo pipefail

# Find the backend container (AWS profile)
CONTAINER_NAME="automated-trading-platform-backend-aws-1"
SERVICE_NAME="backend-aws"

# Try to find container by name first, then by service
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    # Try to find by service name pattern
    CONTAINER_NAME=$(docker ps --filter "name=backend-aws" --format '{{.Names}}' | head -1)
    if [ -z "$CONTAINER_NAME" ]; then
        echo "❌ Error: Could not find backend container (backend-aws)" >&2
        echo "   Make sure docker compose --profile aws is running" >&2
        exit 1
    fi
fi

echo "📦 Container: $CONTAINER_NAME"

# Get build fingerprint from container env
GIT_SHA=$(docker exec "$CONTAINER_NAME" sh -c 'echo "${ATP_GIT_SHA:-unknown}"' 2>/dev/null || echo "unknown")
BUILD_TIME=$(docker exec "$CONTAINER_NAME" sh -c 'echo "${ATP_BUILD_TIME:-unknown}"' 2>/dev/null || echo "unknown")
echo "🔖 Backend commit: ${GIT_SHA:0:8} (built: $BUILD_TIME)"

# Execute command inside container
echo "▶️  Executing: $*"
echo ""

# Pass through exit code
docker exec "$CONTAINER_NAME" "$@"
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Command completed successfully"
else
    echo "❌ Command failed with exit code $EXIT_CODE"
fi

exit $EXIT_CODE

