#!/bin/bash
# Script para verificar y corregir el comportamiento de límites de posición en AWS
# Este script verifica si el código correcto está desplegado y proporciona instrucciones

set -e

echo "=========================================="
echo "Verificación de Límites de Posición en AWS"
echo "=========================================="
echo ""

# Verificar si el código correcto está en AWS
echo "1. Verificando código en AWS..."
if ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && grep -q "ORDEN NO EJECUTADA POR VALOR EN CARTERA" backend/app/services/signal_monitor.py' 2>/dev/null; then
    echo "   ✅ Código correcto encontrado en AWS"
    CODE_CORRECT=true
else
    echo "   ❌ Código antiguo detectado en AWS (busca 'ALERTA BLOQUEADA')"
    CODE_CORRECT=false
fi

# Verificar si existe la columna order_skipped
echo ""
echo "2. Verificando columna order_skipped en base de datos..."
if ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec -T db-aws psql -U trader -d atp -c "SELECT column_name FROM information_schema.columns WHERE table_name = '\''telegram_messages'\'' AND column_name = '\''order_skipped'\'';"' 2>/dev/null | grep -q "order_skipped"; then
    echo "   ✅ Columna order_skipped existe"
    COLUMN_EXISTS=true
else
    echo "   ❌ Columna order_skipped NO existe"
    COLUMN_EXISTS=false
fi

# Verificar mensajes recientes
echo ""
echo "3. Verificando mensajes recientes de LDO_USD..."
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec -T db-aws psql -U trader -d atp -c "SELECT id, symbol, blocked, order_skipped, LEFT(message, 100) as message FROM telegram_messages WHERE symbol = '\''LDO_USD'\'' ORDER BY timestamp DESC LIMIT 3;"' 2>/dev/null || echo "   ⚠️ No se pudieron obtener mensajes"

echo ""
echo "=========================================="
echo "Resumen y Acciones Necesarias"
echo "=========================================="
echo ""

if [ "$CODE_CORRECT" = false ]; then
    echo "❌ PROBLEMA: El código en AWS está desactualizado"
    echo ""
    echo "   Solución:"
    echo "   1. Hacer commit y push de los cambios locales"
    echo "   2. Desplegar a AWS (o hacer pull en el servidor)"
    echo "   3. Reiniciar el backend:"
    echo "      ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart backend-aws'"
    echo ""
fi

if [ "$COLUMN_EXISTS" = false ]; then
    echo "❌ PROBLEMA: La columna order_skipped no existe"
    echo ""
    echo "   Solución:"
    echo "   ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec backend-aws python scripts/migrate_add_order_skipped.py'"
    echo ""
fi

if [ "$CODE_CORRECT" = true ] && [ "$COLUMN_EXISTS" = true ]; then
    echo "✅ Todo parece estar correcto"
    echo ""
    echo "   Si aún ves mensajes de 'ALERTA BLOQUEADA', intenta:"
    echo "   1. Reiniciar el backend:"
    echo "      ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart backend-aws'"
    echo ""
    echo "   2. Verificar logs recientes:"
    echo "      ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs backend-aws | grep -E \"ORDEN NO EJECUTADA|ALERTA BLOQUEADA\" | tail -10'"
    echo ""
fi

echo "=========================================="
