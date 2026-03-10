#!/bin/bash
# Quick deploy of ExchangeOrder fix via SSM (direct file copy method)

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🔧 Deploying ExchangeOrder Fix"
echo "=============================="
echo ""
echo "⚠️  Note: This fix modifies backend/app/services/signal_monitor.py"
echo "   The file must be deployed via git or direct copy."
echo ""
echo "Option 1: Git (Recommended)"
echo "  1. git add backend/app/services/signal_monitor.py"
echo "  2. git commit -m 'Fix: Remove redundant ExchangeOrder imports'"
echo "  3. git push"
echo "  4. On AWS: git pull && docker restart automated-trading-platform-backend-aws-1"
echo ""
echo "Option 2: Direct SSM (for quick test)"
echo "  This requires base64 encoding the file, which is complex."
echo "  Better to use git method above."
echo ""
echo "Current status: Fix is applied locally, ready to commit/push"
