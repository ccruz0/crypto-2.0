# Resumen de Mejoras: Diagnóstico de Alertas de Prueba

## Problema Original
La alerta de prueba para AAVE_USDT se envió correctamente a Telegram, pero NO se creó ninguna orden ni se reportó ningún error visible al usuario.

## Soluciones Implementadas

### 1. Mejoras en el Código (`backend/app/api/routes_test.py`)

#### A. Notificación cuando `trade_enabled = False`
**Ubicación**: Línea ~291

Cuando `trade_enabled = False`, ahora se envía una notificación a Telegram explicando que la orden no se creó porque Trade está en NO.

```python
if not watchlist_item.trade_enabled:
    telegram_notifier.send_message(
        f"⚠️ <b>TEST ALERT: Orden no creada</b>\n\n"
        f"📊 Symbol: <b>{symbol}</b>\n"
        f"🟢 Señal: BUY detectada\n"
        f"✅ Alerta enviada\n"
        f"❌ Orden no creada: {order_error_message}"
    )
```

#### B. Notificación cuando orden retorna `None`
**Ubicación**: Línea ~424

Cuando `_create_buy_order()` retorna `None` (bloqueada por límites/seguridad), se envía una notificación explicando las posibles causas.

```python
if not order_result:
    error_msg = f"⚠️ La creación de orden retornó None para {symbol}. Esto puede deberse a:\n- Límite de órdenes abiertas alcanzado\n- Verificación de seguridad bloqueó la orden\n- Error interno en la creación de orden"
    telegram_notifier.send_message(...)
```

#### C. Notificación de éxito
**Ubicación**: Línea ~353

Cuando la orden se crea exitosamente, se envía una notificación con detalles del order_id y status.

```python
if order_result:
    telegram_notifier.send_message(
        f"✅ <b>TEST ALERT: Orden creada exitosamente</b>\n\n"
        f"📊 Symbol: <b>{symbol}</b>\n"
        f"🟢 Side: BUY\n"
        f"💰 Amount: ${bg_watchlist_item.trade_amount_usd:.2f}\n"
        f"🆔 Order ID: {order_id}\n"
        f"📊 Status: {order_result.get('status', 'UNKNOWN')}"
    )
```

### 2. Nuevo Endpoint de Diagnóstico

**Endpoint**: `GET /api/test/diagnose-alert/{symbol}`

**Ubicación**: `backend/app/api/routes_test.py` (línea ~668)

Este endpoint proporciona diagnóstico completo de por qué una alerta no generó una orden:

```bash
curl http://localhost:8002/api/test/diagnose-alert/AAVE_USDT \
  -H "X-API-Key: demo-key"
```

**Respuesta incluye**:
- Configuración del watchlist item (trade_enabled, trade_amount_usd, etc.)
- Estado de órdenes abiertas (símbolo y global)
- Órdenes recientes (últimos 5 minutos)
- Valor en cartera vs límites
- Lista de verificaciones con estado (success/error/warning)
- Lista de problemas detectados
- Recomendaciones para solucionar

### 3. Script de Diagnóstico en Python

**Archivo**: `backend/scripts/diagnose_simulate_alert.py`

Script para ejecutar desde línea de comandos:

```bash
# Dentro del contenedor Docker
docker compose exec backend python scripts/diagnose_simulate_alert.py AAVE_USDT

# O directamente si tienes acceso a Python
python backend/scripts/diagnose_simulate_alert.py AAVE_USDT
```

**Qué verifica**:
1. ✅ Configuración de watchlist (trade_enabled, trade_amount_usd)
2. ✅ Órdenes abiertas (símbolo y global)
3. ✅ Órdenes recientes (últimos 5 minutos)
4. ✅ Valor en cartera vs límites
5. ✅ Resumen de problemas y recomendaciones

### 4. Herramienta Web de Diagnóstico

**Archivo**: `diagnose_alert_issue.html`

Herramienta web visual para diagnosticar problemas de alertas.

**Características**:
- Interfaz web simple y visual
- Auto-detección de API URL (local/AWS)
- Verificación completa de configuración
- Recomendaciones claras y accionables
- Indicadores visuales (✅❌⚠️)

**Uso**:
1. Abrir `diagnose_alert_issue.html` en el navegador
2. Ingresar el símbolo (ej: AAVE_USDT)
3. Click en "Diagnosticar"
4. Ver resultados y recomendaciones

### 5. Documentación

