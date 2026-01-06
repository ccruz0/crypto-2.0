#!/bin/bash
# Check Telegram /start command logs on AWS

echo "=========================================="
echo "Checking Telegram /start Logs"
echo "=========================================="
echo ""

SERVER="ubuntu@175.41.189.249"

# Check if we can connect
echo "🔍 Testing SSH connection..."
if ssh -o ConnectTimeout=5 $SERVER "echo 'Connected'" 2>/dev/null; then
    echo "✅ SSH connection successful"
    echo ""
    
    echo "📋 Fetching recent Telegram /start logs..."
    echo ""
    
    ssh $SERVER << 'ENDSSH'
cd ~/automated-trading-platform

echo "=== Last 100 lines with Telegram START/MENU/ERROR ==="
docker-compose --profile aws logs --tail=100 backend-aws 2>/dev/null | grep -i "TG.*START\|TG.*MENU\|TG.*ERROR" | tail -30

echo ""
echo "=== Recent /start command processing ==="
docker-compose --profile aws logs --tail=200 backend-aws 2>/dev/null | grep -i "\[TG\]\[CMD\]\[START\]" | tail -20

echo ""
echo "=== Main menu send attempts ==="
docker-compose --profile aws logs --tail=200 backend-aws 2>/dev/null | grep -i "\[TG\]\[MENU\]" | tail -20

echo ""
echo "=== Any errors sending menu messages ==="
docker-compose --profile aws logs --tail=200 backend-aws 2>/dev/null | grep -i "\[TG\].*ERROR.*menu\|\[TG\].*Failed.*menu" | tail -10

echo ""
echo "=== Recent Telegram API responses ==="
docker-compose --profile aws logs --tail=200 backend-aws 2>/dev/null | grep -i "Menu message sent\|Menu message API returned" | tail -10
ENDSSH

else
    echo "❌ Cannot connect to AWS server"
    echo ""
    echo "Manual steps to check logs:"
    echo "1. SSH to AWS: ssh ubuntu@175.41.189.249"
    echo "2. Run: cd ~/automated-trading-platform"
    echo "3. Check logs: docker-compose --profile aws logs --tail=200 backend-aws | grep -i 'TG.*START\|TG.*MENU'"
    echo ""
    echo "Or check all recent logs:"
    echo "   docker-compose --profile aws logs --tail=100 backend-aws"
fi

echo ""















