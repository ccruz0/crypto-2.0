#!/bin/bash
# Script para sincronizar el fix y reiniciar el backend en AWS

set -e

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🔄 Sincronizando fix y reiniciando backend en AWS..."
echo ""

# Sincronizar solo los archivos modificados
echo "📦 Sincronizando archivos modificados..."
rsync_cmd \
  backend/app/api/routes_dashboard.py \
  backend/app/services/signal_monitor.py \
  "$EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/"

echo ""
echo "🔄 Reiniciando backend..."

ssh_cmd "$EC2_USER@$EC2_HOST" << 'RESTART_SCRIPT'
cd ~/automated-trading-platform

# Check if using Docker Compose
if docker compose --profile aws ps backend 2>/dev/null | grep -q "Up"; then
    echo "🔄 Reiniciando contenedor backend..."
    
    # Copy files into container
    echo "📋 Copiando archivos al contenedor..."
    docker cp backend/app/api/routes_dashboard.py automated-trading-platform-backend-aws-1:/app/app/api/routes_dashboard.py 2>/dev/null || \
    docker cp backend/app/api/routes_dashboard.py $(docker compose --profile aws ps -q backend):/app/app/api/routes_dashboard.py
    
    docker cp backend/app/services/signal_monitor.py automated-trading-platform-backend-aws-1:/app/app/services/signal_monitor.py 2>/dev/null || \
    docker cp backend/app/services/signal_monitor.py $(docker compose --profile aws ps -q backend):/app/app/services/signal_monitor.py
    
    echo "🔄 Reiniciando contenedor..."
    docker compose --profile aws restart backend
    
    echo "✅ Backend reiniciado"
    
    # Wait a bit and check status
    sleep 5
    echo ""
    echo "📊 Estado del backend:"
    docker compose --profile aws ps backend
    
    echo ""
    echo "📋 Logs recientes:"
    docker compose --profile aws logs --tail=30 backend | grep -E "(signal_monitor|strategy.decision|BUY signal)" || docker compose --profile aws logs --tail=20 backend
else
    echo "⚠️  No se encontró contenedor Docker, intentando reiniciar proceso uvicorn..."
    pkill -f "uvicorn app.main:app" || true
    sleep 2
    
    cd ~/automated-trading-platform/backend
    source venv/bin/activate 2>/dev/null || true
    nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
    
    sleep 3
    echo "✅ Backend reiniciado"
    echo ""
    echo "📋 Logs recientes:"
    tail -20 backend.log
fi
RESTART_SCRIPT

echo ""
echo "✅ Sincronización y reinicio completados!"
echo ""
echo "🔍 Verificando estado del backend..."
sleep 3

# Verificar que el backend responde
curl -s -f "https://dashboard.hilovivo.com/api/health" > /dev/null && echo "✅ Backend está respondiendo" || echo "⚠️  Backend no responde aún"










