#!/bin/bash
# Script para probar la persistencia de valores de watchlist

echo "🧪 Testing Watchlist Value Persistence"
echo "======================================"
echo ""

BACKEND_URL="http://localhost:8002/api"
SYMBOL="BTC_USDT"  # Cambiar según necesidad

echo "1️⃣ Verificando backend..."
if ! curl -s "$BACKEND_URL/health" > /dev/null; then
    echo "❌ Backend no está respondiendo en $BACKEND_URL"
    exit 1
fi
echo "✅ Backend está respondiendo"
echo ""

echo "2️⃣ Obteniendo watchlist actual..."
DASHBOARD_RESPONSE=$(curl -s "$BACKEND_URL/dashboard")
SYMBOL_DATA=$(echo "$DASHBOARD_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for item in data:
        if item.get('symbol', '').upper() == '$SYMBOL':
            print(json.dumps(item, indent=2))
            break
except:
    pass
")

if [ -z "$SYMBOL_DATA" ]; then
    echo "⚠️  No se encontró $SYMBOL en la watchlist"
    echo "   Creando item..."
    CREATE_RESPONSE=$(curl -s -X POST "$BACKEND_URL/dashboard" \
        -H "Content-Type: application/json" \
        -d "{\"symbol\":\"$SYMBOL\",\"exchange\":\"CRYPTO_COM\"}")
    echo "$CREATE_RESPONSE" | python3 -m json.tool
    sleep 2
fi

echo "📊 Datos actuales de $SYMBOL:"
echo "$SYMBOL_DATA" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(f\"  ID: {data.get('id')}\")
    print(f\"  Trade Amount USD: {data.get('trade_amount_usd')}\")
    print(f\"  SL Percentage: {data.get('sl_percentage')}\")
    print(f\"  TP Percentage: {data.get('tp_percentage')}\")
    print(f\"  SL Price: {data.get('sl_price')}\")
    print(f\"  TP Price: {data.get('tp_price')}\")
except Exception as e:
    print(f\"  Error: {e}\")
"
echo ""

echo "3️⃣ Estableciendo valores de prueba..."
TEST_AMOUNT=150.50
TEST_SL_PCT=2.5
TEST_TP_PCT=5.0

# Obtener el ID del item
ITEM_ID=$(echo "$SYMBOL_DATA" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('id', ''))
except:
    pass
")

if [ -z "$ITEM_ID" ]; then
    echo "❌ No se pudo obtener el ID del item"
    exit 1
fi

echo "   Actualizando item ID: $ITEM_ID"
UPDATE_RESPONSE=$(curl -s -X PUT "$BACKEND_URL/dashboard/$ITEM_ID" \
    -H "Content-Type: application/json" \
    -d "{
        \"trade_amount_usd\": $TEST_AMOUNT,
        \"sl_percentage\": $TEST_SL_PCT,
        \"tp_percentage\": $TEST_TP_PCT
    }")

echo "   Respuesta:"
echo "$UPDATE_RESPONSE" | python3 -m json.tool | head -20
echo ""

echo "4️⃣ Verificando que los valores se guardaron..."
sleep 2
VERIFY_RESPONSE=$(curl -s "$BACKEND_URL/dashboard")
VERIFY_DATA=$(echo "$VERIFY_RESPONSE" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    for item in data:
        if item.get('symbol', '').upper() == '$SYMBOL':
            print(json.dumps(item, indent=2))
            break
except:
    pass
")

echo "📊 Valores después de actualizar:"
echo "$VERIFY_DATA" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    amount = data.get('trade_amount_usd')
    sl_pct = data.get('sl_percentage')
    tp_pct = data.get('tp_percentage')
    
    if amount == $TEST_AMOUNT:
        print(f\"  ✅ Trade Amount USD: {amount} (correcto)\")
    else:
        print(f\"  ❌ Trade Amount USD: {amount} (esperado: $TEST_AMOUNT)\")
    
    if sl_pct == $TEST_SL_PCT:
        print(f\"  ✅ SL Percentage: {sl_pct} (correcto)\")
    else:
        print(f\"  ❌ SL Percentage: {sl_pct} (esperado: $TEST_SL_PCT)\")
    
    if tp_pct == $TEST_TP_PCT:
        print(f\"  ✅ TP Percentage: {tp_pct} (correcto)\")
    else:
        print(f\"  ❌ TP Percentage: {tp_pct} (esperado: $TEST_TP_PCT)\")
except Exception as e:
    print(f\"  Error: {e}\")
"
echo ""

echo "5️⃣ Revisando logs del backend..."
echo "   Buscando [WATCHLIST_UPDATE] y [WATCHLIST_PROTECT]..."
cd /Users/carloscruz/automated-trading-platform/backend
if [ -f backend.log ]; then
    echo "   Últimas líneas relevantes:"
    tail -50 backend.log | grep -E "WATCHLIST_UPDATE|WATCHLIST_PROTECT" | tail -10 || echo "   No se encontraron logs de watchlist aún"
else
    echo "   ⚠️  Archivo de log no encontrado"
fi
echo ""

echo "✅ Prueba completada"
echo ""
echo "📝 Próximos pasos manuales:"
echo "   1. Abre el dashboard en el navegador"
echo "   2. Establece valores para $SYMBOL"
echo "   3. Refresca la página (F5)"
echo "   4. Verifica que los valores persisten"
echo "   5. Reinicia el backend y verifica de nuevo"

