# 🚫 Condiciones que Bloquean las Compras

## ✅ Condiciones Requeridas para Crear Órdenes

### 1. **Flags de Configuración** (CRÍTICO)
- ✅ `trade_enabled = YES` ← **OBLIGATORIO** (línea 2078)
- ✅ `alert_enabled = YES` ← **OBLIGATORIO** (línea 2083)
- ✅ `buy_alert_enabled = YES` ← Para alertas (no bloquea órdenes)

### 2. **Señal BUY Activa**
- ✅ `buy_signal = True` O `strategy.decision = "BUY"`
- ✅ Sin esto, NO se crean órdenes

### 3. **Indicadores Técnicos** (CRÍTICO)
- ✅ `MA50` debe estar disponible (línea 2094)
- ✅ `EMA10` debe estar disponible (línea 2094)
- ❌ Si faltan MAs → **BLOQUEO** (línea 2094-2114)

## 🚫 Condiciones que BLOQUEAN las Compras

### Bloqueo 1: Máximo de Órdenes Abiertas (Línea 1942)
**Condición**: `unified_open_positions >= 3`
- **Límite**: Máximo 3 órdenes abiertas por símbolo (base currency)
- **Ejemplo**: Si tienes 3 órdenes BUY abiertas para BTC, NO se creará otra
- **Solución**: Espera a que se ejecuten o cancela algunas órdenes

### Bloqueo 2: Cooldown de 5 Minutos (Línea 1949-1976)
**Condición**: Hay una orden BUY creada en los últimos 5 minutos
- **Límite**: No se pueden crear órdenes consecutivas
- **Ejemplo**: Si creaste una orden hace 3 minutos, NO se creará otra hasta que pasen 5 minutos
- **Solución**: Espera 5 minutos desde la última orden

### Bloqueo 3: Cambio de Precio Insuficiente (Línea 1979-2008)
**Condición**: `price_change_pct < MIN_PRICE_CHANGE_PCT` (default: 1%)
- **Límite**: Requiere mínimo 1% de cambio de precio desde la última orden
- **Ejemplo**: Si la última orden fue a $100 y el precio actual es $100.50 (0.5%), NO se creará otra orden
- **Solución**: Espera a que el precio cambie al menos 1%

### Bloqueo 4: Portfolio Limit Excedido (Línea 2125-2143)
**Condición**: `portfolio_value > 3 * trade_amount_usd`
- **Límite**: El valor del portfolio no puede exceder 3x el `trade_amount_usd`
- **Ejemplo**: Si `trade_amount_usd = $100` y ya tienes $350 en BTC, NO se creará otra orden
- **Solución**: Reduce la posición o aumenta `trade_amount_usd`

### Bloqueo 5: Lock de Creación de Órdenes (Línea 1921-1928)
**Condición**: Hay un lock activo de 10 segundos
- **Límite**: No se pueden crear órdenes simultáneas (protección contra duplicados)
- **Ejemplo**: Si se está creando una orden, NO se creará otra durante 10 segundos
- **Solución**: Espera 10 segundos

### Bloqueo 6: MAs Faltantes (Línea 2094-2114)
**Condición**: `MA50 is None` O `EMA10 is None`
- **Límite**: Los indicadores técnicos son obligatorios
- **Ejemplo**: Si no hay datos de MA50 o EMA10, NO se creará la orden
- **Solución**: Espera a que se actualicen los indicadores técnicos

## 🔍 Cómo Diagnosticar

### Script de Diagnóstico
```bash
python3 diagnosticar_bloqueo_compras.py SYMBOL
```

### Verificar Logs del Backend
```bash
docker compose --profile aws logs backend | grep -E "(BLOCKED|should_create_order|trade_enabled)"
```

### Verificar Órdenes Abiertas
```bash
# En el dashboard o API:
GET /api/orders/open
```

## 💡 Soluciones Comunes

### Problema: "Las órdenes no se crean aunque hay señal BUY"

**Checklist**:
1. ✅ `trade_enabled = YES`?
2. ✅ `alert_enabled = YES`?
3. ✅ Hay señal BUY activa (`strategy.decision = "BUY"`)?
4. ✅ Hay menos de 3 órdenes abiertas?
5. ✅ Pasaron más de 5 minutos desde la última orden?
6. ✅ El precio cambió al menos 1% desde la última orden?
7. ✅ El portfolio value < 3x trade_amount_usd?
8. ✅ MA50 y EMA10 están disponibles?

### Si todo está OK pero no se crean órdenes:

1. **Revisa los logs** para ver el motivo específico:
   ```bash
   docker compose --profile aws logs -f backend | grep -E "(BLOCKED|should_create_order)"
   ```

2. **Verifica el estado del símbolo**:
   ```bash
   python3 diagnosticar_bloqueo_compras.py SYMBOL
   ```

3. **Revisa órdenes recientes**:
   - Puede haber una orden creada hace menos de 5 minutos
   - Puede haber 3 órdenes abiertas ya

## 📊 Resumen de Límites

| Condición | Límite | Ubicación en Código |
|-----------|--------|---------------------|
| Máximo órdenes por símbolo | 3 | Línea 60, 1942 |
| Cooldown entre órdenes | 5 minutos | Línea 1786, 1949 |
| Cambio de precio mínimo | 1% | Línea 61, 1989 |
| Portfolio limit | 3x trade_amount_usd | Línea 2122, 2125 |
| Lock de creación | 10 segundos | Línea 62, 1921 |

## ✅ Estado Actual del Fix

- ✅ Fix de alertas desplegado
- ✅ `alert_enabled` se habilita automáticamente
- ✅ `signal_monitor` usa `strategy.decision`
- ⚠️  Las órdenes tienen múltiples condiciones de bloqueo (por diseño)

