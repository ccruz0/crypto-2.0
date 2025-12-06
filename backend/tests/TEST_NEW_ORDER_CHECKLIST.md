# Checklist: Probar Nueva Orden

## Pasos para Probar

### 1. Verificar Configuración de SOL_USDT

Antes de crear la orden, verifica que SOL_USDT esté configurado:

```bash
# En AWS server
docker compose exec backend-aws python3 /app/tools/check_sol_status.py
```

Debe mostrar:
- ✅ Trade Enabled: YES
- ✅ Amount USD: > 0
- ✅ is_deleted: NO

### 2. Crear Orden de Prueba

1. Ve al Dashboard
2. Busca SOL_USDT en la Watchlist
3. Si no está visible, ejecuta primero:
   ```bash
   docker compose exec backend-aws python3 /app/tools/fix_missing_coins.py
   ```
4. Presiona el botón TEST para crear una orden de prueba

### 3. Verificar Mensajes de Telegram

Deberías recibir:
- ✅ BUY SIGNAL DETECTED
- ✅ BUY ORDER CREATED
- ✅ ORDER EXECUTED
- ✅ SL/TP ORDERS CREATED (o mensaje de error específico si falla)

### 4. Verificar en el Exchange (Crypto.com)

Ve a Orders → Order History y verifica:

**Órdenes TP creadas:**
- ✅ Type: "Take-Profit Limit"
- ✅ Side: **SOLO "Sell"** (NO debe haber "Buy")
- ✅ Price: Precio TP correcto
- ✅ Trigger Condition: >= {TP_price}

**Órdenes SL creadas:**
- ✅ Type: "Stop Limit" o "Stop-Loss Limit"
- ✅ Side: **SOLO "Sell"** (NO debe haber "Buy")
- ✅ Price: Precio SL correcto

### 5. Revisar Logs

Si hay algún problema, revisa los logs:

```bash
# Ver creación de órdenes TP
docker compose exec backend-aws bash /app/tools/diagnose_sl_tp_failure.sh ORDER_ID SOL_USDT

# Ver logs HTTP de TP
docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]\[AUTO\]" | tail -50

# Verificar que solo se usa SELL
docker compose logs backend-aws 2>&1 | grep -E "TP.*side|Closing TP side" | tail -20
```

## Qué Buscar

### ✅ Éxito:
- Mensaje de Telegram: "🛡️ SL/TP ORDERS CREATED"
- En exchange: Solo órdenes TP con Side="Sell"
- En logs: "Closing TP side=SELL" (no BUY)

### ❌ Problema:
- Mensaje de Telegram: "❌ TP Order: FAILED"
- En exchange: Órdenes TP con Side="Buy" (incorrecto)
- En logs: Errores 229, 40004, o 220

## Si Hay Problemas

1. **TP orders con side=BUY:**
   - Verifica logs: `grep "Closing TP side" backend-aws logs`
   - Debe mostrar solo "SELL"

2. **TP orders fallan:**
   - Ejecuta diagnóstico: `bash /app/tools/diagnose_sl_tp_failure.sh ORDER_ID SOL_USDT`
   - Comparte el código de error específico

3. **Monedas desaparecen:**
   - Ejecuta: `python3 /app/tools/fix_missing_coins.py`
   - Verifica: `python3 /app/tools/check_missing_coins.py`

