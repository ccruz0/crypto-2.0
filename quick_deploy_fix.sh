#!/bin/bash
# Despliegue rápido solo de los archivos del fix

set -e

EC2_HOST_PRIMARY="54.254.150.31"
EC2_HOST_ALTERNATIVE="175.41.189.249"
EC2_USER="ubuntu"

# Cargar funciones SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Desplegando Fix de Alertas a AWS"
echo "========================================="
echo ""

# Determinar host disponible
EC2_HOST=""
for host in "$EC2_HOST_PRIMARY" "$EC2_HOST_ALTERNATIVE"; do
    if timeout 5 ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$host" "echo test" 2>/dev/null; then
        EC2_HOST="$host"
        echo "✅ Conectado a: $EC2_HOST"
        break
    fi
done

if [ -z "$EC2_HOST" ]; then
    echo "❌ No se puede conectar a AWS vía SSH"
    echo ""
    echo "💡 Alternativas:"
    echo "   1. Usar GitHub Actions (hacer commit y push)"
    echo "   2. Conectarse manualmente vía SSH"
    echo "   3. Usar AWS Session Manager"
    exit 1
fi

# Sincronizar archivos
echo ""
echo "📦 Sincronizando archivos..."
rsync_cmd \
  backend/app/api/routes_dashboard.py \
  backend/app/services/signal_monitor.py \
  "$EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/"

echo ""
echo "🔄 Reiniciando backend..."

ssh_cmd "$EC2_USER@$EC2_HOST" << 'RESTART'
cd ~/automated-trading-platform

# Obtener nombre del contenedor
CONTAINER=$(docker compose --profile aws ps -q backend 2>/dev/null || docker ps -q --filter "name=backend")

if [ -n "$CONTAINER" ]; then
    echo "📋 Copiando archivos al contenedor $CONTAINER..."
    docker cp backend/app/api/routes_dashboard.py "$CONTAINER:/app/app/api/routes_dashboard.py"
    docker cp backend/app/services/signal_monitor.py "$CONTAINER:/app/app/services/signal_monitor.py"
    
    echo "🔄 Reiniciando backend..."
    docker compose --profile aws restart backend || docker restart "$CONTAINER"
    
    echo "✅ Backend reiniciado"
    sleep 5
    
    echo ""
    echo "📊 Estado:"
    docker compose --profile aws ps backend 2>/dev/null || docker ps --filter "name=backend"
    
    echo ""
    echo "📋 Logs recientes:"
    docker compose --profile aws logs --tail=20 backend 2>/dev/null || docker logs --tail=20 "$CONTAINER"
else
    echo "❌ No se encontró contenedor backend"
    docker compose --profile aws ps 2>/dev/null || docker ps
fi
RESTART

echo ""
echo "✅ Despliegue completado!"







