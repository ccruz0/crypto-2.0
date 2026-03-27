#!/bin/bash
# Script para revisar logs de watchlist

echo "📋 Revisando logs de Watchlist"
echo "================================"
echo ""

LOG_FILE="/Users/carloscruz/crypto-2.0/backend/backend.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "⚠️  Archivo de log no encontrado: $LOG_FILE"
    exit 1
fi

echo "🔍 Buscando [WATCHLIST_UPDATE]..."
echo "-----------------------------------"
grep "WATCHLIST_UPDATE" "$LOG_FILE" | tail -20 || echo "   No se encontraron logs de WATCHLIST_UPDATE"

echo ""
echo "🔍 Buscando [WATCHLIST_PROTECT]..."
echo "-----------------------------------"
grep "WATCHLIST_PROTECT" "$LOG_FILE" | tail -20 || echo "   No se encontraron logs de WATCHLIST_PROTECT"

echo ""
echo "📊 Últimas 30 líneas del log:"
echo "-----------------------------"
tail -30 "$LOG_FILE"

echo ""
echo "✅ Revisión completada"















