#!/bin/bash
# Script de diagnóstico para el deployment

echo "🔍 DIAGNÓSTICO DEL DEPLOYMENT"
echo "=============================="
echo ""

echo "1. Verificando estado del backend (health check):"
curl -s https://dashboard.hilovivo.com/api/health | python3 -m json.tool 2>/dev/null || echo "❌ Backend no responde"
echo ""

echo "2. Verificando endpoint de sync:"
SYNC_RESULT=$(curl -s -X POST https://dashboard.hilovivo.com/api/orders/sync-history)
echo "$SYNC_RESULT" | python3 -m json.tool 2>/dev/null || echo "$SYNC_RESULT"
echo ""

echo "3. Verificando endpoint de order history:"
HISTORY_RESULT=$(curl -s "https://dashboard.hilovivo.com/api/orders/history?limit=3&offset=0" 2>&1)
if echo "$HISTORY_RESULT" | grep -q "could not translate host name"; then
    echo "❌ ERROR: No se puede resolver el hostname 'db'"
    echo "   Detalle: $(echo "$HISTORY_RESULT" | grep -o '"detail":"[^"]*' | cut -d'"' -f4)"
elif echo "$HISTORY_RESULT" | grep -q "Connection refused"; then
    echo "❌ ERROR: Conexión rechazada a la base de datos"
    echo "   Detalle: $(echo "$HISTORY_RESULT" | grep -o '"detail":"[^"]*' | cut -d'"' -f4)"
elif echo "$HISTORY_RESULT" | python3 -m json.tool 2>/dev/null | grep -q "orders"; then
    echo "✅ Order history funciona correctamente"
    echo "$HISTORY_RESULT" | python3 -m json.tool 2>/dev/null | head -20
else
    echo "⚠️  Respuesta inesperada:"
    echo "$HISTORY_RESULT" | head -5
fi
echo ""

echo "4. Verificando commits desplegados:"
echo "   Último commit local: $(git log -1 --oneline)"
echo "   Último commit remoto: $(git log origin/main -1 --oneline 2>/dev/null || echo 'No disponible')"
echo ""

echo "5. Verificando estado del deployment en GitHub:"
gh run list --workflow=deploy.yml --limit 1 2>/dev/null | head -1 || echo "   GitHub CLI no disponible"
echo ""

echo "=============================="
echo "📋 RESUMEN:"
echo ""
if echo "$HISTORY_RESULT" | grep -q "could not translate host name"; then
    echo "❌ PROBLEMA DETECTADO: Base de datos no accesible"
    echo ""
    echo "🔧 SOLUCIÓN RECOMENDADA:"
    echo "   1. Verificar que el servicio 'db' está corriendo en el servidor"
    echo "   2. Verificar que backend-aws y db están en la misma red Docker"
    echo "   3. Reiniciar los servicios:"
    echo "      ssh hilovivo-aws 'cd ~/automated-trading-platform && docker compose --profile aws restart db backend-aws'"
    echo ""
elif echo "$HISTORY_RESULT" | grep -q "Connection refused"; then
    echo "❌ PROBLEMA DETECTADO: Conexión rechazada a PostgreSQL"
    echo ""
    echo "🔧 SOLUCIÓN RECOMENDADA:"
    echo "   1. Verificar que PostgreSQL está escuchando en el puerto 5432"
    echo "   2. Verificar permisos de conexión"
    echo "   3. Reiniciar el servicio db"
    echo ""
else
    echo "✅ Todos los servicios parecen estar funcionando"
    echo ""
fi















