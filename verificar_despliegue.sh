#!/bin/bash
# Verificar que el despliegue se aplicó correctamente

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🔍 Verificando que el fix está aplicado..."
echo ""

# Verificar que los cambios están en el servidor
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd ~/automated-trading-platform\",
    \"CONTAINER=\$(docker compose --profile aws ps -q backend 2>/dev/null)\",
    \"if [ -n \\\"\\\$CONTAINER\\\" ]; then\",
    \"  echo '🔍 Verificando cambios en signal_monitor.py...'\",
    \"  docker exec \\\$CONTAINER grep -A 3 'strategy.decision' /app/app/services/signal_monitor.py | head -5 || echo 'No encontrado'\",
    \"  echo ''\",
    \"  echo '🔍 Verificando cambios en routes_dashboard.py...'\",
    \"  docker exec \\\$CONTAINER grep -A 3 'alert_enabled.*True' /app/app/api/routes_dashboard.py | head -5 || echo 'No encontrado'\",
    \"  echo ''\",
    \"  echo '📊 Estado del backend:'\",
    \"  docker compose --profile aws ps backend 2>/dev/null || docker ps --filter 'name=backend'\",
    \"else\",
    \"  echo '❌ No se encontró contenedor'\",
    \"fi\"
  ]" \
  --region "$REGION" \
  --output text \
  --query "Command.CommandId" 2>&1)

if [ $? -eq 0 ] && [ -n "$COMMAND_ID" ]; then
    echo "⏳ Esperando verificación..."
    aws ssm wait command-executed \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" || true
    
    echo ""
    echo "📄 Resultado:"
    aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --query "StandardOutputContent" --output text
fi















