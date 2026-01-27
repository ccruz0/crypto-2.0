#!/bin/bash
# Final verification script after fixes are applied
# Run this on AWS: ssh ubuntu@47.130.143.159 "cd ~/automated-trading-platform && bash scripts/verify_telegram_green_aws.sh"

set -euo pipefail

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo /home/ubuntu/automated-trading-platform)"

echo "=========================================="
echo "Telegram GREEN Verification"
echo "=========================================="
echo ""

# Discover backend container
BACKEND_CONTAINER=""
if command -v docker > /dev/null 2>&1 && docker compose --profile aws ps backend-aws > /dev/null 2>&1; then
    BACKEND_CONTAINER="backend-aws"
elif docker ps --filter "name=backend-aws" --format "{{.Names}}" | grep -q .; then
    BACKEND_CONTAINER=$(docker ps --filter "name=backend-aws" --format "{{.Names}}" | head -1)
else
    echo "❌ ERROR: backend-aws container not found"
    exit 1
fi

# Function to exec in backend container
exec_backend() {
    if [ "$BACKEND_CONTAINER" == "backend-aws" ]; then
        docker compose --profile aws exec -T backend-aws "$@"
    else
        docker exec -i "$BACKEND_CONTAINER" "$@"
    fi
}

# Check health endpoint
echo "=== Health Endpoint Check ==="
HEALTH_RESPONSE=$(curl -s http://localhost:8002/api/health/system || echo "")
if [ -z "$HEALTH_RESPONSE" ]; then
    echo "❌ Health endpoint not responding"
    exit 1
fi

# Extract telegram section (without jq)
TELEGRAM_SECTION=$(echo "$HEALTH_RESPONSE" | grep -o '"telegram":{[^}]*}' || echo "")

if [ -z "$TELEGRAM_SECTION" ]; then
    echo "⚠️  Could not extract telegram section, showing full response:"
    echo "$HEALTH_RESPONSE"
    echo ""
else
    echo "Telegram health section:"
    echo "$TELEGRAM_SECTION"
    echo ""
    
    # Extract status and enabled (simple parsing without jq)
    TELEGRAM_STATUS=$(echo "$TELEGRAM_SECTION" | grep -o '"status":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
    TELEGRAM_ENABLED=$(echo "$TELEGRAM_SECTION" | grep -o '"enabled":[^,}]*' | cut -d':' -f2 | tr -d ' ' || echo "false")
    
    echo "Status: $TELEGRAM_STATUS"
    echo "Enabled: $TELEGRAM_ENABLED"
    echo ""
fi

# Check logs for telegram startup
echo "=== Recent Telegram Logs ==="
if [ "$BACKEND_CONTAINER" == "backend-aws" ]; then
    docker compose --profile aws logs backend-aws --tail 100 | grep -E "\[TELEGRAM_STARTUP\]|\[TELEGRAM_HEALTH\]|\[TELEGRAM_SEND\]|\[TELEGRAM_RESPONSE\]|\[TELEGRAM_API_CALL\]" | tail -15 || echo "No telegram logs found"
else
    docker logs "$BACKEND_CONTAINER" --tail 100 | grep -E "\[TELEGRAM_STARTUP\]|\[TELEGRAM_HEALTH\]|\[TELEGRAM_SEND\]|\[TELEGRAM_RESPONSE\]|\[TELEGRAM_API_CALL\]" | tail -15 || echo "No telegram logs found"
fi
echo ""

# Check container status
echo "=== Container Status ==="
if [ "$BACKEND_CONTAINER" == "backend-aws" ]; then
    docker compose --profile aws ps backend-aws
else
    docker ps --filter "name=$BACKEND_CONTAINER" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
fi
echo ""

# Final verdict
if [ "$TELEGRAM_STATUS" == "PASS" ] && [ "$TELEGRAM_ENABLED" == "true" ]; then
    echo "✅ SUCCESS: Telegram is GREEN"
    exit 0
elif [ "$TELEGRAM_STATUS" == "PASS" ]; then
    echo "⚠️  WARNING: Status is PASS but enabled is not true"
    exit 1
else
    echo "❌ FAIL: Telegram is still RED (status: $TELEGRAM_STATUS)"
    echo ""
    echo "Run diagnostic to see which gates are failing:"
    echo "  bash scripts/check_telegram_gates_aws.sh"
    exit 1
fi
