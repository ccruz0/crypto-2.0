# ATP — Registro de hallazgos (sesión 2026-07-01)

Estado read-only salvo lo indicado. Ordenado por severidad.

| # | Hallazgo | Severidad | Estado | Próximo paso |
|---|----------|-----------|--------|--------------|
| 1 | **dry_market en LIVE**: en AWS `self.live_trading` se fija a False siempre; `actual_dry_run = dry_run or not self.live_trading` → toda orden se ejecuta simulada aunque la BD diga LIVE. No estás tradeando de verdad. | 🔴 Crítico | Causa raíz confirmada en código; falta confirmar runtime | Carlos ejecuta `whoami` + git log; luego fix por gates |
| 2 | **Trigger orders ERR_INTERNAL/50001**: endpoint legacy roto; ruido cada 5-6s. | 🟠 Media | Fix hecho + tests (commit 5080629) en rama `fix/deploy-backend-ssm-status-poll` | Merge a main + deploy + verificar |
| 3 | **Mensaje guardrail poco claro**: Telegram dice `system_core_one_active_trade_per_coin / GUARDRAIL_BLOCKED` en vez de "BTC ya tiene posición abierta". | 🟡 Baja (UX) | Diagnosticado | Preparar mapa reason_code→texto humano |
| 4 | **Max órdenes abiertas no configurable**: tope real vía env `SYSTEM_CORE_MAX_OPEN_TRADES=5` + `one_active_trade_per_coin` hardcode; no en la UI. | 🟡 Mejora | Diagnosticado | Añadir campo config + cablear guardrail |
| 5 | **Label config engañoso**: "Max Orders Per Symbol / Day" es realmente por símbolo/día (throttle), no el tope total de abiertas. | 🟡 Baja (UX) | Diagnosticado | Añadir "Max Open Orders (total)" separado |
| 6 | **Persistencia config por preset**: modal parametrizado por preset/riskMode, pero guardado "depende del padre" → posible hueco para presets != swing-conservative. | 🟠 Media | Sospecha, sin confirmar | Revisar componente padre + endpoint save |
| 7 | **Notificación no etiqueta dry-run**: el notifier sabe poner 🧪 (DRY RUN) pero la orden salió sin etiqueta. | 🟡 Baja | Diagnosticado | Pasar flag real al notifier (parte del #1) |
| 8 | **Conteo órdenes BTC 4 vs 5** (open_orders_count por-activo vs total). | 🟡 Baja | Diagnosticado al inicio | Revisar tras fix #2 |

## Detección que falta en el análisis diario (Jarvis)
Grep en `jarvis/**` → **cero** detección de: dry_market en LIVE (#1), señales bloqueadas por guardrail (#3). El análisis de las 22:00 no los surface. Recomendado añadir ambos como checks read-only.

## Prioridad recomendada
1. **#1 (crítico, dinero real)** — confirmar runtime primero, no tocar sin gates.
2. **#2** — merge + deploy (ya listo).
3. **#3, #5** — UX rápidos, bajo riesgo.
4. **#4, #6** — cambios de config, tamaño medio.
