#!/bin/bash
# Deploy Telegram /start command fix to AWS

set -e

echo "=========================================="
echo "Deploying Telegram /start Fix"
echo "=========================================="
echo ""

# Check if we're deploying to AWS or local
if [ "$1" == "local" ]; then
    echo "📦 Deploying to LOCAL environment..."
    echo ""
    echo "🔄 Restarting backend service..."
    docker-compose --profile local restart backend
    echo ""
    echo "✅ Local deployment complete!"
    echo ""
    echo "Test by sending /start to your bot"
    exit 0
fi

# AWS deployment
echo "📦 Deploying to AWS environment..."
echo ""

# Check if file exists
if [ ! -f "backend/app/services/telegram_commands.py" ]; then
    echo "❌ Error: backend/app/services/telegram_commands.py not found"
    exit 1
fi

# Check if we have SSH access configured
if [ -f "scripts/ssh_key.sh" ]; then
    source scripts/ssh_key.sh
    SERVER="ubuntu@175.41.189.249"
    
    echo "🔑 Using SSH key: ${SSH_KEY:-$HOME/.ssh/id_rsa}"
    echo ""
    
    echo "📤 Step 1: Syncing telegram_commands.py to AWS..."
    rsync_cmd \
      --include='app/services/telegram_commands.py' \
      --exclude='*' \
      ./backend/app/services/telegram_commands.py \
      $SERVER:~/automated-trading-platform/backend/app/services/telegram_commands.py
    
    echo ""
    echo "🔄 Step 2: Restarting backend-aws service..."
    ssh_cmd $SERVER << 'ENDSSH'
cd ~/automated-trading-platform

# Restart backend-aws using docker compose
if command -v docker-compose &> /dev/null; then
    echo "🔄 Restarting backend-aws container..."
    docker-compose --profile aws restart backend-aws
    echo "✅ Backend-aws restarted"
elif docker compose version &> /dev/null; then
    echo "🔄 Restarting backend-aws container..."
    docker compose --profile aws restart backend-aws
    echo "✅ Backend-aws restarted"
else
    echo "⚠️  Docker Compose not found"
    exit 1
fi

# Wait a moment for container to start
sleep 3

# Check if container is running
if docker compose --profile aws ps 2>/dev/null | grep -q "backend-aws.*Up" || docker-compose --profile aws ps 2>/dev/null | grep -q "backend-aws.*Up"; then
    echo "✅ Container is running"
else
    echo "⚠️  Container may not be running - check logs"
fi
ENDSSH

    echo ""
    echo "✅ Deployment complete!"
    echo ""
    echo "📱 Next steps:"
    echo "   1. Test /start command in Telegram"
    echo "   2. Check logs: ssh $SERVER 'cd ~/automated-trading-platform && docker-compose --profile aws logs -f backend-aws | grep -i TG.*START'"
    echo "   3. You should see both welcome message and main menu"
    
else
    # Fallback: use docker compose directly if on AWS or have direct access
    echo "⚠️  SSH scripts not found, trying direct docker-compose..."
    echo ""
    
    if command -v docker-compose &> /dev/null || docker compose version &> /dev/null; then
        echo "🔄 Restarting backend-aws service..."
        if command -v docker-compose &> /dev/null; then
            docker-compose --profile aws restart backend-aws
        else
            docker compose --profile aws restart backend-aws
        fi
        
        echo ""
        echo "✅ Deployment complete!"
        echo ""
        echo "📱 Test /start command in Telegram"
    else
        echo "❌ Error: Cannot deploy - no SSH access or docker-compose available"
        echo ""
        echo "Manual deployment steps:"
        echo "1. Copy backend/app/services/telegram_commands.py to AWS server"
        echo "2. SSH to AWS: ssh ubuntu@175.41.189.249"
        echo "3. Restart: cd ~/automated-trading-platform && docker-compose --profile aws restart backend-aws"
        exit 1
    fi
fi

echo ""










