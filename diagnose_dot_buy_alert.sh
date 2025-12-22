#!/bin/bash

# Script de diagnóstico para DOT_USDT BUY alert
# Verifica todas las posibles causas por las que no se envían alertas

SYMBOL="DOT_USDT"
CONTAINER_NAME="backend-aws"  # Ajustar según tu configuración

echo "=========================================="
echo "🔍 DIAGNÓSTICO: DOT_USDT BUY Alert"
echo "=========================================="
echo ""

# 1. Verificar estado del servicio SignalMonitorService
echo "1️⃣ VERIFICANDO ESTADO DEL SERVICIO..."
echo "----------------------------------------"
docker logs $CONTAINER_NAME 2>&1 | grep -i "SignalMonitorService" | tail -10
echo ""

# Verificar si está corriendo
IS_RUNNING=$(docker logs $CONTAINER_NAME 2>&1 | grep -i "SignalMonitorService.*is_running" | tail -1)
if [ -z "$IS_RUNNING" ]; then
    echo "⚠️  No se encontró información sobre el estado del servicio"
else
    echo "Estado del servicio: $IS_RUNNING"
fi
echo ""

# 2. Buscar señales detectadas para DOT_USDT
echo "2️⃣ SEÑALES BUY DETECTADAS PARA $SYMBOL..."
echo "----------------------------------------"
docker logs $CONTAINER_NAME 2>&1 | grep -i "$SYMBOL.*BUY signal detected" | tail -5
echo ""

# 3. Buscar candidatos de señal (antes del throttle)
echo "3️⃣ CANDIDATOS DE SEÑAL (ANTES DEL THROTTLE)..."
echo "----------------------------------------"
docker logs $CONTAINER_NAME 2>&1 | grep -i "$SYMBOL.*signal candidate" | tail -5
echo ""

# 4. Buscar bloqueos por throttle (CRÍTICO)
echo "4️⃣ BLOQUEOS POR THROTTLE (CRÍTICO)..."
echo "----------------------------------------"
BLOCKED=$(docker logs $CONTAINER_NAME 2>&1 | grep -i "$SYMBOL.*BLOQUEADO\|$SYMBOL.*BLOCKED" | tail -10)
if [ -z "$BLOCKED" ]; then
    echo "✅ No se encontraron bloqueos recientes"
else
    echo "🚫 BLOQUEOS ENCONTRADOS:"
    echo "$BLOCKED"
fi
echo ""

# 5. Buscar decisiones de alerta
echo "5️⃣ DECISIONES DE ALERTA..."
echo "----------------------------------------"
ALERT_DECISION=$(docker logs $CONTAINER_NAME 2>&1 | grep -i "$SYMBOL.*BUY alert decision" | tail -5)
if [ -z "$ALERT_DECISION" ]; then
    echo "⚠️  No se encontraron decisiones de alerta (puede indicar que buy_signal fue False antes de llegar aquí)"
else
    echo "$ALERT_DECISION"
fi
echo ""

# 6. Buscar si se procesó la alerta
echo "6️⃣ PROCESAMIENTO DE ALERTA..."
echo "----------------------------------------"
PROCESSED=$(docker logs $CONTAINER_NAME 2>&1 | grep -i "$SYMBOL.*NEW BUY signal detected" | tail -5)
if [ -z "$PROCESSED" ]; then
    echo "⚠️  No se encontró procesamiento de alerta"
else
    echo "✅ Alertas procesadas:"
    echo "$PROCESSED"
fi
echo ""

# 7. Buscar verificación de throttle
echo "7️⃣ VERIFICACIÓN DE THROTTLE..."
echo "----------------------------------------"
docker logs $CONTAINER_NAME 2>&1 | grep -i "$SYMBOL.*throttle check\|$SYMBOL.*should_emit" | tail -5
echo ""

# 8. Buscar información de flags (alert_enabled, buy_alert_enabled)
echo "8️⃣ FLAGS DE ALERTA..."
echo "----------------------------------------"
docker logs $CONTAINER_NAME 2>&1 | grep -i "$SYMBOL.*alert_enabled\|$SYMBOL.*buy_alert_enabled" | tail -10
echo ""

# 9. Buscar errores relacionados
echo "9️⃣ ERRORES RELACIONADOS..."
echo "----------------------------------------"
docker logs $CONTAINER_NAME 2>&1 | grep -i "$SYMBOL.*error\|$SYMBOL.*failed\|$SYMBOL.*exception" | tail -5
echo ""

# 10. Resumen de los últimos logs de DOT_USDT
echo "🔟 ÚLTIMOS LOGS DE $SYMBOL (últimas 20 líneas)..."
echo "----------------------------------------"
docker logs $CONTAINER_NAME 2>&1 | grep -i "$SYMBOL" | tail -20
echo ""

echo "=========================================="
echo "✅ DIAGNÓSTICO COMPLETADO"
echo "=========================================="
echo ""
echo "📋 PRÓXIMOS PASOS:"
echo "1. Si ves 'BLOQUEADO' → El throttle está bloqueando"
echo "2. Si NO ves 'BUY signal detected' → El bot puede estar detenido o las condiciones no se cumplen"
echo "3. Si ves 'BUY signal detected' pero NO 'NEW BUY signal detected' → El throttle o flags están bloqueando"
echo "4. Verificar configuración en base de datos con el script SQL siguiente"

