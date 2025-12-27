#!/bin/bash
# Deploy Watchlist Master Table via AWS Session Manager (SSM)

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Desplegando Watchlist Master Table vía AWS Session Manager"
echo "=============================================================="
echo ""

# Verificar que AWS CLI está configurado
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI no está instalado"
    exit 1
fi

echo "📦 Preparando archivos para despliegue..."

# Lista de archivos a desplegar
FILES_TO_DEPLOY=(
    "backend/app/models/watchlist_master.py"
    "backend/app/services/watchlist_master_seed.py"
    "backend/app/api/routes_dashboard.py"
    "backend/market_updater.py"
    "backend/app/services/portfolio_cache.py"
    "backend/scripts/run_watchlist_master_migration.py"
    "backend/scripts/verify_watchlist_master.py"
    "frontend/src/components/WatchlistCell.tsx"
    "frontend/src/styles/watchlist.css"
    "frontend/src/app/api.ts"
)

# Verificar que los archivos existen
MISSING_FILES=()
for file in "${FILES_TO_DEPLOY[@]}"; do
    if [ ! -f "$file" ]; then
        MISSING_FILES+=("$file")
    fi
done

if [ ${#MISSING_FILES[@]} -gt 0 ]; then
    echo "⚠️  Archivos faltantes:"
    for file in "${MISSING_FILES[@]}"; do
        echo "   - $file"
    done
    echo ""
    read -p "¿Continuar de todos modos? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "🔄 Ejecutando despliegue vía SSM..."

# Comando para desplegar
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"set -e\",
    \"cd /home/ubuntu/automated-trading-platform || cd ~/automated-trading-platform || exit 1\",
    \"echo '📦 Actualizando código desde git...'\",
    \"git config --global --add safe.directory /home/ubuntu/automated-trading-platform 2>/dev/null || true\",
    \"git pull origin main || echo '⚠️ Git pull failed, continuando...'\",
    \"echo ''\",
    \"echo '🔄 Ejecutando migración de base de datos...'\",
    \"cd backend\",
    \"if [ -d venv ]; then\",
    \"  . venv/bin/activate\",
    \"else\",
    \"  echo '⚠️ Virtual environment no encontrado'\",
    \"fi\",
    \"python3 scripts/run_watchlist_master_migration.py || echo '⚠️ Migration failed, continuando...'\",
    \"echo ''\",
    \"echo '✅ Verificando migración...'\",
    \"python3 scripts/verify_watchlist_master.py || echo '⚠️ Verification failed'\",
    \"echo ''\",
    \"echo '🔄 Reiniciando servicios...'\",
    \"CONTAINER=\$(docker compose --profile aws ps -q backend 2>/dev/null || docker ps -q --filter 'name=backend' | head -1)\",
    \"if [ -n \\\"\\\$CONTAINER\\\" ]; then\",
    \"  echo '📋 Copiando archivos al contenedor backend...'\",
    \"  docker cp app/models/watchlist_master.py \\\$CONTAINER:/app/app/models/watchlist_master.py 2>/dev/null || echo '⚠️ watchlist_master.py copy failed'\",
    \"  docker cp app/services/watchlist_master_seed.py \\\$CONTAINER:/app/app/services/watchlist_master_seed.py 2>/dev/null || echo '⚠️ watchlist_master_seed.py copy failed'\",
    \"  docker cp app/api/routes_dashboard.py \\\$CONTAINER:/app/app/api/routes_dashboard.py 2>/dev/null || echo '⚠️ routes_dashboard.py copy failed'\",
    \"  docker cp ../market_updater.py \\\$CONTAINER:/app/market_updater.py 2>/dev/null || echo '⚠️ market_updater.py copy failed'\",
    \"  docker cp app/services/portfolio_cache.py \\\$CONTAINER:/app/app/services/portfolio_cache.py 2>/dev/null || echo '⚠️ portfolio_cache.py copy failed'\",
    \"  echo '🔄 Reiniciando backend...'\",
    \"  docker compose --profile aws restart backend 2>/dev/null || docker restart \\\$CONTAINER\",
    \"  echo '✅ Backend reiniciado'\",
    \"  sleep 5\",
    \"  echo '📄 Últimas líneas del log:'\",
    \"  docker compose --profile aws logs --tail=20 backend 2>/dev/null || docker logs --tail=20 \\\$CONTAINER\",
    \"else\",
    \"  echo '⚠️ No se encontró contenedor backend, intentando reiniciar servicio systemd...'\",
    \"  sudo systemctl restart backend.service 2>/dev/null || sudo systemctl restart automated-trading-platform.service 2>/dev/null || echo '⚠️ No se pudo reiniciar servicio'\",
    \"fi\",
    \"echo ''\",
    \"echo '📦 Actualizando frontend...'\",
    \"cd ../frontend\",
    \"if [ -f package.json ]; then\",
    \"  npm install --silent 2>/dev/null || yarn install --silent 2>/dev/null || echo '⚠️ Frontend install failed'\",
    \"  npm run build 2>/dev/null || yarn build 2>/dev/null || echo '⚠️ Frontend build failed'\",
    \"  echo '✅ Frontend actualizado'\",
    \"else\",
    \"  echo '⚠️ Frontend package.json no encontrado'\",
    \"fi\",
    \"echo ''\",
    \"echo '✅ Despliegue completado!'\",
    \"echo ''\",
    \"echo '📋 Próximos pasos:'\",
    \"echo '1. Verificar logs: docker compose --profile aws logs backend'\",
    \"echo '2. Probar API: curl http://localhost:8000/api/dashboard | jq'\",
    \"echo '3. Verificar frontend en el navegador'\"
  ]" \
  --region "$REGION" \
  --output text \
  --query "Command.CommandId" 2>&1)

if [ $? -eq 0 ] && [ -n "$COMMAND_ID" ]; then
    echo "✅ Comando enviado: $COMMAND_ID"
    echo "⏳ Esperando ejecución (esto puede tomar 1-2 minutos)..."
    
    # Esperar a que termine
    aws ssm wait command-executed \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" || true
    
    echo ""
    echo "📄 Salida del comando:"
    echo "======================"
    aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --query "StandardOutputContent" --output text || echo "No se pudo obtener salida"
    
    echo ""
    echo "📄 Errores (si hay):"
    echo "==================="
    aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --query "StandardErrorContent" --output text || echo "No hay errores"
    
    echo ""
    echo "✅ Despliegue completado!"
    echo ""
    echo "🧪 Para verificar:"
    echo "   ssh ubuntu@175.41.189.249 'cd ~/automated-trading-platform/backend && python3 scripts/test_watchlist_master_endpoints.py'"
else
    echo "❌ Error al enviar comando SSM"
    echo "💡 Asegúrate de que:"
    echo "   1. AWS CLI está configurado con credenciales válidas"
    echo "   2. Tienes permisos para usar SSM"
    echo "   3. La instancia EC2 tiene SSM Agent instalado"
    exit 1
fi

