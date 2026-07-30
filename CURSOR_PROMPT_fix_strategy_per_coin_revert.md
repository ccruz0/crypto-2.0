# Prompt Cursor — la estrategia por-moneda revierte a default (resolución)

Copia en Cursor, repo `crypto-2.0`.

---

Trabaja en `ccruz0/crypto-2.0`. Objetivo (aprobado por Carlos): que la estrategia por-moneda elegida en
el dashboard se respete y deje de "revertir" a swing-conservative a los pocos minutos.

**Causa raíz (confirmada):** la estrategia por-moneda SÍ se guarda en `trading_config.json` bajo `coins`,
pero `resolve_strategy_profile()` en `backend/app/services/strategy_profiles.py` (~línea 103) la ignora:

1. **Approach forzado desde el watchlist** (líneas ~120-124):
   ```python
   if watchlist_item is not None:
       approach = _normalize_approach(getattr(watchlist_item, "sl_tp_mode", None))
   ```
   y luego `if approach is None: approach = preset_approach` — así el sufijo de riesgo del preset del
   usuario (p.ej. `swing-aggressive`) se descarta y "Agresiva" se resuelve como "Conservadora".

2. **Match de símbolo incompleto** (~línea 130):
   ```python
   coin_cfg = coins_cfg.get(symbol_key) or coins_cfg.get(symbol_key.replace("_USDT", "_USD")) or {}
   ```
   solo prueba `_USDT→_USD`. Si el preset está guardado bajo la otra variante → `coin_cfg={}` → cae al
   default `SWING/CONSERVATIVE` (~172-179) → se pierde toda la estrategia.

El poll del dashboard (`getTopCoins`, cada ~3 min, `GET /market/top-coins-data`) re-resuelve con esto y
re-inyecta el default (`routes_market.py:1161`), y la UI prioriza ese `strategy_key`
(`WatchlistTab.tsx` `getCoinStrategy` PRIORITY 1). Además, como el BOT usa la misma resolución, opera con
el default, no con lo elegido. **No es solo cosmético.**

**Cambio (solo `backend/app/services/strategy_profiles.py`, función `resolve_strategy_profile`):**
1. Resolver primero el preset por-moneda (strategy + approach) desde `coins[symbol].preset`. Normaliza el
   símbolo en AMBOS sentidos para el lookup: prueba `symbol_key`, `_USDT→_USD` y `_USD→_USDT`.
2. Usar el `approach` del **preset** cuando el preset trae sufijo de riesgo explícito
   (`swing-aggressive`, `scalp-aggressive`, etc.). Usar `watchlist_item.sl_tp_mode` **solo como fallback**
   cuando el preset no trae approach. (Invierte la precedencia actual, alineado con el comentario del
   propio código "dashboard is the source of truth").
3. Mantener el fallback final a `(SWING, CONSERVATIVE)` solo si de verdad no hay preset ni señal.
4. Actualiza el docstring de "Priority" para reflejar: preset por-moneda primero, watchlist como fallback.

**Restricciones:** no cambies el poll del frontend ni `config_loader`. No toques el live gate / equity /
guardrail / bucle de trading. Solo la resolución.

**Tests** (`backend/tests/test_resolve_strategy_profile.py`):
- Preset `swing-aggressive` en config → resuelve (SWING, AGGRESSIVE) aunque `watchlist.sl_tp_mode`="conservative".
- Preset `scalp-aggressive` bajo `DOT_USD` con symbol pedido `DOT_USDT` → resuelve (SCALP, AGGRESSIVE) (match de variante).
- Preset sin sufijo (`swing`) + `sl_tp_mode`="aggressive" → approach = AGGRESSIVE (fallback al watchlist).
- Sin preset ni señal → (SWING, CONSERVATIVE).

**Validación esperada:** cambiar una moneda a "Scalp Agresiva", guardar, esperar el poll (~3 min) → la UI
mantiene "Scalp Agresiva" (ya no revierte), y `GET /market/top-coins-data` devuelve el `strategy_key`
correcto.

**Entrega:** rama `fix/strategy-profile-respect-per-coin-preset`, PR contra `main`, NO auto-merge. Pega el link.
**Rollback:** revert → vuelve al comportamiento actual (revierte a default).
