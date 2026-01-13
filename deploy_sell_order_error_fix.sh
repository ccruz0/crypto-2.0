#!/bin/bash
# Desplegar Fix de Error Handling para SELL/BUY Orders

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Desplegando Fix de Error Handling para SELL/BUY Orders"
echo "========================================="
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
    \"  echo '📋 Copiando archivos al contenedor...'\",
    \"  docker cp backend/app/services/signal_monitor.py \\\$CONTAINER:/app/app/services/signal_monitor.py\",
    \"  echo '🔄 Reiniciando backend...'\",
    \"  docker compose --profile aws restart backend || docker restart \\\$CONTAINER\",
    \"  echo '✅ Backend reiniciado'\",
    \"  sleep 5\",
    \"  docker compose --profile aws logs --tail=30 backend 2>/dev/null || docker logs --tail=30 \\\$CONTAINER | grep -i 'error\\|started\\|restart' | tail -10\",
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
else
    echo "❌ Error al enviar comando SSM"
    echo "💡 Asegúrate de que:"
    echo "   1. AWS CLI está configurado con credenciales válidas"
    echo "   2. Tienes permisos para usar SSM"
    echo "   3. La instancia EC2 tiene SSM Agent instalado"
fi







