#!/bin/bash
# Script para arreglar el deployment y la conexión a la base de datos
# Ejecutar en el servidor AWS: ssh hilovivo-aws

set -e  # Exit on error

echo "🔧 FIX DEPLOYMENT SCRIPT"
echo "========================"
echo ""

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Función para imprimir mensajes
info() {
    echo -e "${GREEN}✅ $1${NC}"
}

warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

error() {
    echo -e "${RED}❌ $1${NC}"
}

# Verificar que estamos en el directorio correcto
if [ ! -f "docker-compose.yml" ]; then
    error "No se encontró docker-compose.yml. ¿Estás en el directorio correcto?"
    echo "Ejecuta: cd ~/crypto-2.0"
    exit 1
fi

info "Directorio correcto: $(pwd)"
echo ""

# Paso 1: Verificar estado actual de los servicios
echo "📊 PASO 1: Verificando estado actual de los servicios"
echo "---------------------------------------------------"
docker compose --profile aws ps
echo ""

# Verificar si db está corriendo
if docker compose --profile aws ps | grep -q "db.*Up"; then
    info "Servicio 'db' está corriendo"
else
    warn "Servicio 'db' NO está corriendo. Iniciándolo..."
    docker compose --profile aws up -d db
    echo "Esperando 10 segundos para que db inicie..."
    sleep 10
fi

# Verificar si backend-aws está corriendo
if docker compose --profile aws ps | grep -q "backend-aws.*Up"; then
    info "Servicio 'backend-aws' está corriendo"
else
    warn "Servicio 'backend-aws' NO está corriendo. Iniciándolo..."
    docker compose --profile aws up -d backend-aws
fi

echo ""

# Paso 2: Verificar red Docker
echo "🌐 PASO 2: Verificando red Docker"
echo "---------------------------------"
NETWORK_NAME=$(docker compose --profile aws config | grep -A 5 "networks:" | tail -1 | awk '{print $1}' | tr -d ':')
if [ -z "$NETWORK_NAME" ]; then
    NETWORK_NAME="automated-trading-platform_default"
fi

info "Red Docker: $NETWORK_NAME"

# Verificar que ambos contenedores están en la misma red
DB_CONTAINER=$(docker compose --profile aws ps -q db)
BACKEND_CONTAINER=$(docker compose --profile aws ps -q backend-aws)

if [ -n "$DB_CONTAINER" ] && [ -n "$BACKEND_CONTAINER" ]; then
    DB_NETWORK=$(docker inspect $DB_CONTAINER | grep -A 10 "Networks" | grep "$NETWORK_NAME" || echo "")
    BACKEND_NETWORK=$(docker inspect $BACKEND_CONTAINER | grep -A 10 "Networks" | grep "$NETWORK_NAME" || echo "")
    
    if [ -n "$DB_NETWORK" ] && [ -n "$BACKEND_NETWORK" ]; then
        info "Ambos contenedores están en la misma red: $NETWORK_NAME"
    else
        warn "Los contenedores pueden no estar en la misma red"
    fi
else
    warn "No se pudieron obtener IDs de contenedores"
fi

echo ""

# Paso 3: Probar resolución DNS
echo "🔍 PASO 3: Probando resolución DNS"
echo "----------------------------------"
if [ -n "$BACKEND_CONTAINER" ]; then
    info "Probando resolución de 'db' desde backend-aws..."
    if docker exec $BACKEND_CONTAINER ping -c 2 db > /dev/null 2>&1; then
        info "✅ 'db' es accesible desde backend-aws"
    else
        error "❌ 'db' NO es accesible desde backend-aws"
        warn "Intentando reiniciar servicios..."
        docker compose --profile aws restart db backend-aws
        sleep 5
        if docker exec $BACKEND_CONTAINER ping -c 2 db > /dev/null 2>&1; then
            info "✅ 'db' ahora es accesible después del reinicio"
        else
            error "❌ 'db' sigue sin ser accesible. Revisar configuración Docker."
        fi
    fi
else
    warn "No se pudo obtener ID del contenedor backend-aws"
fi

echo ""

# Paso 4: Verificar conexión a PostgreSQL
echo "🗄️  PASO 4: Verificando conexión a PostgreSQL"
echo "--------------------------------------------"
if [ -n "$BACKEND_CONTAINER" ]; then
    info "Probando conexión a PostgreSQL desde backend-aws..."
    if docker exec $BACKEND_CONTAINER python -c "
import psycopg2
import os
db_url = os.getenv('DATABASE_URL', 'postgresql://trader:traderpass@db:5432/atp')
try:
    conn = psycopg2.connect(db_url)
    conn.close()
    print('SUCCESS')
except Exception as e:
    print(f'ERROR: {e}')
