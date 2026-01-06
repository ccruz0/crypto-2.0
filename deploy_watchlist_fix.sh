#!/bin/bash
# Deploy script for watchlist consistency fix
# Run this on AWS server

set -e

echo "=========================================="
echo "Deploying Watchlist Consistency Fix"
echo "=========================================="
echo ""

cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform

echo "1. Pulling latest code..."
git pull origin main

echo ""
echo "2. Building backend with new changes..."
docker compose --profile aws build --no-cache backend-aws

echo ""
echo "3. Restarting backend service..."
docker compose --profile aws up -d backend-aws

echo ""
echo "4. Waiting for service to start..."
sleep 15

echo ""
echo "5. Checking service status..."
docker compose --profile aws ps backend-aws

echo ""
echo "6. Verifying deployment..."
docker compose --profile aws exec -T backend-aws python3 << 'PYTHON_SCRIPT'
import sys
sys.path.insert(0, '/app')

# Test that the fix is deployed by checking if the function exists and has the new code
from app.api.routes_dashboard import _serialize_watchlist_item
import inspect

# Check function source for our new code
source = inspect.getsource(_serialize_watchlist_item)
if 'default_sl_tp_mode' in source and 'market_data_missing_fields' in source:
    print("✅ Fix deployed successfully!")
    print("   - Default values for sl_tp_mode, order_status, exchange")
    print("   - MarketData missing fields logging")
else:
    print("❌ Fix not found in code")
    sys.exit(1)
PYTHON_SCRIPT

echo ""
echo "7. Checking backend logs for any errors..."
docker compose --profile aws logs backend-aws --tail=20 | grep -i error || echo "   No errors found"

echo ""
echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Monitor logs for MarketData warnings:"
echo "   docker compose --profile aws logs backend-aws | grep 'MarketData missing fields'"
echo ""
echo "2. Verify MarketData status:"
echo "   docker compose --profile aws exec backend-aws python3 scripts/verify_market_data_status.py"
echo ""
echo "3. Check watchlist API response to verify default values are present"













