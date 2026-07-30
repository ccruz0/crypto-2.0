# Prompt Cursor — guardrail cuenta solo posiciones del BOT (no holdings manuales)

Copia en Cursor, repo `crypto-2.0`. Cambio en mecanismo de seguridad (guardrail) — cuidado y tests.

---

Trabaja en `ccruz0/crypto-2.0`. Objetivo (aprobado por Carlos): que el guardrail de posiciones abiertas
cuente **solo posiciones abiertas por el bot**, no las tenencias manuales de Carlos (sincronizadas
desde Crypto.com).

**Causa raíz (confirmada):**
`count_open_positions_for_symbol` (`backend/app/services/order_position_service.py`) cuenta como
"posición abierta" las órdenes BUY pendientes + BUY FILLED no compensadas por SELL FILLED. Cuenta
TODAS, incluidas las manuales/sincronizadas. En runtime: `count_open_positions_for_symbol('BTC')=28`
(BUYs manuales de Carlos) y `count_distinct_symbols_with_open_positions=3` → llena el guardrail
(`maxOpenOrdersTotal=3`) con holdings manuales → el bot no puede abrir NINGÚN BUY.

**Discriminador (ya usado en el repo):** las órdenes creadas por el bot tienen
`ExchangeOrder.trade_signal_id IS NOT NULL` (signal_monitor crea un `TradeSignal` y lo asigna a la orden
automática — ver signal_monitor.py:7838-7868). Las manuales/sincronizadas lo tienen a `None`
(exchange_sync.py:3004 ya hace `was_created_by_system = existing.trade_signal_id is not None`).

**Cambio en `count_open_positions_for_symbol`:**
1. En la query de **pending BUY** y en la de **filled BUY**, añade el filtro:
   `ExchangeOrder.trade_signal_id.isnot(None)`
   → solo cuentan BUYs abiertas por el bot.
2. En la query de **filled SELL** (la que compensa/ofsetea), para no descontar de forma incorrecta con
   ventas manuales, restringe el offset a SELLs del bot o de protección:
   `or_(ExchangeOrder.trade_signal_id.isnot(None), ExchangeOrder.parent_order_id.isnot(None), ExchangeOrder.order_role.in_(["STOP_LOSS","TAKE_PROFIT"]))`
   → así una posición del bot se cierra con su SL/TP o una SELL del bot, no con una venta manual ajena.

Esto propaga el criterio "solo bot" a todo lo que usa esta función: el guardrail por-moneda, el conteo
distinto (`count_distinct_symbols_with_open_positions`) y la invariante de SELL
(`validate_sell_position_exists`). Efecto correcto adicional: el bot solo podrá SELL para cerrar una
posición SUYA (no venderá tus bags manuales).

**Restricciones:** no cambies los umbrales del guardrail ni `check_trade_allowed`; solo QUÉ cuenta como
posición. No toques el live gate, el equity fix ni el bucle de trading.

**Tests** (`backend/tests/test_position_count_bot_only.py`):
- BUY FILLED con `trade_signal_id=None` (manual) → NO cuenta.
- BUY FILLED con `trade_signal_id` set (bot) → cuenta 1.
- BUY del bot compensada por su SELL FILLED (con parent_order_id/rol TP) → cuenta 0.
- Venta manual (trade_signal_id=None, sin parent) NO descuenta una BUY del bot.
- `count_distinct_symbols_with_open_positions` ignora símbolos con solo holdings manuales.

**Validación esperada tras deploy:** `count_open_positions_for_symbol('BTC')` → 0 (era 28);
`count_distinct_symbols_with_open_positions` → 0 si no hay posiciones del bot → el bot tiene hasta 3
huecos y podrá abrir un BUY de DOT/ETH en la próxima señal.

**Entrega:** rama `fix/guardrail-count-bot-positions-only`, PR contra `main`, NO auto-merge. Pega el link.
**Rollback:** revert → vuelve a contar todo (estado actual, bloqueado pero seguro).
