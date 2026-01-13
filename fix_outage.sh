#!/bin/bash
# Fix outage script - to be run on AWS server
# This script fixes: Telegram config, market data staleness, scheduler stall

set -e

cd /home/ubuntu/automated-trading-platform

echo "=========================================="
echo "OUTAGE FIX SCRIPT"
echo "=========================================="
echo ""

# Step 1: Fix Telegram config
echo "Step 1: Fixing Telegram config..."
if [ -f .env.aws ]; then
    # Check if TELEGRAM_CHAT_ID_AWS is missing
    if ! grep -q "^TELEGRAM_CHAT_ID_AWS=" .env.aws; then
        # Get existing TELEGRAM_CHAT_ID if available
        EXISTING_CHAT_ID=$(grep "^TELEGRAM_CHAT_ID=" .env.aws | cut -d'=' -f2 | tr -d '"' | tr -d "'" || echo "")
        if [ -n "$EXISTING_CHAT_ID" ]; then
            echo "Adding TELEGRAM_CHAT_ID_AWS=$EXISTING_CHAT_ID to .env.aws"
            echo "TELEGRAM_CHAT_ID_AWS=$EXISTING_CHAT_ID" >> .env.aws
        else
            echo "ERROR: TELEGRAM_CHAT_ID_AWS not found and TELEGRAM_CHAT_ID not available"
            echo "Please set TELEGRAM_CHAT_ID_AWS in .env.aws manually"
            exit 1
        fi
    else
        echo "TELEGRAM_CHAT_ID_AWS already exists in .env.aws"
    fi
    
    # Ensure ENVIRONMENT=aws
    if ! grep -q "^ENVIRONMENT=aws" .env.aws; then
        # Remove any existing ENVIRONMENT line and add correct one
        sed -i '/^ENVIRONMENT=/d' .env.aws
        echo "ENVIRONMENT=aws" >> .env.aws
        echo "Set ENVIRONMENT=aws in .env.aws"
    fi
else
    echo "ERROR: .env.aws not found"
    exit 1
fi

# Step 2: Start market-updater
echo ""
echo "Step 2: Starting market-updater..."
docker compose --profile aws up -d market-updater-aws
sleep 5
docker logs --tail 50 market-updater-aws

# Step 3: Restart backend to load new env vars
echo ""
echo "Step 3: Restarting backend to load new env vars..."
docker compose --profile aws restart backend-aws
sleep 10

# Step 4: Check scheduler status
echo ""
echo "Step 4: Checking scheduler status..."
docker exec automated-trading-platform-backend-aws-1 env | grep -E "DEBUG_DISABLE_SIGNAL_MONITOR|DISABLE_SIGNAL_MONITOR" || echo "No signal monitor disable flags found"

# Try to start signal monitor via API
echo ""
echo "Step 5: Attempting to start signal monitor..."
curl -sS -X POST http://localhost:8002/api/control/start-signal-monitor || echo "API endpoint not available or already running"

echo ""
echo "=========================================="
echo "FIXES APPLIED"
echo "=========================================="
echo ""
echo "Waiting 30 seconds for services to stabilize..."
sleep 30

echo ""
echo "Checking status..."
docker compose --profile aws ps

echo ""
echo "Market updater logs (last 20):"
docker logs --tail 20 market-updater-aws 2>&1 || echo "Market updater not running"

echo ""
echo "Backend logs (last 20):"
docker logs --tail 20 automated-trading-platform-backend-aws-1 2>&1 | grep -E "HEARTBEAT|GLOBAL_BLOCKER|Signal monitor|TELEGRAM" || echo "No relevant logs found"





