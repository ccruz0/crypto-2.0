# 🔴 CONFIRMADA — el bucle automático no ejecuta real en AWS (dinero real) — PENDIENTE DE APROBACIÓN

**Evidencia final (2026-07-01):**
- Logs backend-aws: SELL automáticas hoy en DRY (DOT 15:34, ETH 15:35 ×2), no persistidas.
- Carlos confirma: las órdenes reales de la BD (IDs numéricas) las ejecutó **él a mano, directamente
  en Crypto.com**; ATP solo las sincronizó. Ninguna hoy.
- Conclusión: **el bucle automático de ATP simula todas sus órdenes en AWS** (`dry`) y las notifica en
  Telegram como "ORDER CREATED" sin ejecutar. La estrategia está inerte.

Mecanismo confirmado: el caller pasa `dry_run=False` (de la BD LIVE), pero
`actual_dry_run = dry_run or not self.live_trading` con `self.live_trading=False` en el contexto del
monitor de señales en AWS → siempre dry.

**NOTA:** una revisión previa marcó esto como "descartado" al ver 16 órdenes "reales" en la BD; se
descubrió después que eran manuales. Diagnóstico reactivado y confirmado.

---

# 🔴 PROPUESTA CRÍTICA — live gate en AWS (dinero real) — PENDIENTE DE APROBACIÓN

**NO aplicada. NO push. NO deploy.** Enciende ejecución con dinero real: requiere tu OK explícito +
Gate 1 (parche+tests) + Gate 2 (PR/deploy), y verificación con orden mínima.

## Causa raíz (confirmada en código)
- Caller (`signal_monitor.py:7106`): `dry_run_mode = not get_live_trading_status(db)` → pasa `dry_run=False` cuando la BD está en LIVE. Correcto.
- Broker (`crypto_com_trade.py`, 5 funciones de orden): `actual_dry_run = dry_run or not self.live_trading`.
- `_refresh_runtime_flags()` (línea ~210) en AWS fija `self.live_trading = False` **siempre**, y se ejecuta al inicio de cada orden. Docstring: *"In production (AWS) LIVE_TRADING is never read from env; callers must pass dry_run from get_live_trading(db)."*
- Resultado: `not self.live_trading` = True en AWS → `actual_dry_run` = True → **toda orden automática es simulada** (`dry_market_*`), ignorando el flag LIVE de la BD.
- Introducido: 2026-02-09, commit `53524b9`.

El término `or not self.live_trading` **contradice el propio docstring** (que dice que el caller manda vía `dry_run`). Ese término es el bug.

## Opción de fix recomendada (mínima, alineada con el docstring)
En AWS, que `dry_run` del caller sea autoritativo — no anularlo con `self.live_trading`:

```python
# En cada una de las 5 funciones de orden, sustituir:
actual_dry_run = dry_run or not self.live_trading
# por:
from app.core.runtime import is_aws_runtime
actual_dry_run = dry_run if is_aws_runtime() else (dry_run or not self.live_trading)
```

Alternativa (un solo punto): en `_refresh_runtime_flags`, en AWS fijar `self.live_trading` desde la
BD (`get_live_trading_status(db)`) en vez de `False`. Más limpio pero necesita sesión de BD en ese
método; hay que cablearla. Recomiendo la primera (más localizada y explícita).

Nota: el camino no-dry sigue pasando por `require_mutation_allowed_for_broker` /
`assert_exchange_mutation_allowed`, que quedan como segunda barrera. No se elimina ninguna protección
salvo el override erróneo.

## ⚠️ PRECONDICIONES antes de encender (obligatorias)
Esto pasa el sistema a operar con tu dinero. Antes del deploy, confirma:
1. **Límites conservadores** (ya configurables tras PR #103): `maxOpenOrdersTotal`, `maxOpenOrdersPerCoin`, y `SYSTEM_CORE_MAX_TRADE_USD` (default 1000 — ¿es el que quieres?).
2. **Kill switch** operativo y probado (`kill_switch_on`).
3. **Guardrails ON** (`SYSTEM_CORE_GUARDS_ENABLED=true`).
4. Saber qué estrategias/monedas tienen `trade_enabled=true` (ahora mismo: ALGO, BTC_USD, DGB, DOT, ETH_USDT).

## Plan de validación (staged, con red)
1. Merge por Gate 2, deploy a AWS.
2. Confirmar `whoami` / logs: `actual_dry_run=False` en el próximo intento.
3. **Orden de prueba mínima** en 1 moneda de bajo importe (o reducir `SYSTEM_CORE_MAX_TRADE_USD` temporalmente) y confirmar que aparece una orden **real** en el exchange (id numérico, no `dry_`).
4. Vigilar 15-30 min con el kill switch a mano.
5. Si algo raro → kill switch + rollback (revertir el commit → vuelve a dry).

## Rollback
Revertir el commit del fix → `actual_dry_run` vuelve a forzar dry en AWS. Sin dependencias nuevas.

## Gobernanza
Cambio de dinero real → Gate 1 + Gate 2 + `require_double_approval`. No lo aplico yo. Cuando confirmes
runtime y las precondiciones, preparo el prompt de Cursor / el patch para que lo ejecutes tú.
