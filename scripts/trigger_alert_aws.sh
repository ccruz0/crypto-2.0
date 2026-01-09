#!/bin/bash
# Script to trigger a manual alert on AWS and monitor decision tracing

SYMBOL=${1:-"ALGO_USDT"}
SIDE=${2:-"BUY"}

echo "🚀 Triggering manual alert for $SYMBOL $SIDE on AWS..."
echo ""

# SSH to AWS and run the script
cd "$(dirname "$0")/.."
. ./scripts/ssh_key.sh

ssh_cmd ubuntu@47.130.143.159 "cd ~/automated-trading-platform && docker compose --profile aws exec -T market-updater-aws python3 /app/scripts/trigger_manual_alert.py $SYMBOL $SIDE"

