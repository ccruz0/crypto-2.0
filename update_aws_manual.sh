#!/bin/bash
# Manual update script - copy and paste these commands on AWS server

echo "=========================================="
echo "Manual Update Commands for AWS"
echo "=========================================="
echo ""
echo "Copy and paste these commands on the AWS server:"
echo ""
echo "cd ~/automated-trading-platform"
echo "git pull origin main"
echo "docker compose --profile aws stop backend-aws"
echo "docker compose --profile aws build backend-aws"
echo "docker compose --profile aws up -d backend-aws"
echo "sleep 15"
echo "docker compose --profile aws exec backend-aws grep -A 5 \"if text.startswith(\\\"/start\\\"):\" /app/app/services/telegram_commands.py"
echo ""
echo "=========================================="
echo "Or run this single command:"
echo "=========================================="
echo ""
echo "cd ~/automated-trading-platform && git pull origin main && docker compose --profile aws stop backend-aws && docker compose --profile aws build backend-aws && docker compose --profile aws up -d backend-aws && sleep 15 && docker compose --profile aws exec backend-aws grep -A 5 \"if text.startswith(\\\"/start\\\"):\" /app/app/services/telegram_commands.py"

