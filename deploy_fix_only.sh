#!/bin/bash
# Script para sincronizar solo los archivos del fix a AWS

set -e

EC2_HOST_PRIMARY="54.254.150.31"
EC2_HOST_ALTERNATIVE="175.41.189.249"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

# Determinar qué host usar
EC2_HOST=""
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_PRIMARY" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_PRIMARY"
    echo "✅ Usando host primario: $EC2_HOST"
elif ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_ALTERNATIVE" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_ALTERNATIVE"
    echo "✅ Usando host alternativo: $EC2_HOST"
else
    echo "❌ No se puede conectar a ningún host"
    exit 1
fi

echo "========================================="
echo "Desplegando Fix de Alertas a AWS"
echo "========================================="
echo ""

# Sincronizar solo los archivos modificados
echo "📦 Sincronizando archivos modificados..."
rsync_cmd \
  backend/app/api/routes_dashboard.py \
  backend/app/services/signal_monitor.py \
  "$EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/"

echo ""
echo "🔄 Reiniciando backend en AWS..."

ssh_cmd "$EC2_USER@$EC2_HOST" << 'DEPLOY_SCRIPT'
cd ~/automated-trading-platform

# Verificar si estamos usando Docker Compose
if command -v docker > /dev/null && docker compose --profile aws ps backend 2>/dev/null | grep -q "Up"; then
    echo "📋 Copiando archivos al contenedor Docker..."
    
    # Obtener el nombre del contenedor
    CONTAINER_NAME=$(docker compose --profile aws ps -q backend)
    
    if [ -n "$CONTAINER_NAME" ]; then
        # Copiar archivos al contenedor
        docker cp backend/app/api/routes_dashboard.py "$CONTAINER_NAME:/app/app/api/routes_dashboard.py"
        docker cp backend/app/services/signal_monitor.py "$CONTAINER_NAME:/app/app/services/signal_monitor.py"
        
        echo "✅ Archivos copiados al contenedor"
        
        # Reiniciar backend
        echo "🔄 Reiniciando contenedor backend..."
        docker compose --profile aws restart backend
        
        echo "✅ Backend reiniciado"
        
        # Esperar un momento
        sleep 5
        
        # Verificar estado
        echo ""
        echo "📊 Estado del backend:"
        docker compose --profile aws ps backend
        
        echo ""
        echo "📋 Logs recientes (últimas 30 líneas):"
        docker compose --profile aws logs --tail=30 backend | grep -E "(signal_monitor|strategy.decision|BUY|restart)" || docker compose --profile aws logs --tail=20 backend
    else
        echo "❌ No se encontró el contenedor backend"
        docker compose --profile aws ps
    fi
else
    echo "⚠️  No se encontró Docker Compose o el contenedor no está corriendo"
    echo "Intentando reiniciar proceso uvicorn..."
    
    pkill -f "uvicorn app.main:app" || true
    sleep 2
    
    cd ~/automated-trading-platform/backend
    if [ -d "venv" ]; then
        source venv/bin/activate
    fi
    nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
    
    sleep 3
    echo "✅ Backend reiniciado"
    echo ""
    echo "📋 Logs recientes:"
    tail -20 backend.log
fi
DEPLOY_SCRIPT

echo ""
echo "========================================="
echo "✅ Despliegue Completado"
echo "========================================="
echo ""
echo "🔍 Verificando que el backend responde..."
sleep 3

# Verificar salud del backend
if curl -s -f "https://dashboard.hilovivo.com/api/health" > /dev/null 2>&1; then
    echo "✅ Backend está respondiendo correctamente"
else
    echo "⚠️  El backend puede estar reiniciándose aún, espera unos segundos más"
fi

echo ""
echo "💡 Próximos pasos:"
echo "   1. Verifica en el dashboard: https://dashboard.hilovivo.com"
echo "   2. Busca BTC o DOT en la watchlist"
echo "   3. Si muestra BUY con INDEX:100%, la alerta debería saltar automáticamente"
echo "   4. Verifica los logs del backend para confirmar que detecta las señales"














