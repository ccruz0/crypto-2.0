#!/bin/bash
# Verification script to ensure required scripts exist in backend container and image
# This prevents regressions where scripts exist in repo but are missing in container/image

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=============================="
echo "Backend Image Scripts Verification"
echo "=============================="
echo ""

# Get container ID from docker compose
echo "1) Finding backend-aws container..."
CID=$(docker compose --profile aws ps -q backend-aws 2>/dev/null || echo "")
if [ -z "$CID" ]; then
    # Fallback: try to find by container name pattern
    CID=$(docker ps --filter "name=automated-trading-platform-backend-aws" --format '{{.ID}}' | head -1)
    if [ -z "$CID" ]; then
        echo "❌ ERROR: backend-aws container not found"
        echo "   Make sure docker compose --profile aws is running"
        exit 1
    fi
fi
echo "   Container ID: $CID"
echo ""

# Get image SHA from container
echo "2) Extracting image reference from container..."
RAW_IMAGE=$(docker inspect "$CID" --format '{{.Image}}' 2>/dev/null || echo "")
if [ -z "$RAW_IMAGE" ]; then
    echo "❌ ERROR: Could not get image reference from container"
    exit 1
fi

# Ensure sha256: prefix
if [[ "$RAW_IMAGE" == sha256:* ]]; then
    IMAGE_REF="$RAW_IMAGE"
else
    IMAGE_REF="sha256:$RAW_IMAGE"
fi
echo "   Image: $IMAGE_REF"
echo ""

# Check in running container
echo "3) Verifying scripts in running container..."
REQUIRED_FILE="/app/scripts/print_api_fingerprints.py"
if docker exec "$CID" sh -lc "test -f $REQUIRED_FILE" 2>/dev/null; then
    echo "   ✅ $REQUIRED_FILE exists in container"
    docker exec "$CID" sh -lc "ls -lh $REQUIRED_FILE" 2>/dev/null || true
else
    echo "   ❌ ERROR: $REQUIRED_FILE MISSING in container"
    exit 1
fi
echo ""

# Check in fresh container from image
echo "4) Verifying scripts in fresh container from image..."
if docker run --rm "$IMAGE_REF" sh -lc "test -f $REQUIRED_FILE" 2>/dev/null; then
    echo "   ✅ $REQUIRED_FILE exists in image"
    docker run --rm "$IMAGE_REF" sh -lc "ls -lh $REQUIRED_FILE" 2>/dev/null || true
else
    echo "   ❌ ERROR: $REQUIRED_FILE MISSING in image"
    exit 1
fi
echo ""

echo "=============================="
echo "✅ ALL CHECKS PASSED"
echo "=============================="
echo ""
echo "Scripts verification complete. Both container and image contain required files."

