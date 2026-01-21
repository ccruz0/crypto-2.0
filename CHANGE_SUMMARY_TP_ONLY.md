# Cambio de Lógica: Contar Solo Órdenes TP como Órdenes Abiertas

## Cambio Implementado

Se modificó `count_total_open_positions()` en `backend/app/services/order_position_service.py` para que **solo cuente órdenes TP (TAKE_PROFIT) pendientes**.

## Nueva Lógica

**Antes**: 
- Contaba todas las órdenes BUY (pendientes + FILLED no cerradas)
- Lógica compleja con normalización por BASE currency
- Estimación basada en cantidad neta

**Ahora**:
- Solo cuenta órdenes con `order_role = 'TAKE_PROFIT'`
- Solo órdenes con status: `NEW`, `ACTIVE`, `PARTIALLY_FILLED` (pendientes)
- Más simple y directo: 1 TP pendiente = 1 orden abierta esperando venta

## Beneficios

1. **Más simple**: Lógica directa, fácil de entender
2. **Más preciso**: Si hay 3 TP pendientes = 3 posiciones esperando venta
3. **Más claro**: El límite MAX_OPEN_ORDERS_TOTAL controla directamente cuántas órdenes TP pueden estar pendientes

## Impacto

- El límite `MAX_OPEN_ORDERS_TOTAL=3` ahora significa: máximo 3 órdenes TP pendientes
- Cuando se crea una nueva orden BUY y se crean SL/TP automáticamente, el TP cuenta hacia el límite
- Las órdenes TP FILLED no cuentan (ya se ejecutaron)
