# ALGO_USDT Throttle Reset Status

## ✅ Throttle State Reseteado

**Fecha:** 2026-01-09 13:43:00 UTC  
**Estado:** ✅ Throttle state reseteado exitosamente

### Cambios Aplicados:
- `last_price` = NULL (reset completo)
- `force_next_signal` = TRUE (permite bypass inmediato)
- `emit_reason` = 'MANUAL_RESET_FOR_TESTING'

### Configuración Actual:
- **Symbol:** ALGO_USDT
- **Strategy:** scalp:conservative
- **Side:** BUY
- **Trade Enabled:** ✅ TRUE
- **Trade Amount:** $10.00
- **Margin Trading:** ✅ TRUE
- **Alert Enabled:** ✅ TRUE
- **Buy Alert Enabled:** ✅ TRUE

## Estado Actual del Mercado

**Última actualización:** 2026-01-09 06:36:07 UTC
- **Precio:** $0.13505
- **RSI:** 51.2
- **MA50:** 0.14
- **MA10w:** 0.14
- **Volume Ratio:** 1.80x

## Análisis

**RSI = 51.2** - Este valor está **fuera del rango típico de compra** para estrategias conservadoras:
- Estrategias conservadoras generalmente requieren RSI < 30-40 para señales de compra
- RSI de 51.2 indica que el mercado está en zona neutral/sobrecomprado
- No se disparará una señal BUY hasta que el RSI baje al rango de compra

## Próximos Pasos

1. **Esperar a que el RSI baje** al rango de compra (< 30-40 para estrategias conservadoras)
2. **Monitorear los logs** para ver cuando se dispare la señal
3. **Verificar decision tracing** cuando se dispare la alerta (si se bloquea o se crea la orden)

## Monitoreo

Para verificar si se dispara una alerta:
```bash
# Ver logs recientes de ALGO
docker compose --profile aws logs --tail 500 market-updater-aws 2>&1 | grep -i 'ALGO.*BUY\|ALGO.*signal\|ALGO.*order'

# Ver mensajes de Telegram recientes
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "SELECT id, symbol, LEFT(message, 120) as msg_preview, blocked, decision_type, reason_code, timestamp FROM telegram_messages WHERE symbol = 'ALGO_USDT' AND timestamp >= NOW() - INTERVAL '10 minutes' ORDER BY timestamp DESC LIMIT 10;"
```

## Nota

El throttle está reseteado y listo. El sistema disparará una alerta automáticamente cuando:
1. El RSI baje al rango de compra (< 30-40)
2. Se cumplan las demás condiciones de la estrategia (MA checks, volume, etc.)
3. No haya otros bloqueos (portfolio limit, cooldown, etc.)

---

**Status:** ✅ Throttle reseteado, esperando condiciones de mercado  
**Fecha:** 2026-01-09

