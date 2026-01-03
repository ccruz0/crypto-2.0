#!/bin/bash
# Script to check order on production server
# Run this on the production server via SSH or Docker exec

ORDER_ID="5755600481538037740"

echo "🔍 Checking order $ORDER_ID on production..."
echo ""

# Try to run inside Docker container first
if docker compose exec -T backend-aws python3 check_specific_order.py "$ORDER_ID" 2>/dev/null; then
    exit 0
fi

# Fallback: run directly if not in Docker
cd ~/automated-trading-platform/backend 2>/dev/null || cd /home/ubuntu/automated-trading-platform/backend
python3 check_specific_order.py "$ORDER_ID"