" 2>&1 | grep -q "SUCCESS"; then
        info "✅ Conexión a PostgreSQL exitosa"
    else
        error "❌ Conexión a PostgreSQL falló"
        docker exec $BACKEND_CONTAINER python -c "
import psycopg2
import os
db_url = os.getenv('DATABASE_URL', 'postgresql://trader:traderpass@db:5432/atp')
try:
    conn = psycopg2.connect(db_url)
    conn.close()
    print('SUCCESS')
except Exception as e:
    print(f'ERROR: {e}')
" 2>&1
    fi
else
    warn "No se pudo obtener ID del contenedor backend-aws"
fi

echo ""

# Paso 5: Actualizar código desde git
echo "📥 PASO 5: Actualizando código desde git"
echo "----------------------------------------"
info "Obteniendo últimos cambios de git..."
git fetch origin
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
    warn "Estás en la rama '$CURRENT_BRANCH', cambiando a 'main'..."
    git checkout main
fi

LOCAL_COMMIT=$(git rev-parse HEAD)
REMOTE_COMMIT=$(git rev-parse origin/main)

if [ "$LOCAL_COMMIT" != "$REMOTE_COMMIT" ]; then
    info "Hay cambios nuevos en remoto. Actualizando..."
    git pull origin main
    info "Código actualizado"
else
    info "Código ya está actualizado"
fi

echo "Último commit: $(git log -1 --oneline)"
echo ""

# Paso 6: Reconstruir y reiniciar servicios
echo "🔨 PASO 6: Reconstruyendo y reiniciando servicios"
echo "------------------------------------------------"
warn "Esto puede tomar varios minutos..."
docker compose --profile aws down
sleep 5
docker compose --profile aws up -d --build
info "Servicios reconstruidos y reiniciados"
echo ""

# Paso 7: Esperar a que los servicios estén listos
echo "⏳ PASO 7: Esperando a que los servicios estén listos"
echo "-----------------------------------------------------"
info "Esperando 30 segundos para que los servicios inicien..."
sleep 30

# Verificar health checks
echo "Verificando health checks..."
for i in {1..6}; do
    if docker compose --profile aws ps | grep -q "backend-aws.*healthy"; then
        info "✅ backend-aws está healthy"
        break
    elif [ $i -eq 6 ]; then
        warn "⚠️  backend-aws aún no está healthy después de 60 segundos"
    else
        echo "   Intento $i/6... esperando 10 segundos más..."
        sleep 10
    fi
done

if docker compose --profile aws ps | grep -q "db.*healthy"; then
    info "✅ db está healthy"
else
    warn "⚠️  db puede no estar healthy aún"
fi

echo ""

# Paso 8: Verificar logs
echo "📋 PASO 8: Verificando logs recientes"
echo "-------------------------------------"
echo "Últimas 20 líneas de logs de db:"
docker compose --profile aws logs db --tail=20
echo ""
echo "Últimas 20 líneas de logs de backend-aws:"
docker compose --profile aws logs backend-aws --tail=20
echo ""

# Paso 9: Probar endpoints
echo "🧪 PASO 9: Probando endpoints"
echo "-----------------------------"
BACKEND_URL="http://localhost:8002"

# Health check
info "Probando health check..."
if curl -s "$BACKEND_URL/health" | grep -q "ok"; then
    info "✅ Health check OK"
else
    error "❌ Health check falló"
fi

# Order history
info "Probando order history..."
HISTORY_RESPONSE=$(curl -s "$BACKEND_URL/api/orders/history?limit=1&offset=0" 2>&1)
if echo "$HISTORY_RESPONSE" | grep -q "orders"; then
    info "✅ Order history funciona"
elif echo "$HISTORY_RESPONSE" | grep -q "could not translate host name"; then
    error "❌ Order history falla: problema de DNS con 'db'"
    warn "Puede necesitar más tiempo para que la red Docker se estabilice"
else
    warn "⚠️  Order history devolvió respuesta inesperada"
    echo "$HISTORY_RESPONSE" | head -3
fi

# Sync endpoint
info "Probando sync endpoint..."
SYNC_RESPONSE=$(curl -s -X POST "$BACKEND_URL/api/orders/sync-history" 2>&1)
if echo "$SYNC_RESPONSE" | grep -q "ok"; then
    info "✅ Sync endpoint funciona"
else
    warn "⚠️  Sync endpoint puede tener problemas"
    echo "$SYNC_RESPONSE" | head -3
fi

echo ""

# Resumen final
echo "================================"
echo "📊 RESUMEN FINAL"
echo "================================"
echo ""
docker compose --profile aws ps
echo ""
info "Script completado!"
echo ""
echo "Próximos pasos:"
echo "1. Verificar que los servicios están corriendo: docker compose --profile aws ps"
echo "2. Monitorear logs: docker compose --profile aws logs -f backend-aws"
echo "3. Probar desde el frontend: https://dashboard.hilovivo.com"
echo ""















