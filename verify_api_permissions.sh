#!/bin/bash
# Script para verificar si los permisos de la API key funcionan después de actualizarlos

echo "🔍 VERIFICACIÓN DE PERMISOS DE API KEY"
echo "======================================"
echo ""

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() {
    echo -e "${GREEN}✅ $1${NC}"
}

error() {
    echo -e "${RED}❌ $1${NC}"
}

warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

echo "1. Probando endpoint que SÍ funciona (get-open-orders)..."
OPEN_ORDERS_RESPONSE=$(curl -s -X POST https://dashboard.hilovivo.com/api/orders/sync-status 2>&1 || echo "endpoint_not_available")
if echo "$OPEN_ORDERS_RESPONSE" | grep -q "ok\|orders"; then
    info "get-open-orders funciona (permisos básicos OK)"
else
    warn "No se pudo verificar get-open-orders"
fi
echo ""

echo "2. Probando endpoint de order history..."
SYNC_RESPONSE=$(curl -s -X POST https://dashboard.hilovivo.com/api/orders/sync-history 2>&1)
if echo "$SYNC_RESPONSE" | grep -q '"ok":true'; then
    info "Sync endpoint responde correctamente"
else
    warn "Sync endpoint puede tener problemas"
fi
echo ""

echo "3. Verificando logs del backend para errores de autenticación..."
sleep 3
AUTH_ERRORS=$(ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws logs backend-aws --tail=100 --since 2m 2>&1 | grep -i '40101\|authentication failed' | tail -5" 2>&1)

if [ -z "$AUTH_ERRORS" ]; then
    info "No se encontraron errores de autenticación recientes"
else
    error "Aún hay errores de autenticación:"
    echo "$AUTH_ERRORS"
fi
echo ""

echo "4. Verificando si se recibieron órdenes del sync..."
sleep 2
ORDERS_RECEIVED=$(ssh hilovivo-aws "cd ~/automated-trading-platform && docker compose --profile aws logs backend-aws --tail=200 --since 5m 2>&1 | grep -E 'Received.*orders from API|Fetched page|Found.*FILLED orders' | tail -3" 2>&1)

if echo "$ORDERS_RECEIVED" | grep -q "Received.*orders"; then
    info "Se están recibiendo órdenes de la API!"
    echo "$ORDERS_RECEIVED"
else
    warn "No se están recibiendo órdenes de la API"
    if echo "$ORDERS_RECEIVED" | grep -q "0 total orders"; then
        error "El sync está recibiendo 0 órdenes - el problema persiste"
    fi
fi
echo ""

echo "5. Verificando órdenes en la base de datos..."
HISTORY_RESPONSE=$(curl -s "https://dashboard.hilovivo.com/api/orders/history?limit=5&offset=0" 2>&1)
if echo "$HISTORY_RESPONSE" | grep -q '"orders"'; then
    ORDER_COUNT=$(echo "$HISTORY_RESPONSE" | python3 -c "import sys, json; data = json.load(sys.stdin); print(len(data.get('orders', [])))" 2>/dev/null || echo "0")
    if [ "$ORDER_COUNT" -gt 0 ]; then
        info "Hay $ORDER_COUNT órdenes en la base de datos"
        
        # Verificar si hay órdenes recientes
        RECENT_ORDERS=$(echo "$HISTORY_RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
orders = data.get('orders', [])
recent = [o for o in orders if '2025-12-15T23:' in o.get('update_datetime', '')]
print(len(recent))
" 2>/dev/null || echo "0")
        
        if [ "$RECENT_ORDERS" -gt 0 ]; then
            info "✅ ¡Se encontraron órdenes del 15/12 a las 23:16!"
        else
            warn "No se encontraron órdenes del 15/12 a las 23:16 aún"
        fi
    else
        warn "Base de datos tiene 0 órdenes"
    fi
else
    error "Error al obtener órdenes de la base de datos"
fi
echo ""

echo "================================"
echo "📊 RESUMEN"
echo "================================"
echo ""
if echo "$AUTH_ERRORS" | grep -q "40101"; then
    error "El problema de autenticación persiste"
    echo ""
    echo "🔧 Próximos pasos:"
    echo "1. Verifica que habilitaste TODOS los permisos de lectura en Crypto.com"
    echo "2. Espera 2-3 minutos más para que los cambios se propaguen"
    echo "3. Si el problema persiste, puede ser un bug conocido de Crypto.com"
    echo "4. Considera contactar soporte de Crypto.com"
else
    if echo "$ORDERS_RECEIVED" | grep -q "Received.*[1-9]"; then
        info "¡Los permisos funcionan! Se están recibiendo órdenes"
    else
        warn "Los permisos pueden estar actualizados, pero aún no se reciben órdenes"
        echo "   Esto puede ser normal si no hay órdenes nuevas en el rango de fechas"
    fi
fi
echo ""















