#!/bin/bash
# Direct update script - run this on your local machine with SSH access to AWS

set -e

. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

EC2_HOST="47.130.143.159"
EC2_USER="ubuntu"

echo "🚀 Updating Telegram Menu on AWS"
echo "=================================="
echo "Host: $EC2_HOST"
echo ""

echo "📥 Step 1: Pulling latest code..."
ssh_cmd "$EC2_USER@$EC2_HOST" "cd ~/crypto-2.0 && git stash && rm -f update_telegram_menu.sh update_telegram_menu_aws.sh update_telegram_menu_aws_ssm.sh && git pull origin main"

echo ""
echo "🛑 Step 2: Stopping backend-aws container..."
ssh_cmd "$EC2_USER@$EC2_HOST" "cd ~/crypto-2.0 && docker compose --profile aws stop backend-aws"

echo ""
echo "🔧 Step 3: Rebuilding backend-aws image..."
ssh_cmd "$EC2_USER@$EC2_HOST" "cd ~/crypto-2.0 && docker compose --profile aws build backend-aws"

echo ""
echo "🔄 Step 4: Starting backend-aws container..."
ssh_cmd "$EC2_USER@$EC2_HOST" "cd ~/crypto-2.0 && docker compose --profile aws up -d backend-aws"

echo ""
echo "⏳ Step 5: Waiting for container to be ready..."
sleep 15

echo ""
echo "✅ Step 6: Verifying code update..."
ssh_cmd "$EC2_USER@$EC2_HOST" "cd ~/crypto-2.0 && docker compose --profile aws exec backend-aws grep -A 5 'if text.startswith(\"/start\"):' /app/app/services/telegram_commands.py"

echo ""
echo "✅ Update complete!"
echo ""
echo "Prueba ahora enviando /start en Telegram. Deberías ver:"
echo "- Un solo mensaje con el menú principal"
echo "- Botones inline (Portfolio, Watchlist, Open Orders, etc.)"
echo "- Sin mensaje de bienvenida duplicado"

