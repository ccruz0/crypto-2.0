# Diagnóstico: Por qué LDO no ha creado alerta u orden

## Resumen

Si LDO muestra una señal BUY en el dashboard pero no se ha creado una alerta u orden, hay varias condiciones que deben cumplirse. Este documento explica todas las verificaciones necesarias.

## Condiciones para Enviar ALERTA BUY

### 1. Flags de Configuración ✅

**Requeridos:**
- `alert_enabled = True` (interruptor maestro)
- `buy_alert_enabled = True` (o `None` cuando `alert_enabled=True`)

**Verificación:**
```bash
# Ejecutar script de diagnóstico
cd backend && python scripts/diagnose_ldo_alerts.py
```

**Solución si está deshabilitado:**
- Ir al Dashboard → Watchlist
- Buscar LDO
- Activar "ALERTS ✔" y "BUY ✔" en la columna Actions

### 2. Throttle (Cooldown y Cambio de Precio) ⏱️

**Requerido:**
- **Cooldown:** Debe haber pasado el tiempo configurado desde la última alerta BUY
  - Default: 5 minutos (`alert_cooldown_minutes`)
  - Configurable por símbolo en watchlist
- **Cambio de Precio:** El precio debe haber cambiado al menos el porcentaje mínimo
  - Default: 1.0% (`min_price_change_pct`)
  - Configurable por símbolo en watchlist

**Verificación:**
El script de diagnóstico muestra:
- Tiempo transcurrido desde última alerta
- Cambio de precio desde última alerta
- Si ambos criterios se cumplen

**Solución si está bloqueado:**
- Esperar el tiempo de cooldown restante
- O reducir `alert_cooldown_minutes` en el dashboard
- O reducir `min_price_change_pct` en el dashboard

### 3. Señal BUY Generada 🟢

**Requerido:**
- El backend debe haber generado una señal BUY
- Todos los criterios de la estrategia deben cumplirse:
  - RSI < umbral configurado
  - Volume ≥ ratio mínimo
  - Precio dentro de buy_target (si configurado)
  - Precio > EMA10 (si requerido por estrategia)

**Verificación:**
- El dashboard muestra "BUY" en la columna Signals
- El tooltip muestra "Señal: BUY (todos los criterios BUY cumplidos según backend)"

## Condiciones para Crear ORDEN BUY

### 1. Todas las Condiciones de Alerta ✅

Primero deben cumplirse todas las condiciones para enviar alerta (ver arriba).

### 2. Flags Adicionales para Órdenes 📦

**Requeridos:**
- `trade_enabled = True`
- `trade_amount_usd` configurado (valor > 0)

**Solución si está deshabilitado:**
- Ir al Dashboard → Watchlist
- Buscar LDO
- Activar "BUY ✔" en la columna Actions
- Configurar "Amount USD" en la configuración del símbolo

### 3. Indicadores Técnicos (MAs) 📈

**Requeridos:**
- `MA50` disponible
- `EMA10` disponible

**Nota:** Las alertas se envían aunque falten MAs, pero las órdenes NO se crean sin MAs.

**Solución:**
- Esperar a que el sistema actualice los indicadores técnicos
- Los MAs se actualizan automáticamente cada ciclo de actualización

### 4. Límite de Órdenes Abiertas 🚫

**Requerido:**
- Máximo 3 órdenes abiertas por símbolo base (ej: LDO)
- Si ya hay 3 órdenes abiertas, no se crean más

**Verificación:**
El script de diagnóstico muestra:
- Número de órdenes abiertas para el símbolo
- Si se alcanzó el límite

**Solución:**
- Cerrar órdenes existentes antes de crear nuevas
- O esperar a que se ejecuten las órdenes existentes

### 5. Límite de Portfolio 💰

**Requerido:**
- El valor del portfolio para el símbolo debe ser ≤ 3x `trade_amount_usd`
- Si el portfolio excede este límite, las órdenes se bloquean (pero las alertas se envían)

