#!/bin/bash
# Health check script for AWS backend
# Usage: bash scripts/check_runtime_health_aws.sh

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

REMOTE_HOST="hilovivo-aws"
REMOTE_PATH="/home/ubuntu/automated-trading-platform"

echo -e "${BLUE}Running runtime health check on AWS backend...${NC}"
echo ""

# Detect backend container name dynamically
CONTAINER_NAME=$(ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker ps --format '{{.Names}}' | grep -E 'automated-trading-platform-backend' | head -1" 2>&1 || echo "")

if [ -z "$CONTAINER_NAME" ]; then
    echo -e "${RED}❌ Error: No backend container found matching 'automated-trading-platform-backend'${NC}"
    exit 1
fi

echo -e "${BLUE}Backend container: $CONTAINER_NAME${NC}"
echo ""

# Run health check script inside container
# Working directory is /app, backend folder is at /app/backend
HEALTH_CHECK_OUTPUT=$(ssh "$REMOTE_HOST" "cd $REMOTE_PATH && docker exec \"$CONTAINER_NAME\" sh -c 'cd /app && python3 backend/scripts/check_runtime_health.py 2>&1 || python backend/scripts/check_runtime_health.py 2>&1 || echo \"⚠️  Health check script not found in container\"'" 2>&1)

if echo "$HEALTH_CHECK_OUTPUT" | grep -q "⚠️  Health check script not found"; then
    echo -e "${YELLOW}⚠️  Health check script not found in container${NC}"
    echo -e "${YELLOW}   Expected path: /app/backend/scripts/check_runtime_health.py${NC}"
    exit 1
else
    echo "$HEALTH_CHECK_OUTPUT"
    # Check exit code from the Python script output
    if echo "$HEALTH_CHECK_OUTPUT" | grep -q "❌\|FAILED"; then
        exit 1
    elif echo "$HEALTH_CHECK_OUTPUT" | grep -q "⚠️\|WARNINGS"; then
        exit 0
    else
        exit 0
    fi
fi
