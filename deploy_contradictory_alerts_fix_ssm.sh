#!/bin/bash
# Desplegar fix de alertas contradictorias usando AWS Session Manager (SSM)

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Desplegando Fix de Alertas Contradictorias vía AWS Session Manager"
echo "======================================================================="
echo ""

# Verificar que AWS CLI está configurado
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI no está instalado"
    exit 1
fi

echo "🔄 Ejecutando despliegue vía SSM..."

# Copiar archivo directamente al servidor vía SSM
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform\",
    \"git pull origin main || echo 'Git pull failed'\",
    \"CONTAINER=\$(docker compose --profile aws ps -q backend 2>/dev/null || docker ps -q --filter 'name=backend')\",
    \"if [ -n \\\"\\\$CONTAINER\\\" ]; then\",
    \"  echo '📋 Copiando archivo exchange_sync.py al contenedor...'\",
    \"  docker cp backend/app/services/exchange_sync.py \\\$CONTAINER:/app/app/services/exchange_sync.py\",
    \"  echo '🔄 Reiniciando backend...'\",
    \"  docker compose --profile aws restart backend || docker restart \\\$CONTAINER\",
    \"  echo '✅ Backend reiniciado con fix de alertas contradictorias'\",
    \"  sleep 5\",
    \"  docker compose --profile aws logs --tail=30 backend 2>/dev/null || docker logs --tail=30 \\\$CONTAINER\",
    \"else\",
    \"  echo '❌ No se encontró contenedor backend'\",
    \"  exit 1\",
    \"fi\"
  ]" \
  --region "$REGION" \
  --output json | jq -r '.Command.CommandId')

if [ -z "$COMMAND_ID" ] || [ "$COMMAND_ID" == "null" ]; then
    echo "❌ Error al enviar comando SSM"
    exit 1
fi

echo "📋 Command ID: $COMMAND_ID"
echo "⏳ Esperando resultado del comando..."
echo ""

# Esperar a que el comando termine
sleep 5

# Obtener resultado del comando
aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --output json | jq -r '.StandardOutputContent, .StandardErrorContent'

echo ""
echo "✅ Despliegue completado!"







