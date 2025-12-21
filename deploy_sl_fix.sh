#!/bin/bash
# Script to deploy SL display fix to AWS
set -e

# Use the same server as restart_backend_aws.sh
EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Desplegando fix de visualización de SL a AWS..."
echo ""

# Sync backend files (only the modified file)
echo "📦 Sincronizando archivos del backend..."
rsync_cmd \
  --exclude='venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.env' \
  backend/app/api/routes_orders.py \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/api/

echo ""
echo "📦 Sincronizando archivos del frontend..."
rsync_cmd \
  --exclude='node_modules/' \
  --exclude='.next/' \
  --exclude='*.log' \
  frontend/src/lib/api.ts \
  frontend/src/app/page.tsx \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/frontend/src/lib/ \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/frontend/src/app/

echo ""
echo "🔄 Reiniciando backend en AWS..."
ssh_cmd "$EC2_USER@$EC2_HOST" << 'RESTART_SCRIPT'
cd ~/automated-trading-platform

# Check if using Docker Compose
if docker compose --profile aws ps backend 2>/dev/null | grep -q "Up"; then
    echo "🔄 Reiniciando contenedor backend..."
    docker compose --profile aws restart backend
    echo "✅ Contenedor backend reiniciado"
    
    # Wait a bit and check status
    sleep 5
    echo ""
    echo "📊 Estado del backend:"
    docker compose --profile aws ps backend
    
    echo ""
    echo "📋 Logs recientes:"
    docker compose --profile aws logs --tail=30 backend
elif pgrep -f "uvicorn app.main:app" > /dev/null; then
    echo "🔄 Reiniciando proceso uvicorn..."
    pkill -f "uvicorn app.main:app"
    sleep 2
    
    cd ~/automated-trading-platform/backend
    source venv/bin/activate 2>/dev/null || true
    nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
    
    sleep 3
    echo "✅ Backend reiniciado"
    echo ""
    echo "📋 Logs recientes:"
    tail -30 backend.log
else
    echo "⚠️  No se encontró proceso backend en ejecución"
    echo "Contenedores Docker disponibles:"
    docker compose --profile aws ps 2>/dev/null || docker ps
fi

echo ""
echo "🧪 Verificando salud del backend..."
sleep 3
if curl -f --connect-timeout 5 http://localhost:8002/health >/dev/null 2>&1 || curl -f --connect-timeout 5 http://localhost:8000/api/health >/dev/null 2>&1; then
    echo "✅ Backend está saludable y respondiendo"
else
    echo "⚠️  Verificación de salud falló - puede necesitar más tiempo para iniciar"
fi
RESTART_SCRIPT

echo ""
echo "✅ Despliegue completo!"
echo ""
echo "📝 Próximos pasos:"
echo "1. Recarga el frontend en el navegador (F5 o Cmd+R)"
echo "2. Verifica que los valores de SL aparezcan en la tabla de Holdings"
echo "3. Revisa la sección 'Protection Status' en la parte inferior"







