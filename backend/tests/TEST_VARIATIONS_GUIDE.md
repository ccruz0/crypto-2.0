# Guía para Probar Variaciones de TP y Aislar Error 220

## Scripts Disponibles

### 1. `test_tp_variations_direct.py`
Script que prueba variaciones de payload directamente, una por una, para aislar el error 220.

**Características:**
- Prueba 8 variaciones: 4 con `side`, 4 sin `side`
- Obtiene precio de mercado actual para calcular `ref_price` correctamente
- Envía requests directamente a Crypto.com API
- Logging detallado de cada intento
- Se detiene en la primera variación exitosa

**Uso:**
```bash
# En el servidor AWS
docker compose exec backend-aws python3 /app/tests/test_tp_variations_direct.py

# Ver logs
docker compose logs backend-aws 2>&1 | grep "[TP_ORDER][TEST]" | tail -150
```

### 2. `test_manual_tp.py`
Script original que usa `create_take_profit_order()` (prueba todas las variaciones internas).

**Uso:**
```bash
docker compose exec backend-aws python3 /app/tests/test_manual_tp.py
```

## Variaciones que se Prueban

### Con campo `side`:
1. **minimal_with_side_SELL**: Solo campos requeridos + `side=SELL`
2. **with_client_oid_and_side_SELL**: Con `client_oid` + `side=SELL`
3. **with_time_in_force_and_side_SELL**: Con `time_in_force` + `side=SELL`
4. **all_params_with_side_SELL**: Todos los parámetros + `side=SELL`

### Sin campo `side`:
5. **minimal_without_side**: Solo campos requeridos (sin `side`)
6. **with_client_oid_without_side**: Con `client_oid` (sin `side`)
7. **with_time_in_force_without_side**: Con `time_in_force` (sin `side`)
8. **all_params_without_side**: Todos los parámetros (sin `side`)

## Interpretación de Resultados

### Si alguna variación SIN `side` funciona:
- Crypto.com puede inferir el `side` automáticamente desde la posición abierta
- **Solución**: Omitir el campo `side` en el payload

### Si todas las variaciones fallan con error 220:
- Posible causa 1: No hay posición abierta para AKT_USDT
  - **Solución**: Crear una orden BUY pequeña primero para abrir posición
  
- Posible causa 2: El `side` enviado no coincide con la dirección de la posición
  - **Solución**: Verificar la posición abierta y usar el `side` correcto

- Posible causa 3: Crypto.com requiere el `side` pero en un formato diferente
  - **Solución**: Revisar documentación oficial o payloads de órdenes exitosas

## Próximos Pasos

1. **Ejecutar el test**:
   ```bash
   docker compose exec backend-aws python3 /app/tests/test_tp_variations_direct.py
   ```

2. **Analizar los logs**:
   ```bash
   docker compose logs backend-aws 2>&1 | grep "[TP_ORDER][TEST]" | tail -150
   ```

3. **Si todas fallan**:
   - Verificar si hay posición abierta:
     ```bash
     docker compose exec backend-aws python3 -c "
     from app.services.brokers.crypto_com_trade import trade_client
     positions = trade_client.get_positions()
     print('Open positions:', positions)
     "
     ```
   
   - Si no hay posición, crear una pequeña orden BUY primero

4. **Si alguna funciona**:
   - Identificar qué variación funcionó
   - Ajustar el código para usar solo esa variación
   - Hacer deploy solo cuando confirmemos que funciona

## Notas Importantes

- ⚠️ **NO hacer deploy hasta encontrar la solución**
- ⚠️ Todas las pruebas son en **LIVE TRADING** (dry_run=False)
- ⚠️ Las órdenes pueden crearse realmente en el exchange
- ⚠️ Revisar los logs completos antes de tomar decisiones

