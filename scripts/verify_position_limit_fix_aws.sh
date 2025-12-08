#!/bin/bash
# Script para verificar y corregir el comportamiento de límites de posición en AWS

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
    echo "   ❌ Código antiguo detectado en AWS"
    CODE_CORRECT=false
fi

# Verificar si existe la columna order_skipped
echo ""
echo "2. Verificando columna order_skipped..."
if ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec backend-aws python -c "import sys; sys.path.insert(0, \"/app\"); from app.database import engine; from sqlalchemy import text; conn = engine.connect(); result = conn.execute(text(\"SELECT column_name FROM information_schema.columns WHERE table_name = '\''telegram_messages'\'' AND column_name = '\''order_skipped'\''\")); print(\"EXISTS\" if result.fetchone() else \"NOT_EXISTS\")"' 2>/dev/null | grep -q "EXISTS"; then
    echo "   ✅ Columna order_skipped existe"
    COLUMN_EXISTS=true
else
    echo "   ❌ Columna order_skipped NO existe"
    COLUMN_EXISTS=false
fi

echo ""
echo "=========================================="
echo "Resumen"
echo "=========================================="

if [ "$CODE_CORRECT" = false ]; then
    echo "❌ El código en AWS necesita actualización"
    echo "   Ejecuta: git push (si tienes cambios locales)"
    echo "   Luego en AWS: git pull && docker compose --profile aws restart backend-aws"
fi

if [ "$COLUMN_EXISTS" = false ]; then
    echo "❌ Falta la columna order_skipped"
    echo "   Ejecuta: ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec backend-aws python scripts/migrate_add_order_skipped.py'"
fi

if [ "$CODE_CORRECT" = true ] && [ "$COLUMN_EXISTS" = true ]; then
    echo "✅ Todo correcto - reinicia el backend si es necesario"
fi
