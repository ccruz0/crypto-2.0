# 📊 Cálculo del Límite de Órdenes Abiertas

## Configuración

El límite máximo de órdenes abiertas por símbolo está configurado en:
- **Archivo**: `backend/app/services/signal_monitor.py`
- **Variable**: `MAX_OPEN_ORDERS_PER_SYMBOL = 3`
- **Línea**: 60

```python
self.MAX_OPEN_ORDERS_PER_SYMBOL = 3  # Maximum open orders per symbol
```

## ¿Cómo se Calcula el Conteo de Órdenes Abiertas?

El sistema usa una función unificada `count_open_positions_for_symbol()` que calcula las órdenes abiertas de la siguiente manera:

### Definición de "Órdenes Abiertas"

```
Órdenes Abiertas = Órdenes BUY Pendientes + Posiciones BUY FILLED no cerradas
```

#### 1. Órdenes BUY Pendientes
- Órdenes con estado: `NEW`, `ACTIVE`, `PARTIALLY_FILLED`
- Solo órdenes principales (NO incluye SL/TP)
- Lado: `BUY`

#### 2. Posiciones BUY FILLED no Cerradas
- Órdenes BUY con estado `FILLED` que aún no han sido completamente cerradas
- Se usa lógica **FIFO** (First In, First Out):
  - **Solo las órdenes SELL FILLED** offset las órdenes BUY más antiguas primero
  - **Las órdenes TP/SL pendientes NO reducen el conteo** - son solo órdenes de protección que aún no se han ejecutado
  - Si una orden BUY FILLED tiene cantidad neta restante (después de restar solo SELLs FILLED), cuenta como 1 posición abierta

**Importante**: 
- Las órdenes TP/SL pendientes **NO** reducen el conteo de posiciones abiertas
- Solo las órdenes SELL FILLED (ya ejecutadas) reducen el conteo
- Ejemplo: 3 órdenes BUY FILLED - 3 órdenes TP pendientes = **3 posiciones abiertas** (las TP pendientes no cuentan)

### Ejemplo de Cálculo

```
Situación:
- 2 órdenes BUY FILLED: 100 AAVE cada una (total: 200 AAVE)
- 1 orden SELL FILLED: 50 AAVE
- 1 orden BUY pendiente (NEW)

Cálculo:
- Órdenes pendientes: 1
- Posiciones FILLED no cerradas: 
  - Primera BUY: 100 AAVE - 50 AAVE (SELL) = 50 AAVE restantes → cuenta como 1 posición
  - Segunda BUY: 100 AAVE (no afectada) → cuenta como 1 posición
- Total: 1 + 2 = 3 órdenes abiertas ✅ (límite alcanzado)
```

## Agrupación por Base Currency

**Importante**: El conteo se hace por **base currency**, no por par completo.

- Si tienes órdenes en `AAVE_USDT` y `AAVE_USD`, se cuentan **juntas**
- El símbolo base es `AAVE` (la parte antes del `_`)

Esto evita tener múltiples posiciones en el mismo activo a través de diferentes pares.

## Verificación del Límite

En `signal_monitor.py` (línea 1797), antes de crear una nueva orden:

```python
if unified_open_positions >= self.MAX_OPEN_ORDERS_PER_SYMBOL:
    logger.warning(
        f"🚫 BLOCKED: {symbol} has reached maximum open orders limit "
        f"({unified_open_positions}/{self.MAX_OPEN_ORDERS_PER_SYMBOL}). Skipping new order."
    )
    should_create_order = False
```

Si el conteo unificado es **>= 3**, se bloquea la creación de nuevas órdenes.

## Logs de Diagnóstico

El sistema registra información detallada en los logs:

```
[OPEN_POSITION_COUNT] symbol=AAVE pending_buy=1 filled_buy=2 filled_sell=1 
                      net_qty=150.0 final_positions=3
```

Nota: Las órdenes TP/SL pendientes no aparecen en el log porque no afectan el conteo de posiciones abiertas.

Y en el flujo de creación de órdenes:

```
🔍 AAVE (base: AAVE) order check: 
   open_orders_raw=1/3 (BUY pending only), 
   open_orders_unified=3/3 (pending BUY + net BUY positions)
```

## ¿Por qué se Bloqueó la Orden para AAVE_USDT?

