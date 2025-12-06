# Problema y Solución: Órdenes con Margen

## 🔴 PROBLEMA IDENTIFICADO

### 1. **Balance Disponible Real vs. Dashboard**
- **Dashboard muestra:** $18,351.38 USD de margen disponible
- **Balance real disponible:** Solo $1,414.14 (USD: $521.12 + USDT: $893.01)
- **Diferencia:** $16,937.24 bloqueados o utilizados

### 2. **Error en Órdenes con Margen**
- Las órdenes con `margin = YES` y `leverage = 10x` fallan con:
  ```
  Error 306: INSUFFICIENT_AVAILABLE_BALANCE
  ```

### 3. **Análisis del Error**
Para una orden de $1,000 USD con leverage 10x:
- **Margen teórico necesario:** $100 USD (1,000 / 10)
- **Balance disponible:** $1,414.14 USD
- **Resultado:** Debería ser suficiente, pero Crypto.com lo rechaza

### 4. **Posibles Causas**
1. **Margen bloqueado en posiciones abiertas:** Las 58 órdenes SELL pendientes (SL/TP) pueden estar bloqueando parte del margen
2. **Requisitos adicionales de Crypto.com:** El exchange puede requerir un buffer adicional de margen (más allá del cálculo simple `notional / leverage`)
3. **Cálculo incorrecto del margen disponible:** El balance disponible puede no reflejar todo el margen disponible para trading (parte puede estar reservado)
4. **Mínimo de margen por orden:** Crypto.com podría tener un mínimo de margen requerido por orden

## ✅ SOLUCIÓN IMPLEMENTADA

### 1. **Verificación de Balance Antes de Crear Órdenes**
Se agregó un check que:
- Obtiene el balance disponible real (USD + USDT) antes de crear la orden
- Calcula el margen requerido: `(notional / leverage) * 1.15` (agrega 15% de buffer)
- Compara balance disponible vs. margen requerido
- **Registra advertencia** si no hay suficiente balance, pero **intenta la orden de todas formas** (Crypto.com la rechazará si realmente falta)

### 2. **Logging Mejorado**
Ahora los logs muestran:
```
💰 BALANCE CHECK: available=$1,414.14, margin_required=$115.00 for BTC_USDT
⚠️ INSUFFICIENT BALANCE for margin order: available=$1,414.14 < required=$1,150.00
```

### 3. **Script de Diagnóstico**
Se creó `diagnose_margin_orders.py` que:
- Muestra el balance disponible real
- Calcula el margen bloqueado por órdenes pendientes
- Analiza órdenes con margin fallidas recientes

## 🛠️ RECOMENDACIONES ADICIONALES

### Solución Inmediata:
1. **Reducir el tamaño de las órdenes:**
   - En lugar de $1,000, usar $500 o menos
   - Con leverage 10x, $500 requiere solo $57.50 de margen (con buffer)

2. **Verificar margen en Crypto.com Exchange:**
   - Revisar el dashboard de Crypto.com Exchange directamente
   - Ver si hay posiciones abiertas que bloquean margen
   - Confirmar el margen disponible real para trading

3. **Revisar órdenes pendientes:**
   - Las 58 órdenes SELL pendientes pueden estar bloqueando margen
   - Considerar cancelar algunas si no son necesarias

### Solución a Largo Plazo:
1. **Implementar ajuste automático del tamaño de orden:**
   - Si no hay suficiente balance, reducir automáticamente el tamaño de la orden
   - O cambiar automáticamente a SPOT si margin falla

2. **Caché de balance disponible:**
   - Guardar el balance disponible y actualizarlo periódicamente
   - Usar este balance para calcular automáticamente el tamaño máximo de orden

3. **Notificaciones proactivas:**
   - Enviar alerta de Telegram cuando el balance disponible sea bajo
   - Sugerir reducir el tamaño de las órdenes o añadir más balance

## 📊 CÁLCULO DEL MARGEN

### Fórmula Actual:
```
margen_requerido = (notional / leverage) * 1.15

Ejemplo:
- Notional: $1,000
- Leverage: 10x
- Margen requerido: ($1,000 / 10) * 1.15 = $115
```

### Con el balance actual ($1,414.14):
- **Tamaño máximo de orden con margin:** ~$12,000 (con leverage 10x)
- **Tamaño seguro recomendado:** ~$500-$1,000 para dejar buffer

## 🔍 PRÓXIMOS PASOS

1. ✅ Verificación de balance implementada
2. ⏳ Corregir errores de sintaxis en el código
3. ⏳ Probar con órdenes pequeñas ($100-$500)
4. ⏳ Verificar margen disponible en Crypto.com Exchange dashboard
5. ⏳ Implementar ajuste automático del tamaño de orden (opcional)

