#!/bin/bash
# Deploy canonical throttle logic fix

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Desplegando Canonical Throttle Logic Fix"
echo "=========================================="

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform\",
    \"git pull origin main || echo 'Git pull failed, continuing...'\",
    \"CONTAINER=\$(docker compose --profile aws ps -q backend 2>/dev/null || docker ps -q --filter 'name=backend')\",
    \"if [ -n \\\"\\\$CONTAINER\\\" ]; then\",
    \"  echo '📋 Copiando archivos al contenedor...'\",
    \"  docker cp backend/app/services/signal_throttle.py \\\$CONTAINER:/app/app/services/signal_throttle.py\",
    \"  docker cp backend/app/services/signal_monitor.py \\\$CONTAINER:/app/app/services/signal_monitor.py\",
    \"  echo '🔄 Reiniciando backend...'\",
    \"  docker compose --profile aws restart backend || docker restart \\\$CONTAINER\",
    \"  echo '✅ Backend reiniciado'\",
    \"  sleep 5\",
    \"  docker compose --profile aws logs --tail=30 backend 2>/dev/null || docker logs --tail=30 \\\$CONTAINER\",
    \"else\",
    \"  echo '❌ No se encontró contenedor backend'\",
    \"fi\"
  ]" \
  --region "$REGION" \
  --output text \
  --query "Command.CommandId")

echo "✅ Comando enviado: $COMMAND_ID"
echo "⏳ Esperando ejecución..."

sleep 10

aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "[Status, StandardOutputContent]" \
  --output text

echo ""
echo "✅ Despliegue completado!"
