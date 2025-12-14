# Deploy: Cambio Porcentual en Alertas

## Resumen
Cada alerta en Telegram y en el Dashboard ahora muestra el cambio porcentual de precio desde la última alerta del mismo tipo (BUY/SELL) para el mismo símbolo.

## Cambios Implementados

### 1. `backend/app/services/telegram_notifier.py`
- **`send_buy_signal()`**: Añadido parámetro `previous_price: Optional[float] = None`
  - Siempre muestra "📊 Cambio desde última alerta" con:
    - Si hay `price_variation`: muestra el valor proporcionado (ej: "+2.50%")
    - Si hay `previous_price`: calcula y muestra con flecha direccional (ej: "↑ 2.35%")
    - Si no hay precio anterior: muestra "Primera alerta"
  
- **`send_sell_signal()`**: Añadido parámetro `previous_price: Optional[float] = None`
  - Mismo comportamiento que `send_buy_signal()`

- **Mensajes almacenados en DB**: Ahora incluyen el cambio porcentual en el formato:
  - `✅ BUY SIGNAL: {symbol} @ ${price} ({change}) - {reason}`
  - `🔴 SELL SIGNAL: {symbol} @ ${price} ({change}) - {reason}`

### 2. `backend/app/services/signal_monitor.py`
- Actualizadas 3 llamadas a `send_buy_signal()` para incluir `previous_price=prev_buy_price`
- Actualizada 1 llamada a `send_sell_signal()` para incluir `previous_price=prev_sell_price`

### 3. `backend/app/api/signal_monitor.py`
- Actualizada 1 llamada a `send_buy_signal()` para incluir `previous_price=prev_buy_price`

## Ejemplo de Mensaje

### Telegram
```
🟢 BUY SIGNAL DETECTED
🔴 LIVE ALERT - Real-time signal

📈 Symbol: BTC_USDT
💵 Price: $45,230.5000
📊 Cambio desde última alerta: ↑ 2.35%
✅ Reason: Swing/Conservative | RSI=35.0, Price=45230.5000...
```

### Dashboard (Monitoreo)
```
✅ BUY SIGNAL: BTC_USDT @ $45,230.50 (↑ 2.35%) - Swing/Conservative | RSI=35.0...
```

## Compatibilidad
- ✅ **Backward compatible**: El parámetro `previous_price` es opcional
- ✅ **No breaking changes**: Funciona con código existente que no pasa `previous_price`
- ✅ **Sin migraciones**: No requiere cambios en la base de datos

## Testing
1. Verificar que las alertas muestren el cambio porcentual
2. Verificar que "Primera alerta" se muestre para símbolos nuevos
3. Verificar que el Dashboard muestre el cambio porcentual en los mensajes guardados

## Archivos Modificados
- `backend/app/services/telegram_notifier.py` (54 líneas modificadas)
- `backend/app/services/signal_monitor.py` (3 llamadas actualizadas)
- `backend/app/api/signal_monitor.py` (1 llamada actualizada)

## Deployment
```bash
# Revisar cambios
git diff backend/app/services/telegram_notifier.py
git diff backend/app/services/signal_monitor.py
git diff backend/app/api/signal_monitor.py

# Commit y push
git add backend/app/services/telegram_notifier.py
git add backend/app/services/signal_monitor.py
git add backend/app/api/signal_monitor.py
git commit -m "feat: Mostrar cambio porcentual desde última alerta en todas las alertas de Telegram y Dashboard"
git push origin main
```

## Verificación Post-Deploy
1. Ejecutar una alerta de prueba y verificar que muestre el cambio porcentual
2. Verificar en el Dashboard que los mensajes almacenados incluyan el cambio porcentual
3. Verificar que las alertas subsiguientes calculen correctamente el cambio desde la anterior

