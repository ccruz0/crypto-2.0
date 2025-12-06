# Solución: Monedas Desaparecidas y Órdenes TP Fallando

## Problemas Identificados

### 1. Monedas Desaparecidas del Dashboard
- **Síntoma:** SOL_USDT y otras monedas no aparecen en el dashboard
- **Causa probable:** `is_deleted = True` en la base de datos
- **Solución:** Restaurar monedas marcadas como eliminadas

### 2. Órdenes TP Fallando
- **Síntoma:** Mensaje "❌ TP Order: FAILED (no se pudo crear)"
- **Causa:** Error al crear la orden TP (probablemente error 229, 40004, o 220)
- **Solución:** Revisar logs y ajustar la lógica según el error específico

## Soluciones Inmediatas

### Paso 1: Restaurar Monedas Desaparecidas

Ejecuta en AWS:

```bash
docker compose exec backend-aws python3 /app/tools/fix_missing_coins.py
```

O manualmente en la base de datos:

```sql
-- Restaurar SOL_USDT
UPDATE watchlist_items SET is_deleted = FALSE WHERE symbol = 'SOL_USDT';

-- Verificar otras monedas comunes
SELECT symbol, is_deleted, created_at 
FROM watchlist_items 
WHERE symbol IN ('BTC_USDT', 'ETH_USDT', 'DOGE_USDT', 'ADA_USDT', 'TON_USDT', 'LDO_USDT', 'SOL_USDT')
ORDER BY symbol, created_at DESC;
```

### Paso 2: Diagnosticar Error de TP

Ejecuta en AWS:

```bash
# Ver logs de la última orden TP fallida
docker compose logs backend-aws 2>&1 | grep -E "TP.*FAILED|create_take_profit_order|TP_ORDER.*AUTO" | tail -50

# Ver errores específicos
docker compose logs backend-aws 2>&1 | grep -E "error.*229|error.*40004|error.*220" | tail -30

# Ver payloads HTTP de TP
docker compose logs backend-aws 2>&1 | grep "\[TP_ORDER\]\[AUTO\]" | tail -100
```

### Paso 3: Verificar Estado de Órdenes TP Creadas

Según la imagen, hay múltiples órdenes TP creadas pero no ejecutadas:
- Price: 172.00
- Trigger Condition: >= 165.84
- Completed: 0 (ninguna ejecutada)

Esto sugiere que:
1. Las órdenes TP SÍ se están creando (contrario al mensaje de Telegram)
2. Pero no se están ejecutando porque el precio no ha alcanzado el trigger (165.84)
3. El mensaje de Telegram puede estar reportando incorrectamente el estado

## Acciones Requeridas

1. **Ejecutar script de restauración** para recuperar monedas desaparecidas
2. **Revisar logs** para identificar el error específico de TP
3. **Verificar** si las órdenes TP realmente se están creando o no
4. **Ajustar** la lógica según el error encontrado

## Notas

- El mensaje de Telegram dice "TP Order: FAILED" pero en la imagen veo órdenes TP creadas
- Puede haber un problema de sincronización entre el estado real y el reportado
- Necesitamos verificar los logs HTTP para confirmar si las órdenes se están creando correctamente