**Archivos creados**:
- `docs/DIAGNOSTICO_SIMULATE_ALERT.md`: Documentación completa del problema y soluciones
- `docs/RESUMEN_MEJORAS_DIAGNOSTICO.md`: Este archivo

## Cómo Usar las Nuevas Herramientas

### Opción 1: Desde el Dashboard (Próximamente)
En futuras versiones, se puede agregar un botón "Diagnosticar" en el dashboard que llame al endpoint.

### Opción 2: Herramienta Web
```
1. Abrir diagnose_alert_issue.html en el navegador
2. Ingresar símbolo
3. Click en "Diagnosticar"
```

### Opción 3: Línea de Comandos
```bash
docker compose exec backend python scripts/diagnose_simulate_alert.py SYMBOL
```

### Opción 4: API Directa
```bash
curl http://localhost:8002/api/test/diagnose-alert/AAVE_USDT \
  -H "X-API-Key: demo-key"
```

### Opción 5: Telegram (Automático)
Ahora recibirás notificaciones automáticas en Telegram cuando:
- ❌ Una orden no se crea (con razón)
- ✅ Una orden se crea exitosamente

## Checklist de Verificación

Para que una alerta de prueba genere una orden, debe cumplir TODOS estos requisitos:

- [ ] ✅ Símbolo existe en watchlist
- [ ] ✅ `trade_enabled = True` (Trade = YES en Dashboard)
- [ ] ✅ `trade_amount_usd > 0` (Amount USD configurado)
- [ ] ✅ Menos de 3 órdenes abiertas para el símbolo
- [ ] ✅ No hay órdenes recientes (últimos 5 minutos)
- [ ] ✅ Valor en cartera <= 3x trade_amount_usd
- [ ] ✅ No bloqueado por verificaciones de seguridad

## Causas Más Probables (Orden de Probabilidad)

1. **`trade_enabled = False`** (70%)
   - Solución: Habilitar "Trade" = YES en Dashboard

2. **`trade_amount_usd` no configurado** (20%)
   - Solución: Configurar "Amount USD" > 0 en Dashboard

3. **Orden bloqueada por límites/seguridad** (10%)
   - Solución: Esperar o revisar logs del backend

## Próximos Pasos Recomendados

1. **Verificar configuración de AAVE_USDT**:
   - Abrir Dashboard
   - Buscar AAVE_USDT
   - Verificar Trade = YES y Amount USD > 0

2. **Probar herramienta de diagnóstico**:
   - Abrir `diagnose_alert_issue.html`
   - Diagnosticar AAVE_USDT
   - Seguir recomendaciones

3. **Repetir prueba de alerta**:
   - Con configuración correcta, la orden debería crearse
   - Recibirás notificación de éxito o error en Telegram

4. **Revisar logs** (si es necesario):
   ```bash
   docker compose logs backend | grep -i "AAVE_USDT\|simulate-alert\|Background.*order"
   ```

## Archivos Modificados

1. `backend/app/api/routes_test.py`:
   - Agregadas 3 notificaciones a Telegram
   - Nuevo endpoint `/test/diagnose-alert/{symbol}`

2. `backend/scripts/diagnose_simulate_alert.py`:
   - Script nuevo para diagnóstico completo

3. `diagnose_alert_issue.html`:
   - Herramienta web nueva para diagnóstico visual

4. `docs/DIAGNOSTICO_SIMULATE_ALERT.md`:
   - Documentación completa del problema

5. `docs/RESUMEN_MEJORAS_DIAGNOSTICO.md`:
   - Este resumen

## Mejoras Futuras Posibles

1. **Botón en Dashboard**: Agregar botón "Diagnosticar" en la vista de cada símbolo
2. **Historial de diagnósticos**: Guardar resultados de diagnósticos
3. **Auto-fix**: Implementar correcciones automáticas cuando sea posible
4. **Alertas proactivas**: Notificar cuando la configuración impide crear órdenes
5. **Dashboard de salud**: Vista global de símbolos con problemas de configuración

## Conclusión

Con estas mejoras, ahora tienes:
- ✅ Notificaciones claras cuando las órdenes no se crean
- ✅ Múltiples formas de diagnosticar problemas
- ✅ Recomendaciones accionables
- ✅ Herramientas visuales y de línea de comandos
- ✅ Documentación completa

Ya no deberías quedarte sin saber por qué una alerta de prueba no generó una orden.

