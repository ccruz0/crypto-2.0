#!/bin/bash
# Run on EC2 (e.g. ssh ubuntu@<EC2_IP> 'bash -s' < scripts/run_order_history_deploy_and_capture.sh)
# Or copy to EC2 and run: bash run_order_history_deploy_and_capture.sh
set -e
REPO="${REPO:-$HOME/automated-trading-platform}"
cd "$REPO" || cd /home/ubuntu/crypto-2.0 || { echo "❌ No repo"; exit 1; }

echo "📥 git pull..."
git pull origin main || true

echo "🔨 Rebuild backend-aws (no cache)..."
sudo docker compose --profile aws build --no-cache backend-aws

echo "🔄 Restart backend-aws..."
sudo docker compose --profile aws up -d --force-recreate backend-aws

echo "⏳ Wait 20s for backend to be ready..."
sleep 20

echo "📡 Trigger order history sync (sync=true)..."
curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:8002/api/orders/history?limit=10&offset=0&sync=true" && echo ""

echo "📋 Diagnostic log line:"
sudo docker compose --profile aws logs backend-aws --tail 300 2>&1 | grep -i "Order history response" || echo "(no match - check logs with: sudo docker compose --profile aws logs backend-aws --tail 200)"

echo ""
echo "Done. Share the 'Order history response:' line if present."