Si recibiste el mensaje:
```
❌ Orden no creada: ⚠️ La creación de orden retornó None para AAVE_USDT
```

Posibles causas:
1. ✅ **Límite alcanzado**: Ya tienes 3 órdenes abiertas para AAVE (pendientes + FILLED no cerradas)
2. Verificación de seguridad bloqueó la orden
3. Error interno en la creación de orden

### Cómo Verificar

1. **Revisa los logs del backend** buscando:
   ```
   🚫 BLOCKED: AAVE has reached maximum open orders limit
   ```

2. **Consulta el dashboard** para ver cuántas órdenes abiertas tienes para AAVE

3. **Verifica en la base de datos**:
   - Órdenes BUY pendientes (NEW/ACTIVE/PARTIALLY_FILLED)
   - Órdenes BUY FILLED que no han sido completamente cerradas por SELLs

## Cómo Verificar el Estado Actual

### Opción 1: Usar el Script de Diagnóstico

Ejecuta el script de diagnóstico (requiere acceso a la base de datos):

```bash
cd /Users/carloscruz/automated-trading-platform
python3 backend/scripts/diagnose_open_orders_limit.py --symbol AAVE
```

Este script mostrará:
- Conteo unificado de órdenes abiertas
- Desglose de órdenes pendientes
- Desglose de órdenes FILLED
- Cálculo de posiciones netas (FIFO)
- Si el límite ha sido alcanzado

### Opción 2: Revisar los Logs del Backend

Busca en los logs del backend:

```bash
# Si usas Docker
docker logs automated-trading-platform-backend-aws-1 --tail 1000 | grep -i "AAVE.*límite\|AAVE.*BLOCKED\|OPEN_POSITION_COUNT.*AAVE"

# O busca directamente
grep -i "AAVE.*maximum open orders\|AAVE.*límite\|OPEN_POSITION_COUNT.*AAVE" /ruta/a/logs/backend.log
```

Busca mensajes como:
```
🚫 BLOCKED: AAVE has reached maximum open orders limit (7/3)
[OPEN_POSITION_COUNT] symbol=AAVE pending_buy=0 filled_buy=29.232 filled_sell=23.469 net_qty=5.763 final_positions=7
```

### Opción 3: Consultar el Dashboard

1. Ve al Dashboard
2. Revisa la sección "Open Orders" o "Portfolio"
3. Filtra por AAVE para ver todas las órdenes abiertas
4. Cuenta:
   - Órdenes BUY pendientes (NEW/ACTIVE/PARTIALLY_FILLED)
   - Posiciones BUY FILLED que aún no han sido cerradas

### Opción 4: Usar el Endpoint de Diagnóstico

```bash
curl http://localhost:8002/api/test/diagnose-alert/AAVE_USDT
```

## Caso Real: AAVE con 7 Posiciones

Según un diagnóstico previo, AAVE tenía:
- **7 posiciones abiertas** (límite: 3)
- **29.232 AAVE** compradas (FILLED)
- **23.469 AAVE** vendidas (FILLED)
- **5.763 AAVE** netas restantes
- **0 órdenes pendientes**

**¿Por qué 7 posiciones si solo hay 5.763 AAVE netas?**

El sistema cuenta cada orden BUY FILLED que tiene cantidad neta restante como **1 posición**, independientemente de la cantidad. Si tienes:
- 7 órdenes BUY FILLED con cantidades pequeñas que suman 5.763 AAVE
- Cada una tiene algo de cantidad neta restante
- Resultado: 7 posiciones abiertas

Esto es **normal y correcto** - el límite es de **posiciones**, no de cantidad total.

## Modificar el Límite

Si necesitas cambiar el límite, edita `backend/app/services/signal_monitor.py`:

```python
self.MAX_OPEN_ORDERS_PER_SYMBOL = 5  # Cambiar de 3 a 5
```

**Nota**: Aumentar el límite puede aumentar el riesgo de exposición en un solo activo.

## Soluciones cuando el Límite está Alcanzado

1. **Esperar**: Las posiciones se cerrarán automáticamente con SL/TP o manualmente
2. **Cerrar manualmente**: Vende algunas posiciones desde el dashboard
3. **Aumentar el límite**: Solo si realmente necesitas más exposición (no recomendado)
