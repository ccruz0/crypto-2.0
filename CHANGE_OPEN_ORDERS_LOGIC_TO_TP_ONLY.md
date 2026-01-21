# Cambio de Lógica: Contar Solo Órdenes TP como Órdenes Abiertas

## Cambio Solicitado

**Antes**: Se contaban todas las órdenes BUY (pendientes + FILLED no cerradas)
**Ahora**: Contar solo órdenes TP (TAKE_PROFIT) pendientes

## Razón

Las órdenes TP representan posiciones esperando ser vendidas. Si hay 3 órdenes TP, significa que hay 3 posiciones esperando ser vendidas.

## Cambio a Implementar

Modificar `count_total_open_positions()` en `backend/app/services/order_position_service.py` para que solo cuente órdenes con:
- `order_role = 'TAKE_PROFIT'`
- `status IN ('NEW', 'ACTIVE', 'PARTIALLY_FILLED')` (pendientes, no FILLED)

## Impacto

- Más simple y directo
- Cuenta solo órdenes esperando ejecución (TP pendientes)
- El límite MAX_OPEN_ORDERS_TOTAL controlará cuántas órdenes TP pueden estar pendientes
