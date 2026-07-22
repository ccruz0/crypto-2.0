# Alert quality evaluation + Auto strategy — Phase 1 design

**Fecha:** 2026-07-22  
**Estado:** DISEÑO APROBADO (Phase 1) — sin implementación en prod  
**Branch:** `docs/alert-quality-eval-phase1-design`  
**Canvas:** `~/.cursor/projects/home-ubuntu-crypto-2-0/canvases/alert-quality-eval-phase1.canvas.tsx`

---

## 1. Objetivo

1. **Evaluar** si las alertas BUY/SELL capturan tendencia *a posteriori* (calidad de señal, no solo “se envió”).
2. **Más adelante (Phase 2+):** aprender parámetros de eficacia bajo **aprobación humana**.
3. **Preset `auto`:** parámetros **visibles**, **no editables** manualmente; solo actualizables vía cola de aprobación.

**No hacer en Phase 1:** mutar `trading_config` en prod, reasignar monedas a Auto, tocar `HostSwapHigh`, desplegar, ni writes autónomos.

---

## 2. Mapa del pipeline existente

```
market_updater
  → OHLCV efímero + indicadores → market_prices / market_data (snapshot)
  → sync_watchlist_to_signals → trade_signals

backend (RUN_SIGNAL_MONITOR=true)
  → SignalMonitorService (30s)
  → signal_evaluator / trading_signals vs strategy_rules
  → throttle → emit_alert → Telegram + telegram_messages
  → (si trade_enabled) order_intents → exchange_orders / order_history
```

| Pieza | Ruta |
|-------|------|
| Market worker | `backend/market_updater.py` |
| Escritura señales | `backend/app/services/signal_writer.py` |
| Monitor | `backend/app/services/signal_monitor.py` |
| Eval canónica | `backend/app/services/signal_evaluator.py` |
| Reglas | `backend/app/services/trading_signals.py` |
| Alertas | `backend/app/services/alert_emitter.py`, `telegram_notifier.py` |
| Órdenes | `signal_order_orchestrator.py` |
| Presets | `backend/trading_config.json` (`strategy_rules`) |
| Resolución | `strategy_profiles.py` → `get_strategy_rules()` |
| UI Watchlist | `frontend/.../WatchlistTab.tsx` (`strategyOptions`) |
| UI reglas | `StrategyConfigModal.tsx` |

**Desacoplamiento útil para eval:** `alert_enabled*` controla alertas; `trade_enabled` controla órdenes. Una alerta puede existir con `order_skipped=true`.

**Presets actuales (UI):** `swing|intraday|scalp` × `conservative|aggressive`.  
**Swing Conservative** es el baseline más estricto (RSI 30/70, MAs, filtros de tendencia, ATR SL×1.5, TP rr 1.5).

---

## 3. Métricas Phase 1 (fórmulas)

Universo: filas `telegram_messages` con `blocked=false` (alerta enviada).  
Segmentar por `symbol × strategy_key × side`. Exigir **n ≥ 20** antes de rankear un segmento.

| ID | Métrica | Fórmula | Ventanas |
|----|---------|---------|----------|
| M1 | Trend hit @ T | BUY: `close_T > entry×(1+δ)`; SELL: `close_T < entry×(1−δ)` | T ∈ {15m, 1h, 4h}; δ default **0.5%** |
| M2 | Direction accuracy | `1` si `sign(return_T)` coincide con side | Mismos T |
| M3 | MFE / MAE | Máx. % favorable / adverso en `[t0, t0+H]` | H=4h (scalp: 1h) |
| M4 | TP before SL | `1` si toca TP antes que SL en horizonte; `0` / null si ninguno | SL/TP del preset al emitir |
| M5 | Expectancy proxy | `hit_rate×avg_MFE − miss_rate×avg_MAE` (solo alerta) | Por segmento |
| M6 | Alert→fill | fills / alertas enviadas (ops) | No es calidad de tendencia |
| M7 | Composite score | `0.35·dir_1h + 0.25·trend_4h + 0.25·tp_before_sl + 0.15·clip(MFE−MAE)` | Términos en [0,1] |

**Scorecard rollups:** por segmento (n, dir@1h, trend@4h, TP&lt;SL, median MFE/MAE, composite); global (top/bottom symbols, BUY vs SELL, comparación de presets).

**Entry price:** preferir `context_json` / precio en mensaje; fallback `trade_signals.entry_price` / `order_history.avg_price` si hay fill.

---

## 4. Fuentes de datos

### Ya disponibles

| Store | Uso |
|-------|-----|
| `telegram_messages` | Evento de alerta; **PK de evaluación** (`id`, `correlation_id`, `symbol`, `timestamp`, `context_json`) |
| `order_intents` | `signal_id` → `telegram_messages.id` |
| `order_history` / `exchange_orders` | Outcomes de fill (camino PnL opcional) |
| `trade_signals` | Snapshot preset / indicadores / entry |
| `watchlist_signal_state` | Última eval (no histórico de outcomes) |

### Limitación crítica

`market_data` / `market_prices` son **solo snapshot**. No hay tabla de velas. Para retornos forward, Phase 1 **re-fetch** OHLCV público (Binance/Crypto.com) en el momento del label.