**Verificación:**
El script de diagnóstico muestra:
- Valor actual del portfolio para el símbolo
- Límite calculado (3x trade_amount_usd)
- Si se excede el límite

**Solución:**
- Reducir `trade_amount_usd` en el dashboard
- O cerrar posiciones existentes para reducir el valor del portfolio

## Script de Diagnóstico

Ejecutar el script de diagnóstico para verificar todas las condiciones:

```bash
cd backend
python scripts/diagnose_ldo_alerts.py
```

El script verifica:
1. ✅ Configuración en watchlist (flags)
2. ⏱️ Estado de throttling (cooldown y cambio de precio)
3. 📊 Órdenes abiertas (límites)
4. 💰 Valor de portfolio (límite 3x)
5. 📈 Indicadores técnicos (MAs)
6. 📝 Resumen y recomendaciones

## Flujo de Decisión

```
¿Señal BUY generada?
├─ NO → No se envía alerta ni se crea orden
└─ SÍ → ¿alert_enabled = True?
    ├─ NO → No se envía alerta ni se crea orden
    └─ SÍ → ¿buy_alert_enabled = True?
        ├─ NO → No se envía alerta ni se crea orden
        └─ SÍ → ¿Throttle permite? (cooldown + cambio precio)
            ├─ NO → No se envía alerta ni se crea orden
            └─ SÍ → ✅ ALERTA SE ENVÍA
                └─ ¿trade_enabled = True?
                    ├─ NO → Solo alerta, no orden
                    └─ SÍ → ¿trade_amount_usd configurado?
                        ├─ NO → Solo alerta, no orden
                        └─ SÍ → ¿MAs disponibles?
                            ├─ NO → Solo alerta, no orden
                            └─ SÍ → ¿Órdenes abiertas < 3?
                                ├─ NO → Solo alerta, no orden
                                └─ SÍ → ¿Portfolio <= límite?
                                    ├─ NO → Solo alerta, no orden
                                    └─ SÍ → ✅ ORDEN SE CREA
```

## Logs del Backend

Para ver logs detallados del procesamiento de señales:

```bash
# Ver logs recientes de LDO
bash scripts/aws_backend_logs.sh --tail 2000 | grep -E "LDO.*(BUY|alert|order)" | tail -50

# Ver logs de throttle
bash scripts/aws_backend_logs.sh --tail 2000 | grep -E "LDO.*(THROTTLE|cooldown)" | tail -50

# Ver logs de bloqueos
bash scripts/aws_backend_logs.sh --tail 2000 | grep -E "LDO.*(BLOQUEADO|BLOCKED)" | tail -50
```

## Checklist Rápido

- [ ] `alert_enabled = True` en dashboard
- [ ] `buy_alert_enabled = True` en dashboard
- [ ] `trade_enabled = True` en dashboard (para órdenes)
- [ ] `trade_amount_usd` configurado (para órdenes)
- [ ] Cooldown cumplido (5 min default)
- [ ] Cambio de precio cumplido (1% default)
- [ ] MAs disponibles: MA50 y EMA10 (para órdenes)
- [ ] Órdenes abiertas < 3 (para órdenes)
- [ ] Portfolio <= 3x trade_amount_usd (para órdenes)

## Notas Importantes

1. **Las alertas y órdenes son independientes:**
   - Las alertas pueden enviarse aunque las órdenes estén bloqueadas
   - Las órdenes requieren todas las condiciones de alertas + condiciones adicionales

2. **Throttle es crítico:**
   - Incluso si todos los flags están activados, el throttle puede bloquear
   - El throttle requiere AMBOS: cooldown Y cambio de precio

3. **MAs son requeridos solo para órdenes:**
   - Las alertas se envían aunque falten MAs
   - Las órdenes NO se crean sin MA50 y EMA10

4. **Límites de portfolio:**
   - El límite de portfolio solo afecta órdenes, no alertas
   - Si se excede el límite, se envía alerta pero no se crea orden





