#!/bin/bash
# AWS Rollback Script
# Rollback to a specific commit hash
# Usage: ./scripts/rollback_aws.sh <commit-sha>

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory and repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

# Check for commit SHA argument
if [ $# -eq 0 ]; then
    echo -e "${RED}❌ ERROR: Commit SHA required${NC}"
    echo ""
    echo "Usage: $0 <commit-sha>"
    echo ""
    echo "Example:"
    echo "  $0 fd44bca06e6ff0ddd3147a46aaa6e89b06a6f580"
    echo "  $0 fd44bca  # Short SHA also works"
    exit 1
fi

TARGET_COMMIT="$1"

echo "=========================================="
echo "AWS Rollback"
echo "=========================================="
echo ""

# Verify we're in the right directory
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}❌ ERROR: docker-compose.yml not found. Are you in the repo root?${NC}"
    exit 1
fi

# Show current state
CURRENT_COMMIT=$(git rev-parse HEAD)
CURRENT_COMMIT_SHORT=$(git rev-parse --short HEAD)
echo "📊 Current state:"
echo "   HEAD: $CURRENT_COMMIT_SHORT ($CURRENT_COMMIT)"
echo ""

# Step 1: Fetch latest from origin
echo "📥 Fetching latest from origin..."
git fetch --all || {
    echo -e "${RED}❌ ERROR: Failed to fetch from origin${NC}"
    exit 1
}

# Step 2: Verify target commit exists
echo "🔍 Verifying target commit exists..."
if ! git cat-file -e "$TARGET_COMMIT" 2>/dev/null; then
    echo -e "${RED}❌ ERROR: Commit $TARGET_COMMIT not found${NC}"
    echo ""
    echo "Available commits (last 10):"
    git log --oneline -10
    exit 1
fi

TARGET_COMMIT_FULL=$(git rev-parse "$TARGET_COMMIT")
TARGET_COMMIT_SHORT=$(git rev-parse --short "$TARGET_COMMIT_FULL")

echo "   Target: $TARGET_COMMIT_SHORT ($TARGET_COMMIT_FULL)"
echo ""

# Step 3: Checkout target commit
echo "🔀 Checking out target commit..."
git checkout "$TARGET_COMMIT_FULL" || {
    echo -e "${RED}❌ ERROR: Failed to checkout commit $TARGET_COMMIT_FULL${NC}"
    exit 1
}

# Step 4: Verify git state
VERIFIED_COMMIT=$(git rev-parse HEAD)
if [ "$VERIFIED_COMMIT" != "$TARGET_COMMIT_FULL" ]; then
    echo -e "${RED}❌ ERROR: Git state mismatch after checkout${NC}"
    echo "   Expected: $TARGET_COMMIT_FULL"
    echo "   Got: $VERIFIED_COMMIT"
    exit 1
fi

echo "✅ Git state verified: $TARGET_COMMIT_SHORT"
echo ""

# Step 5: Build and start services
echo "🚀 Building and starting services..."
docker compose --profile aws up -d --build || {
    echo -e "${RED}❌ ERROR: Failed to start services${NC}"
    exit 1
}

# Step 6: Wait for services to start
echo ""
echo "⏳ Waiting for services to start (15 seconds)..."
sleep 15

# Step 7: Verify services
echo ""
echo "✅ Service status:"
docker compose --profile aws ps || {
    echo -e "${RED}❌ ERROR: Failed to get service status${NC}"
    exit 1
}

# Step 8: Health check
echo ""
echo "🏥 Health check..."
HEALTH_URL="http://localhost:8002/api/health"
HEALTH_RESPONSE=$(curl -sS "$HEALTH_URL" || echo "")

if [ -z "$HEALTH_RESPONSE" ]; then
    echo -e "${YELLOW}⚠️  WARNING: Health endpoint not responding${NC}"
    echo "   URL: $HEALTH_URL"
    echo "   This may be expected if services are still starting"
else
    if command -v jq &> /dev/null; then
        HEALTH_STATUS=$(echo "$HEALTH_RESPONSE" | jq -r '.status // "UNKNOWN"')
        echo "   Health status: $HEALTH_STATUS"
    else
        echo "   Health endpoint responded"
    fi
fi

# Summary
echo ""
echo "=========================================="
echo -e "${GREEN}✅ Rollback completed!${NC}"
echo "=========================================="
echo ""
echo "📊 Summary:"
echo "   Previous: $CURRENT_COMMIT_SHORT"
echo "   Current:  $TARGET_COMMIT_SHORT"
echo "   Services: $(docker compose --profile aws ps --format json | jq -r 'length' 2>/dev/null || echo 'N/A') running"
echo ""
echo "🔍 Verify rollback:"
echo "   git rev-parse HEAD"
echo "   curl -s http://localhost:8002/api/health/system | jq ."
echo ""

