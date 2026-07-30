# Prompt Cursor — FIX SHORTING 2/2: crear SL/TP para los cortos (no quedan desnudos)

⚠️ Fix de seguridad. Shorting OFF hasta que esto y el fix 1/2 estén listos y probados. Es el más
delicado de los dos: el disparo de protección está BUY-only en varios sitios.

---

Trabaja en `ccruz0/crypto-2.0`. Objetivo (aprobado por Carlos): que cuando el bot abra un CORTO
(SELL de entrada en margen), cree su SL/TP invertido — SL **encima** y TP **debajo** del precio de
entrada, con órdenes de cierre lado **BUY**. Ahora los cortos quedan DESNUDOS (sin protección).

**Diagnóstico (confirmado):** el CÁLCULO ya es side-aware, el problema es el DISPARO.
- `exchange_sync.py:_create_sl_tp_impl` (~:1503, fórmulas :1536-1548) YA calcula SL/TP correctos por side
  (BUY: SL abajo/TP arriba; SELL: SL arriba/TP abajo). ✅
- `tp_sl_order_creator.py` (`get_closing_side_from_entry` :26-44) YA devuelve BUY como cierre de una
  entrada SELL, y coloca SL/TP con el side correcto. ✅
- PERO el disparo de protección tras el fill es **BUY-only**:
  - El bloque que crea/publica protección tras fill vive en la rama BUY (`signal_monitor.py` ~:8055-8302,
    con `OrderFilled(side="BUY")` hardcoded ~:8228).
  - El SELL de ENTRADA de corto se coloca en `_place_order_from_signal` / `place_order_simple`
    (`signal_monitor.py` ~:8461, place_market_order SELL ~:8617) y **retorna sin crear SL/TP**.
  - `sl_tp_checker.py` está hardcoded a BUY (`side="BUY"  # we assume BUY positions` en ~:876, ~:895, y
    busca entry solo en `side==BUY` ~:834-855; mismo patrón ~:1919-1941).
  - NO uses `routes_signals.calculate_stop_loss_and_take_profit` (:253-260) para cortos — es long-only.
  - Nota: `exchange_sync.py:1288` delega a `protection_order_service.py` que NO está commiteado — no
    dependas de ese módulo.

**Cambio recomendado (cableado side-aware, las firmas ya soportan side):**
1. **Disparar protección tras el fill del SELL de entrada de corto.** En `_place_order_from_signal`
   (~:8617), cuando el SELL es apertura de corto en margen y se confirma el fill, invoca el MISMO camino
   de creación de SL/TP que usa el BUY, pasando `side="SELL"` (entry side) y el `filled_price`/`filled_qty`
   reales. Debe pasar por `_create_sl_tp_impl` (side-aware) o por `tp_sl_order_creator` con el entry side
   correcto. Publica `OrderFilled(side="SELL", ...)` en vez del hardcode BUY, o llama directo al creador.
2. **De-hardcodear `sl_tp_checker.py`**: en ~:876, ~:895 (y ~:1922, ~:1941) deriva `entry_side` del
   origen real de la posición (BUY vs SELL de entrada) en vez de `# we assume BUY positions`; y busca
   `entry_price`/`parent_order_id` del lado correcto (~:834-855). Para un corto: entry side SELL, cierre
   BUY, SL encima, TP debajo.
3. Verifica la validación de precios en `tp_sl_order_creator.py:99-119` para el TP de corto (tp_side=BUY
   por debajo del mercado) — según el análisis ya está contemplado; confírmalo.
4. NO reutilices el FORCED_CLOSE de `_create_sell_order` (~:9640-9700) para esto — su semántica es
   *cerrar* un long, no *abrir* un corto con protección.

**Tests:** `backend/tests/test_short_protection.py`:
- Fill de un SELL de entrada de corto (side=SELL, margen) → se crean SL (precio > entry) y TP
  (precio < entry), ambos con side BUY (cierre).
- Las fórmulas de precio para SELL dan SL=entry*(1+sl_pct) y TP=entry*(1-tp_pct).
- Un BUY de entrada de long sigue creando SL abajo / TP arriba (sin regresión).
- `sl_tp_checker` con una posición corta usa entry side SELL (no asume BUY).

**Restricciones:** no toques el live gate, equity, ni el guardrail (eso es el fix 1/2). Solo el disparo y
el side de la protección. No dependas de `protection_order_service.py` (no commiteado).

**Entrega:** rama `fix/short-position-sl-tp`, PR contra `main`, NO auto-merge. Pega el link.
**Nota:** este fix es de tamaño medio y toca varias rutas; si te resulta más seguro, hazlo en pasos
(primero el disparo del SL/TP para el SELL de entrada, luego de-hardcodear sl_tp_checker) con su PR.
