#!/bin/bash
# Deploy Swing Conservative strategy update to AWS

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Desplegando Swing Conservative Update vía AWS Session Manager"
echo "=============================================================="
echo ""

# Verificar que AWS CLI está configurado
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI no está instalado"
    exit 1
fi

echo "🔄 Ejecutando despliegue vía SSM..."

# Copiar archivos directamente al servidor vía SSM
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform\",
    \"git pull origin main || echo 'Git pull failed'\",
    \"CONTAINER=\$(docker compose --profile aws ps -q backend 2>/dev/null || docker ps -q --filter 'name=backend')\",
    \"if [ -n \\\"\\\$CONTAINER\\\" ]; then\",
    \"  echo '📋 Copiando archivos Swing Conservative update al contenedor...'\",
    \"  docker cp backend/trading_config.json \\\$CONTAINER:/app/trading_config.json\",
    \"  docker cp backend/app/services/config_loader.py \\\$CONTAINER:/app/app/services/config_loader.py\",
    \"  docker cp backend/app/services/trading_signals.py \\\$CONTAINER:/app/app/services/trading_signals.py\",
    \"  docker cp backend/tests/test_swing_conservative_gating.py \\\$CONTAINER:/app/tests/test_swing_conservative_gating.py 2>/dev/null || echo 'Test file copy skipped'\",
    \"  echo '🔄 Reiniciando backend para aplicar cambios...'\",
    \"  docker compose --profile aws restart backend || docker restart \\\$CONTAINER\",
    \"  echo '✅ Backend reiniciado'\",
    \"  sleep 5\",
    \"  echo '📊 Últimas líneas del log:'\",
    \"  docker compose --profile aws logs --tail=30 backend 2>/dev/null || docker logs --tail=30 \\\$CONTAINER\",
    \"else\",
    \"  echo '❌ No se encontró contenedor backend'\",
    \"  docker compose --profile aws ps 2>/dev/null || docker ps\",
    \"fi\"
  ]" \
  --region "$REGION" \
  --output text \
  --query "Command.CommandId" 2>&1)

if [ $? -eq 0 ] && [ -n "$COMMAND_ID" ]; then
    echo "✅ Comando enviado: $COMMAND_ID"
    echo "⏳ Esperando ejecución..."
    
    # Esperar a que termine
    aws ssm wait command-executed \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" || true
    
    echo ""
    echo "📄 Salida del comando:"
    aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --query "StandardOutputContent" --output text || echo "No se pudo obtener salida"
    
    echo ""
    echo "✅ Despliegue completado!"
    echo ""
    echo "📝 Verificación recomendada:"
    echo "   - Verificar logs del backend para confirmar migración"
    echo "   - Probar señal de compra con Swing Conservative"
    echo "   - Verificar que los nuevos filtros están activos"
else
    echo "❌ Error al enviar comando SSM"
fi
