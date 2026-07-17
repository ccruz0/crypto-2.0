# Telegram Noise Audit — 2026-07-17

Evidence-based audit of ATP Telegram notifications and permanent root-cause fixes.

## Evidence source

Production API (read-only):

`GET https://dashboard.hilovivo.com/api/monitoring/telegram-messages`

Snapshot analyzed: **500 messages** spanning **2026-07-17 06:04–06:37 UTC** (~34 minutes).  
API `total=500` (endpoint capped); this is a high-rate window, not a quiet period.

### Actually sent to Telegram (`blocked=false`)

| Count | Category | Classification |
|------:|----------|----------------|
| 86 | `SHORT TP NOT WIDENED` (ETH_USD / ETH_USDT) | **Loop / Noise** |
| 45 | `AUTOMATIC ORDER CREATION FAILED` — Amount USD missing (ETH_USD) | **Loop / Bug** |
| 16 | `SL/TP ORDERS CREATED` — same SL order IDs re-announced | **Duplicate / Loop** |
| 2 | `TRADE BLOCKED` — MAX_OPEN_ORDERS_TOTAL | **Warning** (cooldown working) |

### Persisted but not sent (`blocked=true`)

| Count | Category | Notes |
|------:|----------|-------|
| 198 | `BLOQUEADO` throttle gates | Monitor noise only; not Telegram |
| 153 | `TRADE BLOCKED` (suppressed) | Guardrail cooldown working |

## Root causes

### 1. SHORT TP NOT WIDENED loop

- **Code:** `backend/app/services/tp_sl_order_creator.py` → `create_take_profit_order`
- **Why:** Short TP target already past market; code correctly refuses to widen TP, but notified on every retry.
- **Why it repeated:** Exchange sync / SL-TP backfill retries every few seconds while SL exists and TP is missing (`half_protected_backfill`).
- **Fix:** Once-per-parent Telegram claim (24h) + `tp_unreachable:{parent}` claim so sync stops retrying TP creation for that parent.

### 2. SL/TP ORDERS CREATED duplicates

- **Code:** `backend/app/services/exchange_sync.py` → `_create_sl_tp_for_filled_order`
- **Evidence:** Same entry + SL order IDs (e.g. ETH_USD entry `5755600491780783859` / SL `73817490101973981`) re-notified ~every 5–6 minutes; TP always `None`.
- **Why:** `already_protected` required *both* SL and TP. With SL present and TP unreachable, code reused SL, failed TP, and re-sent “SL/TP ORDERS CREATED”. In-memory 5-minute guard expired and spam continued.
- **Fix:** Track `sl_newly_created` / `tp_newly_created`; skip Telegram when nothing new was created; treat SL + unreachable-TP as idempotent; DB claim `sl_tp_created:{order_id}`.

### 3. AUTOMATIC ORDER CREATION FAILED (Amount USD)

- **Code:** `backend/app/services/signal_monitor.py`
- **Why:** `trade_enabled=True` but `trade_amount_usd` unset for ETH_USD; every ~30s signal cycle re-paged Telegram with identical config error.
- **Fix:** Once-per-symbol claim (`config_fail:amount_usd_missing:{symbol}`, 6h). Same pattern for authentication failures.

## Intentional / preserved

- BUY/SELL signals, order executed, daily summaries, orphan checks, system-down ops alerts.
- `HostSwapHigh` / Alertmanager critical path — **not changed** (true positive; warning severity already routes to null).
- Signal Monitor architecture from PR #62 — **not revisited**.
- TRADE BLOCKED for MAX_OPEN_ORDERS — still notifies once per cooldown (actionable).

## Call graph (production senders)

See investigation notes in PR body. Primary layers:

1. `telegram_notifier.send_message` — trading / ops
2. `send_claw_message` — ATP Control / agent
3. `send_command_response` — interactive commands
4. Alertmanager → `telegram-alerts` container
5. Jarvis mission / investigation Telegram

## Validation

- Unit tests: `tests/test_telegram_event_dedup.py`, `tests/test_sl_tp_telegram_dedup.py`, `tests/test_trade_block_telegram_suppression.py` (14 passed in agent environment).
- Production deploy: **not performed** (requires human approval per CLAUDE.md).

## Remaining recommendations

1. Set `Amount USD` for ETH_USD (or disable `trade_enabled`) so the underlying config failure is resolved, not only deduped.
2. For short positions already through TP target: decide operator action (manual close vs wait for pullback) — SL remains; TP intentionally absent.
3. After deploy: re-query `/api/monitoring/telegram-messages` for 30–60 minutes and confirm SHORT TP / Amount USD / SL-TP created rates collapse.
4. Consider raising the monitoring API limit above 500 for full 24h inventories.
