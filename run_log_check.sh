#!/bin/bash
# Run this script when you can SSH to AWS

echo "=========================================="
echo "Telegram /start Log Analysis"
echo "=========================================="
echo ""

SERVER="ubuntu@175.41.189.249"

echo "📋 Checking recent /start command activity..."
echo ""
ssh $SERVER << 'ENDSSH'
cd ~/automated-trading-platform

echo "=== Last 30 /start related logs ==="
docker-compose --profile aws logs --tail=200 backend-aws 2>/dev/null | grep -i "TG.*START" | tail -30

echo ""
echo "=== Main menu sending attempts ==="
docker-compose --profile aws logs --tail=200 backend-aws 2>/dev/null | grep -i "TG.*MENU" | tail -20

echo ""
echo "=== Any errors ==="
docker-compose --profile aws logs --tail=200 backend-aws 2>/dev/null | grep -i "TG.*ERROR" | tail -15

echo ""
echo "=== Recent Telegram API responses ==="
docker-compose --profile aws logs --tail=200 backend-aws 2>/dev/null | grep -i "Menu message sent\|Menu message API returned\|Welcome message" | tail -15

echo ""
echo "=== Full /start command sequence (last occurrence) ==="
docker-compose --profile aws logs --tail=500 backend-aws 2>/dev/null | grep -A 15 "Processing /start command" | tail -20
ENDSSH

echo ""
echo "✅ Log check complete"
echo ""
echo "If you see errors, check CHECK_TELEGRAM_START_LOGS.md for troubleshooting"















