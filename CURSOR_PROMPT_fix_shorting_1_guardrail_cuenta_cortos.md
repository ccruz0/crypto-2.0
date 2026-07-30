# Prompt Cursor — FIX SHORTING 1/2: el guardrail debe contar los cortos (para el runaway)

⚠️ Fix de seguridad. El shorting está OFF (`ALLOW_SHORTING=false`). NO lo reactives; esto es para que,
cuando se reactive, los cortos queden CAPADOS por los guardrails. Cambio en mecanismo de seguridad → tests.

---

Trabaja en `ccruz0/crypto-2.0`. Objetivo (aprobado por Carlos): que `count_open_positions_for_symbol`
cuente también las **posiciones cortas del bot**, para que los guardrails `maxOpenOrdersPerCoin` (1) y
`maxOpenOrdersTotal` (3) capen también los cortos. Ahora NO los cuenta → el bot abrió 10 cortos ETH
seguidos (runaway).

**Causa raíz (confirmada):** `backend/app/services/order_position_service.py`, función
`count_open_positions_for_symbol` (~líneas 98-299). Cuenta solo compromisos BUY (pending BUY + filled
BUY neteados por filled SELL). Un corto es un `side=SELL` de entrada → nunca entra en el conteo →
devuelve 0 para un símbolo con solo cortos.

**Modelo recomendado (neto con signo, evita doble conteo):**
Trabaja con órdenes de ENTRADA del bot por símbolo (rol principal, no protección):
- `entry_filter (BUY)`: `side=BUY, trade_signal_id IS NOT NULL, parent_order_id IS NULL, (order_role IS NULL OR order_role NOT IN ('STOP_LOSS','TAKE_PROFIT'))`.
- `entry_filter (SELL)`: igual pero `side=SELL` — estas son las ENTRADAS de corto.
Calcula cantidades FILLED:
- `filled_buy_entry_qty`, `filled_sell_entry_qty`.
- Netea con órdenes de CIERRE/protección FILLED del lado opuesto (las que cierran la posición):
  cierres de long = SELL con `parent_order_id` o `order_role in (STOP_LOSS,TAKE_PROFIT)`; cierres de
  corto = BUY con `parent_order_id` o `order_role in (STOP_LOSS,TAKE_PROFIT)`.
- `net = (filled_buy_entry_qty - buy_closed) - (filled_sell_entry_qty - sell_closed)` (o el neteo FIFO
  que ya usa la función para longs, replicado con signo).
- Si `net > 0` → posiciones LONG (usa la lógica actual de estimación por tamaño medio / FIFO).
- Si `net < 0` → posiciones SHORT con `abs(net)` (misma estimación).
- Suma `pending` de ambos lados (pending BUY entries → longs; pending SELL entries → shorts).
`total_open_positions = long_positions + short_positions`.

**Puntos clave / riesgos (del análisis):**
- Distinguir SELL de ENTRADA de corto (parent_order_id NULL, rol principal) de SELL de PROTECCIÓN/cierre
  de long (parent_order_id set y/o order_role STOP_LOSS/TAKE_PROFIT). NO contar las de protección como
  posición.
- Hoy el offset `bot_offset_sell_filter` (línea ~139) hace que una SELL de entrada de corto RESTE
  erróneamente del conteo de longs. El modelo neto lo corrige; asegúrate de que las SELL de entrada de
  corto NO se usen como offset de longs.
- No contar doble.

**Efectos colaterales (verifícalos, son deseados):**
- `system_core_trade_guards.py` `count_distinct_symbols_with_open_positions` (~:204,219) y los guards
  `max_open_trades`/per-coin (~:257,262) ahora capan cortos. ✅
- `signal_monitor.py:8511` usa esta función para `position_exists` del guard SELL: un símbolo con corto
  abierto dará `position_exists=True`. Coherente, pero verifica que no rompa lógica de "añadir a corto".

**Tests:** actualiza `backend/tests/test_position_count_bot_only.py` y
`backend/app/tests/test_order_position_service.py`, y añade casos:
- 1 SELL de entrada del bot (trade_signal_id, parent NULL) FILLED sin BUY que cierre → cuenta 1 (corto).
- 3 SELL de entrada del mismo símbolo → cuenta refleja el corto abierto (no 0), de forma que el guard
  per-coin bloquearía el 2º.
- SELL de protección (order_role=STOP_LOSS / parent set) → NO cuenta como posición.
- Long normal (BUY entry) sigue contando igual que antes.

**Entrega:** rama `fix/guardrail-count-short-positions`, PR contra `main`, NO auto-merge. Pega el link.
**Rollback:** revert → vuelve a contar solo longs (cortos sin cap — por eso shorting sigue OFF).
