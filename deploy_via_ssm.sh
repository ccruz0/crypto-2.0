#!/bin/bash
# Deploy to production via AWS SSM (atp-rebuild-2026).
#
# Modes:
#   fast  - Deploy rápido (sin rebuild): git pull, reinicia backend-aws y nginx (~2 min)
#   full  - Deploy completo (con rebuild): reconstruye imagen backend-aws, levanta stack,
#           health check, reinicia nginx (~5 min). Por defecto.
#
# Usage:
#   ./deploy_via_ssm.sh fast
#   ./deploy_via_ssm.sh
#   ./deploy_via_ssm.sh full
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"
MODE="${1:-full}"

# Help
if [ "$MODE" = "-h" ] || [ "$MODE" = "--help" ]; then
    echo "Deploy via SSM (production)"
    echo ""
    echo "  ./deploy_via_ssm.sh fast   → Deploy rápido (sin rebuild), ~2 min"
    echo "  ./deploy_via_ssm.sh        → Deploy completo (con rebuild), ~5 min"
    echo "  ./deploy_via_ssm.sh full   → Igual que sin argumentos"
    exit 0
fi

echo "🚀 Deploying via AWS Session Manager (SSM)"
echo "==========================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

if [ "$MODE" = "fast" ]; then
    echo "📤 Sending FAST deployment command (git pull + restart backend)..."
    COMMAND_ID=$(aws ssm send-command \
        --instance-ids $INSTANCE_ID \
        --document-name "AWS-RunShellScript" \
        --parameters 'commands=["set -e","cd /home/ubuntu/automated-trading-platform 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1","git config --global --add safe.directory '*' 2>/dev/null || true","git pull origin main || true","docker compose --profile aws ps","docker compose --profile aws restart backend-aws || docker compose --profile aws up -d","sleep 20","curl -sf --connect-timeout 5 http://127.0.0.1:8002/ping_fast && echo Backend OK || echo Backend not ready","sudo systemctl restart nginx 2>/dev/null || true","docker compose --profile aws ps"]' \
        --region $REGION \
        --timeout-seconds 300 \
        --output text \
        --query 'Command.CommandId' 2>&1)
    WAIT_SECONDS=120
else
    echo "📤 Sending FULL deployment command (git pull + full backend rebuild)..."
    # Full deploy: pull, rebuild backend image, up, health check, nginx restart
    COMMAND_ID=$(aws ssm send-command \
        --instance-ids $INSTANCE_ID \
        --document-name "AWS-RunShellScript" \
        --parameters 'commands=["set -e","cd /home/ubuntu/automated-trading-platform 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1","git config --global --add safe.directory '*' 2>/dev/null || true","git pull origin main || true","docker compose --profile aws build --no-cache backend-aws","docker compose --profile aws up -d","sleep 25","curl -sf --connect-timeout 5 http://127.0.0.1:8002/ping_fast && echo Backend OK || echo Backend not ready","sudo systemctl restart nginx 2>/dev/null || true","docker compose --profile aws ps"]' \
        --region $REGION \
        --timeout-seconds 600 \
        --output text \
        --query 'Command.CommandId' 2>&1)
    WAIT_SECONDS=300
fi

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting ${WAIT_SECONDS}s for command to finish..."
sleep "$WAIT_SECONDS"

echo ""
echo "📊 Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1 | head -80

echo ""
echo "🎉 Deploy command finished. Dashboard: https://dashboard.hilovivo.com"
