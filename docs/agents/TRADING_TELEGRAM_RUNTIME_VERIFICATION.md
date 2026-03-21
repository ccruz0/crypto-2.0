# Trading Telegram Routing — Runtime Verification

**Goal:** Confirm production sends trading alerts to ATP Alerts (chat_id `-1003820753438`).

---

## 1. Runtime Config Status

### Config sources (load order)

Docker Compose `backend-aws` and `market-updater-aws` load env in this order (later overrides):

| Order | File | Purpose |
|-------|------|---------|
| 1 | `.env` | Base |
| 2 | `.env.aws` | AWS overrides |
| 3 | `./secrets/runtime.env` | Secrets (Telegram, API keys) |

**Trading chat_id resolution (AWS path):**

```
TELEGRAM_CHAT_ID_TRADING  (primary)
    ↓ if not set
TELEGRAM_CHAT_ID_AWS      (fallback)
    ↓ if not set
TELEGRAM_CHAT_ID          (fallback)
```

### Stale override risk

If `TELEGRAM_CHAT_ID_TRADING` is **not set**, the backend uses `TELEGRAM_CHAT_ID_AWS` or `TELEGRAM_CHAT_ID`, which may still point to the old HILOVIVO3.0 channel.

---

## 2. Effective Trading Chat ID at Send Time

**Variable used:** `self._chat_id_trading or self.chat_id`

- `_chat_id_trading` = resolved from `TELEGRAM_CHAT_ID_TRADING` (or fallbacks) in `refresh_config()`
- `chat_id` = same value stored as `required_chat_id` for the enabled check

**Code path:** `telegram_notifier.py` lines 279–293 (AWS), 484 (send_message)

---

## 3. Code Path for Trading Alerts

| Step | File | Function | chat_destination |
|------|------|----------|------------------|
| 1 | `signal_monitor.py` | BUY/SELL signal → `emit_alert()` | — |
| 2 | `alert_emitter.py` | `emit_alert()` → `telegram_notifier.send_buy_signal()` / `send_sell_signal()` | — |
| 3 | `telegram_notifier.py` | `send_buy_signal()` / `send_sell_signal()` → `send_message(..., chat_destination="trading")` | `"trading"` |
| 4 | `telegram_notifier.py` | `send_message()` → `refresh_config()` → `effective_chat_id = _chat_id_trading or chat_id` | — |
| 5 | `telegram_notifier.py` | `http_post(url, json={"chat_id": effective_chat_id, ...})` | — |

**Other trading alert callers (all use default `chat_destination="trading"`):**

- `send_order_created()` — order created
- `send_executed_order()` — order filled
- `send_daily_summary()` — daily report
- `buy_index_monitor.send_buy_index()` — BTC index
- SL/TP alerts from `signal_monitor`, `sl_tp_checker`, `tp_sl_order_creator`

---

## 4. Verification Script

Run on EC2 (inside backend container):

```bash
# Config check only
docker compose --profile aws exec backend-aws python scripts/verify_trading_telegram_routing.py

# Config check + send test message to ATP Alerts
docker compose --profile aws exec backend-aws python scripts/verify_trading_telegram_routing.py --send-test
```

**Expected output when correct:**

```
3. EFFECTIVE TRADING CHAT ID (used at send time)
   _chat_id_trading  = -1003820753438
   effective_chat_id = -1003820753438

4. ATP ALERTS CHECK
   ✅ MATCH: Trading alerts route to ATP Alerts (-1003820753438)
```

---

## 5. Exact Next Step to Align Production

If the script reports a mismatch or missing chat_id:

1. **Set the env var on EC2:**

   ```bash
   # Add or update in secrets/runtime.env (and optionally .env.aws)
   echo 'TELEGRAM_CHAT_ID_TRADING=-1003820753438' >> secrets/runtime.env
   ```

2. **Restart services so they pick up the new env:**

   ```bash
   docker compose --profile aws restart backend-aws market-updater-aws
   ```

3. **Re-run verification:**

   ```bash
   docker compose --profile aws exec backend-aws python scripts/verify_trading_telegram_routing.py --send-test
   ```

4. **Confirm in ATP Alerts:** You should see the `[TEST] Trading routing verification — ATP Alerts` message.

---

## 6. Files Involved

| File | Role |
|------|------|
| `backend/app/services/telegram_notifier.py` | `refresh_config()`, `send_message()`, routing logic |
| `backend/app/core/config.py` | `TELEGRAM_CHAT_ID_TRADING` in Settings |
| `backend/app/services/alert_emitter.py` | `emit_alert()` → `send_buy_signal` / `send_sell_signal` |
| `backend/app/services/signal_monitor.py` | BUY/SELL signals, order alerts |
| `docker-compose.yml` | `env_file` for backend-aws, market-updater-aws |
| `secrets/runtime.env` | Runtime secrets (must contain `TELEGRAM_CHAT_ID_TRADING`) |
| `.env.aws` | AWS overrides |
| `backend/scripts/verify_trading_telegram_routing.py` | Runtime verification script |

---

## 7. Diagnostic Endpoint (No Chat ID)

`GET /api/diagnostics/telegram-notifier` returns `enabled`, `block_reasons`, etc., but **not** the actual chat_id (for security). Use the verification script for full routing details.
