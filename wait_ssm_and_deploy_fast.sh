#!/bin/bash
# Espera a que la instancia esté Online en SSM (Fleet Manager), luego lanza deploy rápido.
# Comprueba cada 2 minutos. Cuando SSM reporta PingStatus=Online, ejecuta ./deploy_via_ssm.sh fast.
#
# Uso: ./wait_ssm_and_deploy_fast.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"
INTERVAL=120

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "⏳ Waiting for instance $INSTANCE_ID to be Online in SSM (check every ${INTERVAL}s)..."
echo ""

while true; do
    status=$(aws ssm describe-instance-information \
        --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
        --region "$REGION" \
        --query 'InstanceInformationList[0].PingStatus' \
        --output text 2>/dev/null || echo "None")

    echo "$(date '+%H:%M:%S') SSM PingStatus: $status"

    if [ "$status" = "Online" ]; then
        echo ""
        echo "✅ Instance is Online in SSM. Running fast deploy..."
        exec ./deploy_via_ssm.sh fast
    fi

    echo "   Next check in ${INTERVAL}s..."
    sleep "$INTERVAL"
done
