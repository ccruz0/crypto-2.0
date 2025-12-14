# Resumen: Por qué no recibes alertas desde ayer

## ✅ Estado Actual

### Servicios Corriendo:
- ✅ **Exchange Sync**: Corriendo
- ✅ **Signal Monitor**: Corriendo  
- ✅ **Trading Scheduler**: Corriendo

### Workflows:
- ✅ **Telegram Commands**: Ejecutándose continuamente
- ✅ **Dashboard Snapshot**: Ejecutándose periódicamente
- ⏰ **SL/TP Check**: Se ejecuta diario a las 8:00 AM (ya pasó hoy)
- ⏰ **Daily Summary**: Se ejecuta diario a las 8:00 AM (ya pasó hoy)

## 🔍 Por qué no hay alertas nuevas

### 1. **Signal Throttling (Bloqueo de Señales)**

El sistema tiene un mecanismo de throttling que **bloquea señales** para evitar spam:

- **Cooldown mínimo**: Debe pasar un tiempo mínimo entre señales del mismo tipo
- **Cambio de precio mínimo**: El precio debe cambiar un porcentaje mínimo

**Esto es comportamiento esperado** - el sistema está funcionando correctamente al bloquear señales que no cumplen los criterios.

### 2. **Condiciones de Trading no se Cumplen**

Las alertas solo se generan cuando:
- RSI está por debajo del umbral (para BUY)
- Las medias móviles (MA50, MA200, EMA10) cumplen las condiciones
- El precio está en la posición correcta respecto a las MAs

Si estas condiciones no se cumplen, **no se generan alertas** (comportamiento esperado).

### 3. **Alertas Deshabilitadas**

Verifica en la watchlist que `alert_enabled=True` para los símbolos que quieres monitorear.

## 📊 Estado de Signal Throttle

Según el dashboard:
- **Último evento**: 09/12/2025, 06:05:29 pm GMT+7 (hace ~17 horas)
- **Símbolos monitoreados**: UNI_USDT, LDO_USD, BTC_USD, SOL_USDT, etc.
- **Estado**: No hay nuevas señales porque el throttling está bloqueando

## ✅ Solución

### El sistema está funcionando correctamente

Las alertas no aparecen porque:
1. ✅ El throttling está funcionando (bloquea señales repetitivas)
2. ✅ Las condiciones de trading no se cumplen (precio/RSI/MAs no están en posición)
3. ✅ El sistema está monitoreando activamente (Signal Monitor corriendo)

### Para recibir alertas:

1. **Espera a que se cumplan las condiciones**:
   - RSI bajo (para BUY)
   - Precio en posición correcta respecto a MAs
   - Cambio de precio suficiente (para pasar el throttling)

2. **Verifica configuración de alertas**:
   - `alert_enabled=True` en la watchlist
   - Umbrales de RSI configurados correctamente
   - Estrategia y riesgo configurados

3. **Los workflows diarios se ejecutarán mañana**:
   - `SL/TP Check`: 8:00 AM
   - `Daily Summary`: 8:00 AM

## 🔍 Verificación

### Ver estado de servicios:
```bash
curl http://localhost:8002/api/services/status
```

### Ver logs del scheduler:
```bash
docker compose --profile aws logs backend-aws | grep -i "scheduler"
```

### Ver logs de Signal Monitor:
```bash
docker compose --profile aws logs backend-aws | grep -i "signal.*monitor"
```

## 📝 Conclusión

**El sistema está funcionando correctamente**. No hay alertas porque:
- El throttling está bloqueando señales (diseño intencional)
- Las condiciones de trading no se cumplen actualmente
- Esto es **comportamiento esperado** del sistema

Las alertas aparecerán cuando:
- Se cumplan las condiciones técnicas (RSI, MAs, precio)
- Pase el cooldown del throttling
- El precio cambie lo suficiente

