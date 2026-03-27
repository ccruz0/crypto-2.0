#!/bin/bash
# Desplegar usando AWS Session Manager (SSM)

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Desplegando Fix vía AWS Session Manager"
echo "========================================="
echo ""

# Verificar que AWS CLI está configurado
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI no está instalado"
    exit 1
fi

echo "📦 Sincronizando archivos al servidor..."

# Primero, hacer commit y push de los cambios
echo "📝 Haciendo commit de los cambios..."
git add backend/app/api/routes_dashboard.py backend/app/services/signal_monitor.py
git commit -m "Fix: Auto-habilitar alert_enabled y usar strategy.decision en signal_monitor" || echo "⚠️ No hay cambios nuevos para commit"

# Push a main para activar despliegue automático
echo "📤 Haciendo push a main..."
git push origin main || echo "⚠️ Push falló o no hay cambios"

echo ""
echo "🔄 Ejecutando despliegue vía SSM..."

# Copiar archivos directamente al servidor vía SSM
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd ~/automated-trading-platform || cd /home/ubuntu/crypto-2.0\",
    \"git pull origin main || echo 'Git pull failed'\",
    \"CONTAINER=\$(docker compose --profile aws ps -q backend 2>/dev/null || docker ps -q --filter 'name=backend')\",
    \"if [ -n \\\"\\\$CONTAINER\\\" ]; then\",
    \"  echo '📋 Copiando archivos al contenedor...'\",
    \"  docker cp backend/app/api/routes_dashboard.py \\\$CONTAINER:/app/app/api/routes_dashboard.py\",
    \"  docker cp backend/app/services/signal_monitor.py \\\$CONTAINER:/app/app/services/signal_monitor.py\",
    \"  echo '🔄 Reiniciando backend...'\",
    \"  docker compose --profile aws restart backend || docker restart \\\$CONTAINER\",
    \"  echo '✅ Backend reiniciado'\",
    \"  sleep 5\",
    \"  docker compose --profile aws logs --tail=20 backend 2>/dev/null || docker logs --tail=20 \\\$CONTAINER\",
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















