#!/bin/bash
# Simple manual deployment script for order cancellation notifications
# Run this if you have SSH access to AWS EC2

set -e

echo "🚀 Manual Deployment - Order Cancellation Notifications"
echo "========================================================"
echo ""

# Update this with your EC2 IP or use SSH alias
EC2_HOST="${1:-ubuntu@<AWS_EC2_IP>}"
EC2_USER_HOST="${EC2_HOST#*@}"

echo "📥 Pulling latest code from git..."
ssh "$EC2_HOST" "cd ~/crypto-2.0 && git pull origin main"

echo ""
echo "🔄 Restarting backend service..."
ssh "$EC2_HOST" "cd ~/crypto-2.0 && docker compose --profile aws restart backend-aws"

echo ""
echo "⏳ Waiting 5 seconds for service to start..."
sleep 5

echo ""
echo "✅ Checking service status..."
ssh "$EC2_HOST" "cd ~/crypto-2.0 && docker compose --profile aws ps backend-aws"

echo ""
echo "📋 Recent backend logs..."
ssh "$EC2_HOST" "cd ~/crypto-2.0 && docker compose --profile aws logs --tail=30 backend-aws"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "💡 To verify notifications are working:"
echo "   - Cancel a test order via API"
echo "   - Check Telegram channel for notification"

