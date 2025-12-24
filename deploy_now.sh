#!/bin/bash
# Quick deploy script for Telegram fix

set -e

echo "🚀 Deploying Telegram /start fix..."
echo ""

# Check if we can use docker compose
if command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
elif docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
else
    echo "❌ Docker Compose not found"
    exit 1
fi

echo "📦 Rebuilding backend-aws..."
$COMPOSE_CMD --profile aws build backend-aws

echo ""
echo "🔄 Restarting backend-aws..."
$COMPOSE_CMD --profile aws up -d backend-aws

echo ""
echo "⏳ Waiting for container to start..."
sleep 10

echo ""
echo "✅ Checking container status..."
$COMPOSE_CMD --profile aws ps backend-aws

echo ""
echo "🔍 Running diagnostics..."
$COMPOSE_CMD --profile aws exec backend-aws python -m tools.telegram_diag 2>/dev/null || {
    echo "⚠️  Diagnostics tool may not be ready yet. Wait a few more seconds and run:"
    echo "   $COMPOSE_CMD --profile aws exec backend-aws python -m tools.telegram_diag"
}

echo ""
echo "📋 Recent logs (Telegram-related):"
$COMPOSE_CMD --profile aws logs --tail=30 backend-aws 2>/dev/null | grep -i "TG\|telegram\|webhook\|poller" | tail -10 || echo "   (No Telegram logs in last 30 lines)"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Next: Test /start command in Telegram"
