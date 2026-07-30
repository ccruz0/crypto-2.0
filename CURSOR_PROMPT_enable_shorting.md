# 🔴 Prompt Cursor — habilitar SHORTING (alto riesgo, dinero real) — aprobado por Carlos

⚠️ Esto permite que el bot abra posiciones CORTAS en margen sobre señales SELL. Riesgo alto (pérdida
potencialmente ilimitada + coste de préstamo). Va **detrás de un flag OFF por defecto** y solo aplica a
margen. Sigue la validación por fases con el kill switch a mano.

---

Trabaja en `ccruz0/crypto-2.0`. Objetivo (aprobado por Carlos): permitir que una señal SELL sin posición
previa abra un **corto en margen**, en vez de bloquearse con "SELL requires an existing position".

**Situación:** en `backend/app/services/signal_monitor.py` (~8511) el camino SELL calcula
`position_exists = count_open_positions_for_symbol(db, base) > 0` y `validate_trading_decision(...,
position_exists=...)` bloquea (`trading_invariants_week5.validate_sell_position_exists`) si no hay
posición. Como el bot no tiene posiciones propias y NO debe vender los holdings manuales de Carlos,
todas las SELL fallan. Para operar en mercado bajista hay que permitir cortos en margen.

**Diseño (contenido y reversible):**
1. **Flag global, OFF por defecto.** Añade `def shorting_enabled() -> bool` que lea env `ALLOW_SHORTING`
   (usa el patrón `_bool_env` existente; default False). Ponlo en un módulo de config/guards
   (p.ej. `app/services/risk_guard.py` o `app/services/system_core_trade_guards.py`).
2. **Bypass SOLO margin-short.** En TODOS los puntos donde se calcula `position_exists` para una SELL
   antes de `validate_trading_decision` (busca `position_exists` en `signal_monitor.py`; hay al menos el
   de ~8511, revisa si hay más rutas SELL), añade:
   ```python
   # Shorting: si está habilitado y la moneda opera en margen, una SELL sin posición abre un corto.
   # Las ventas SPOT siguen requiriendo posición (no vender holdings manuales).
   if (not position_exists) and user_wants_margin and shorting_enabled():
       position_exists = True  # permitir corto en margen
   ```
   (`user_wants_margin = getattr(watchlist_item, 'trade_on_margin', False)` ya está disponible ahí.)
3. **No toques** la invariante en sí (`validate_sell_position_exists`), ni el risk guard, ni el cap de
   apalancamiento, ni el guardrail de posiciones — todos siguen aplicando al corto.
4. **Activación (paso ops deliberado):** pon `ALLOW_SHORTING=true` en el entorno del backend-aws
   (compose/SSM env del servicio), de forma que sea un cambio explícito y se pueda revertir a `false`.

**Restricciones:** spot SELL sin posición sigue bloqueado (protege bags manuales). Default OFF = cero
cambio de comportamiento. No toques live gate / equity / #107 / bucle de trading.

**Tests** (`backend/tests/test_shorting_flag.py`):
- `ALLOW_SHORTING` no seteado + SELL margin sin posición → BLOQUEADO (comportamiento actual).
- `ALLOW_SHORTING=true` + SELL **margin** sin posición → permitido (position_exists=True).
- `ALLOW_SHORTING=true` + SELL **spot** (trade_on_margin=False) sin posición → BLOQUEADO.
- SELL con posición existente → permitido (sin cambios).

**Entrega:** rama `feat/enable-margin-shorting`, PR contra `main`, NO auto-merge. Pega el link.

**Validación por fases (kill switch a mano):**
1. Merge + deploy con `ALLOW_SHORTING` AÚN sin poner (o false) → confirma que nada cambia.
2. Pon `ALLOW_SHORTING=true` en el env + restart. Confirma en logs `shorting_enabled=True`.
3. Espera UNA señal SELL de una moneda margin ($10) y confirma en Crypto.com un **corto real** abierto
   (posición negativa / margin sell con ID numérico). Vigila 15-30 min: ≤3 posiciones, margen sano,
   `is_liquidating=False`.
4. Si algo raro → `ALLOW_SHORTING=false` + restart (apaga cortos al instante) y/o kill switch.

**Rollback:** `ALLOW_SHORTING=false` (apaga la feature sin revert) o revert del commit.
