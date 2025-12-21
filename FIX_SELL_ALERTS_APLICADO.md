# Fix Aplicado: Alertas SELL Habilitadas

## ✅ Problema Resuelto

**Problema identificado**: 18 de 20 símbolos tenían `sell_alert_enabled=False`

**Solución aplicada**: Se habilitó `sell_alert_enabled=True` para todos los símbolos con `alert_enabled=True`

## 📊 Resultado

- ✅ **18 símbolos actualizados**: `sell_alert_enabled` cambiado de `False` a `True`
- ✅ **2 símbolos ya habilitados**: DOGE_USD y ETH_USDT ya tenían `sell_alert_enabled=True`
- ✅ **Total**: 20 símbolos ahora tienen alertas SELL habilitadas

## 🔍 Qué Significa Esto

Ahora que `sell_alert_enabled=True` para todos los símbolos:

1. ✅ **Las señales SELL se detectarán** cuando se cumplan las condiciones técnicas
2. ✅ **Las alertas SELL se enviarán** a Telegram cuando:
   - RSI > umbral de venta (típicamente 70)
   - Reversión de tendencia (MA50 < EMA10 o precio < MA10w)
   - Confirmación de volumen (volume/avg_volume >= min_volume_ratio)
   - `sell_alert_enabled=True` ✅ (ahora habilitado)

## 📝 Próximos Pasos

### Las señales SELL aparecerán cuando:

1. **RSI > 70** (sobrecompra)
2. **Reversión de tendencia**:
   - MA50 < EMA10 (con diferencia >= 0.5%), O
   - Precio < MA10w
3. **Volumen suficiente**: `volume / avg_volume >= min_volume_ratio` (default: 0.5x)

### Monitoreo

Para ver cuando se generen señales SELL:

```bash
# Ver logs de señales SELL
docker compose --profile aws logs -f backend-aws | grep -i "SELL.*signal\|SELL.*detected\|SELL.*alert"

# Ver señales bloqueadas por throttling
docker compose --profile aws logs backend-aws | grep -i "BLOQUEADO.*SELL"
```

## ⚠️ Nota Importante

Aunque `sell_alert_enabled=True` ahora está habilitado, las señales SELL solo se generarán cuando:

- ✅ Se cumplan las condiciones técnicas (RSI, MAs, volumen)
- ✅ El throttling permita emitir la señal (cooldown y cambio de precio)

Si no ves señales SELL inmediatamente, es porque las condiciones técnicas aún no se cumplen (comportamiento esperado).