### Tablas propuestas

**`alert_outcomes`** (Phase 1b / PR-C) — una fila por alerta etiquetada:

- `telegram_message_id` (unique)
- `symbol`, `side`, `strategy_key`, `param_version`
- `entry_price`, `entry_ts`
- `ret_15m`, `ret_1h`, `ret_4h`
- `trend_hit_15m/1h/4h`, `dir_acc_*`
- `mfe_pct`, `mae_pct`, `horizon_h`
- `tp_before_sl` (bool/null), `tp_price`, `sl_price`
- `composite_score`, `labeled_at`, `candle_source`

**`strategy_param_versions`** (Phase 2) — versiones de Auto:

- `preset_key` (`auto`), `version`, `rules_json`
- `approval_task_id`, `applied_at`, `superseded_by`, `rollback_of`

Jarvis `signal_performance_analysis.py` genera propuestas offline en docs; **no** es el pipeline de métricas de producción — reutilizar ideas, no acoplar runtime.

---

## 5. Diseño preset `auto`

### Schema (sketch)

```json
"strategy_rules": {
  "auto": {
    "notificationProfile": "swing",
    "locked": true,
    "seed_from": "swing-conservative",
    "param_version": 1,
    "rules": {
      "Learned": { /* StrategyRules — same shape as Conservative */ }
    }
  }
}
```

- Extender `StrategyType` con `AUTO = "auto"`.
- Semilla inicial = copia de **swing-conservative**.
- Una sola banda de riesgo (`Learned`) al inicio (evitar conservative/aggressive en Auto).

### Reglas UX

| Regla | Comportamiento |
|-------|----------------|
| Seleccionable | Dropdown Watchlist: opción **Auto (aprendida)** |
| Visible | UI muestra RSI, MA, SL/TP, filtros, cooldown, `param_version` |
| No editable | Inputs deshabilitados; `PUT /api/config` rechaza mutaciones a `strategy_rules.auto.*` |
| Asignación de moneda | Usuario puede poner `coins.{SYM}.preset = "auto"` |
| Overrides | Sin overrides manuales de reglas para monedas Auto |
| Updates | Solo vía Approval Center → apply + bump `param_version` |

### Diferencia vs swing/scalp conservative

| | Swing/Scalp Cons. | Auto |
|--|-------------------|------|
| Quién edita reglas | Humano (Strategy Config) | Solo learning + aprobación |
| Risk modes | Conservative / Aggressive | Learned (único) |
| Origen | Estático en JSON | Versionado + seed |
| UI | Editable | Read-only badge “locked” |

---

## 6. Learning loop (Phase 2+ — sketch)

```
Scorecard → Propose Δparams (bounded) → Approval Center → Apply + version → Monitor → Rollback
```

**Knobs tunables (acotados):** `rsi.buyBelow/sellAbove`, `volumeMinRatio`, `minPriceChangePct`, `alertCooldownMinutes`, `sl.atrMult` / `tp.rr`, flags de `trendFilters` / `rsiConfirmation` / `candleConfirmation`.

**Gate:** mismas flags ACW (`double_approval_required`; no apply autónomo a prod). Propuesta incluye scorecard before/after en ventana holdout.

**Rollback:** restaurar `param_version-1` desde `strategy_param_versions`; reload de config.

---

## 7. Secuencia de PRs (pequeños)

| PR | Scope | Riesgo |
|----|-------|--------|
| **PR-A (recomendado primero)** | Script offline `scripts/eval_alert_quality.py` + scorecard JSON/MD en `docs/analysis/` | Ninguno en runtime |
| PR-B | `GET /api/analytics/alert-scorecard` read-only (sirve último artefacto) | Solo lectura |
| PR-C | Migración `alert_outcomes` + labeler batch (LAB primero) | Write DB LAB |
| PR-D | Scaffolding preset `auto` (schema + UI locked + reject edits); **no** reasignar monedas en prod | Superficie config |

**No merge/deploy sin aprobación humana.**

---

## 8. Root cause / scope / validation / risk / rollback (para futuros PRs)

- **Root cause (producto):** no hay etiquetado sistemático post-alerta; `market_data` no guarda trayectoria.
- **Scope Phase 1 implementación:** métricas + artefacto offline; opcional API read-only.
- **Validation:** scorecard reproducible sobre ventana fija de `telegram_messages` + OHLCV público; n y fórmulas documentadas.
- **Risk:** bajo si PR-A; medio si PR-D toca UI/config sin gate de escritura a Auto.
- **Rollback:** borrar artefacto / revertir PR; Auto no aplicado a monedas live hasta decisión explícita.

---

## 9. Resumen para operadores (ES)

Queremos medir si las alertas BUY/SELL aciertan la tendencia después (15m / 1h / 4h, MFE/MAE, TP antes que SL) y, más adelante, ajustar un preset **Auto** con parámetros visibles pero bloqueados, solo cambiables con tu aprobación.

Hoy el cuello de botella de datos es que **no guardamos velas** — solo el último snapshot. Phase 1 empieza con un **script offline** que relee alertas de Telegram y vuelve a pedir OHLCV para armar el scorecard. El primer PR debe ser ese script + informe; nada de tocar presets en producción todavía.
