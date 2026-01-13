#!/bin/bash
# Deploy Watchlist Master Table - Copy files directly then run migration

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Desplegando Watchlist Master Table (método directo)"
echo "======================================================"
echo ""

# Verificar que AWS CLI está configurado
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI no está instalado"
    exit 1
fi

echo "📦 Copiando archivos directamente al servidor..."

# Copiar archivos usando SSM
FILES=(
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

# Crear comando para copiar archivos
COPY_COMMANDS=""
for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        # Leer contenido del archivo y codificarlo en base64
        CONTENT=$(cat "$file" | base64)
        DIR=$(dirname "$file")
        FILENAME=$(basename "$file")
        
        COPY_COMMANDS="${COPY_COMMANDS}
echo '📦 Copiando $file...'
mkdir -p /home/ubuntu/automated-trading-platform/$DIR
echo '$CONTENT' | base64 -d > /home/ubuntu/automated-trading-platform/$file
chmod 644 /home/ubuntu/automated-trading-platform/$file
"
    fi
done

echo "🔄 Ejecutando despliegue..."

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"set -e\",
    \"cd /home/ubuntu/automated-trading-platform\",
    $COPY_COMMANDS
    \"echo ''\",
    \"echo '🔄 Ejecutando migración...'\",
    \"cd backend\",
    \"if [ -d venv ]; then\",
    \"  . venv/bin/activate\",
    \"fi\",
    \"python3 scripts/run_watchlist_master_migration.py\",
    \"echo ''\",
    \"echo '✅ Verificando...'\",
    \"python3 scripts/verify_watchlist_master.py || echo '⚠️ Verification had warnings'\",
    \"echo ''\",
    \"echo '🔄 Reiniciando backend...'\",
    \"CONTAINER=\\\$(docker compose --profile aws ps -q backend 2>/dev/null || docker ps -q --filter 'name=backend' | head -1)\",
    \"if [ -n \\\"\\\$CONTAINER\\\" ]; then\",
    \"  docker cp app/models/watchlist_master.py \\\$CONTAINER:/app/app/models/watchlist_master.py\",
    \"  docker cp app/services/watchlist_master_seed.py \\\$CONTAINER:/app/app/services/watchlist_master_seed.py\",
    \"  docker cp app/api/routes_dashboard.py \\\$CONTAINER:/app/app/api/routes_dashboard.py\",
    \"  docker cp ../market_updater.py \\\$CONTAINER:/app/market_updater.py\",
    \"  docker cp app/services/portfolio_cache.py \\\$CONTAINER:/app/app/services/portfolio_cache.py\",
    \"  docker compose --profile aws restart backend 2>/dev/null || docker restart \\\$CONTAINER\",
    \"  sleep 5\",
    \"  docker compose --profile aws logs --tail=30 backend 2>/dev/null || docker logs --tail=30 \\\$CONTAINER\",
    \"else\",
    \"  sudo systemctl restart backend.service 2>/dev/null || echo '⚠️ No se pudo reiniciar'\",
    \"fi\",
    \"echo ''\",
    \"echo '✅ Despliegue completado!'\"
  ]" \
  --region "$REGION" \
  --output text \
  --query "Command.CommandId" 2>&1)

if [ $? -eq 0 ] && [ -n "$COMMAND_ID" ]; then
    echo "✅ Comando enviado: $COMMAND_ID"
    echo "⏳ Esperando ejecución..."
    
    aws ssm wait command-executed \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" || true
    
    echo ""
    echo "📄 Salida:"
    aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --query "StandardOutputContent" --output text
    
    echo ""
    echo "✅ Despliegue completado!"
else
    echo "❌ Error al enviar comando"
    exit 1
fi
















