#!/bin/bash
# AWS Backend Deployment Script
# Run this on your AWS server

set -e

echo "=== AWS Backend Deployment ==="
echo ""

# Check if .env.aws exists
if [ ! -f .env.aws ]; then
    echo "❌ ERROR: .env.aws file not found!"
    echo "Please ensure .env.aws exists with Crypto.com credentials"
    exit 1
fi

# Verify credentials are in .env.aws
if ! grep -q "EXCHANGE_CUSTOM_API_KEY" .env.aws; then
    echo "❌ ERROR: EXCHANGE_CUSTOM_API_KEY not found in .env.aws"
    exit 1
fi

if ! grep -q "EXCHANGE_CUSTOM_API_SECRET" .env.aws; then
    echo "❌ ERROR: EXCHANGE_CUSTOM_API_SECRET not found in .env.aws"
    exit 1
fi

echo "✅ .env.aws file found with credentials"
echo ""

# Check outbound IP
echo "Checking outbound IP..."
OUTBOUND_IP=$(curl -s --max-time 5 https://api.ipify.org)
echo "Current outbound IP: $OUTBOUND_IP"
echo "Expected AWS Elastic IP: 47.130.143.159"

if [ "$OUTBOUND_IP" != "47.130.143.159" ]; then
    echo "⚠️  WARNING: Outbound IP doesn't match expected AWS Elastic IP"
    echo "   Authentication may fail if this IP is not whitelisted in Crypto.com"
else
    echo "✅ Outbound IP matches AWS Elastic IP"
fi

echo ""
echo "Stopping existing backend-aws if running..."
docker compose --profile aws stop backend-aws 2>/dev/null || true

echo ""
echo "Starting backend-aws..."
docker compose --profile aws up -d backend-aws

echo ""
echo "Waiting for backend to start..."
sleep 10

echo ""
echo "Checking backend status..."
if docker ps | grep -q backend-aws; then
    echo "✅ Backend-aws is running"
else
    echo "❌ Backend-aws failed to start"
    echo "Checking logs..."
    docker compose --profile aws logs backend-aws --tail 50
    exit 1
fi

echo ""
echo "Verifying credentials are loaded..."
if docker exec automated-trading-platform-backend-aws-1 env | grep -q "EXCHANGE_CUSTOM_API_KEY"; then
    echo "✅ Credentials loaded in container"
else
    echo "❌ Credentials not found in container"
    exit 1
fi

echo ""
echo "Testing API endpoint..."
sleep 5
if curl -s http://localhost:8002/api/health/system > /dev/null; then
    echo "✅ API endpoint responding"
else
    echo "⚠️  API endpoint not responding yet (may need more time)"
fi

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "Next steps:"
echo "1. Check logs: docker compose --profile aws logs -f backend-aws"
echo "2. Test connection: docker compose --profile aws exec backend-aws python scripts/test_crypto_connection.py"
echo "3. Verify no auth errors: docker compose --profile aws logs backend-aws | grep -i '401\|auth.*fail'"
