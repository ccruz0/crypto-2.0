#!/bin/bash
# Deploy audit fixes to AWS
# This script deploys the heartbeat logging and global blocker warnings

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🚀 Deploying Audit Fixes to AWS"
echo "================================"
echo ""

# Check if we're in the right directory
if [ ! -f "docker-compose.yml" ]; then
    echo "❌ Error: docker-compose.yml not found. Are you in the project root?"
    exit 1
fi

# Check if .env.aws exists
if [ ! -f ".env.aws" ]; then
    echo "⚠️  Warning: .env.aws not found. Some environment variables may not be set."
fi

echo "📋 Changes being deployed:"
echo "  - Heartbeat logging every 10 cycles (~5 minutes)"
echo "  - Global blocker warnings for Telegram and watchlist"
echo "  - Improved Telegram blocking log visibility"
echo ""

# Build and deploy backend-aws
echo "🔨 Building backend-aws..."
docker compose --profile aws build backend-aws

echo "🚀 Starting backend-aws..."
docker compose --profile aws up -d backend-aws

echo "⏳ Waiting for service to start..."
sleep 5

# Restart to ensure env vars load
echo "🔄 Restarting to ensure environment variables load..."
docker compose --profile aws restart backend-aws

echo "✅ Deployment complete!"
echo ""
echo "📊 Verification steps:"
echo "  1. Check logs for heartbeat:"
echo "     docker logs -f backend-aws | grep HEARTBEAT"
echo ""
echo "  2. Check for global blockers:"
echo "     docker logs backend-aws | grep GLOBAL_BLOCKER"
echo ""
echo "  3. Verify SignalMonitorService started:"
echo "     docker logs backend-aws | grep 'Signal monitor service'"
echo ""
echo "  4. Run audit script:"
echo "     docker exec backend-aws python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24"
echo ""

