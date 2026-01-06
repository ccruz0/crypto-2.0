#!/bin/bash
# Quick Telegram notifications status check

echo "=========================================="
echo "Telegram Notifications Status Check"
echo "=========================================="
echo ""

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose not found"
    exit 1
fi

# Check if services are running
echo "1️⃣  Checking services..."
if docker-compose ps | grep -q "backend-aws.*Up"; then
    echo "   ✅ backend-aws is running"
else
    echo "   ❌ backend-aws is NOT running"
    echo "      Run: docker-compose --profile aws up -d backend-aws"
fi

if docker-compose ps | grep -q "market-updater-aws.*Up"; then
    echo "   ✅ market-updater-aws is running"
else
    echo "   ❌ market-updater-aws is NOT running"
    echo "      Run: docker-compose --profile aws up -d market-updater-aws"
fi
echo ""

# Check environment variables
echo "2️⃣  Checking environment variables..."
if docker-compose --profile aws exec -T backend-aws env | grep -q "TELEGRAM_BOT_TOKEN="; then
    TOKEN_PRESENT=$(docker-compose --profile aws exec -T backend-aws env | grep "TELEGRAM_BOT_TOKEN=" | cut -d'=' -f2)
    if [ -n "$TOKEN_PRESENT" ]; then
        echo "   ✅ TELEGRAM_BOT_TOKEN is set"
    else
        echo "   ❌ TELEGRAM_BOT_TOKEN is empty"
    fi
else
    echo "   ❌ TELEGRAM_BOT_TOKEN is NOT set"
fi

if docker-compose --profile aws exec -T backend-aws env | grep -q "TELEGRAM_CHAT_ID="; then
    CHAT_ID=$(docker-compose --profile aws exec -T backend-aws env | grep "TELEGRAM_CHAT_ID=" | cut -d'=' -f2)
    if [ -n "$CHAT_ID" ]; then
        echo "   ✅ TELEGRAM_CHAT_ID is set: $CHAT_ID"
    else
        echo "   ❌ TELEGRAM_CHAT_ID is empty"
    fi
else
    echo "   ❌ TELEGRAM_CHAT_ID is NOT set"
fi

RUNTIME_ORIGIN=$(docker-compose --profile aws exec -T backend-aws env | grep "RUNTIME_ORIGIN=" | cut -d'=' -f2)
if [ "$RUNTIME_ORIGIN" = "AWS" ]; then
    echo "   ✅ RUNTIME_ORIGIN=AWS"
else
    echo "   ❌ RUNTIME_ORIGIN=$RUNTIME_ORIGIN (should be AWS)"
fi

RUN_TELEGRAM=$(docker-compose --profile aws exec -T backend-aws env | grep "RUN_TELEGRAM=" | cut -d'=' -f2)
if [ "$RUN_TELEGRAM" = "true" ]; then
    echo "   ✅ RUN_TELEGRAM=true"
else
    echo "   ❌ RUN_TELEGRAM=$RUN_TELEGRAM (should be true)"
fi
echo ""

# Check recent logs
echo "3️⃣  Checking recent Telegram logs (last 20 lines)..."
echo "   Backend logs:"
docker-compose --profile aws logs --tail=20 backend-aws 2>/dev/null | grep -i "telegram" | tail -5 || echo "   (no Telegram logs found)"
echo ""
echo "   Market updater logs:"
docker-compose --profile aws logs --tail=20 market-updater-aws 2>/dev/null | grep -i "telegram" | tail -5 || echo "   (no Telegram logs found)"
echo ""

# Summary
echo "=========================================="
echo "Summary"
echo "=========================================="
echo ""
echo "To run full diagnostic:"
echo "  docker-compose --profile aws exec backend-aws python backend/scripts/diagnose_telegram_alerts.py"
echo ""
echo "To test sending a message:"
echo "  docker-compose --profile aws exec backend-aws python -c \""
echo "    from app.services.telegram_notifier import telegram_notifier;"
echo "    from app.core.runtime import get_runtime_origin;"
echo "    result = telegram_notifier.send_message('🧪 Test', origin=get_runtime_origin());"
echo "    print('✅ Sent' if result else '❌ Failed')\""
echo ""















