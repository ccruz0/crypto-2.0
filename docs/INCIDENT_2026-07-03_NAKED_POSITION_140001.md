# Incident 2026-07-03 — Naked (unprotected) positions from Crypto.com 140001

**Severity:** High (real money). **Symbol observed:** `DOT_USD` (short entries).
**Symptom:** The bot opened entries, but SL/TP creation failed with Crypto.com error
`140001` (`EXCHANGE_API_DISABLED`), leaving **NAKED positions with no stop-loss**.

Production log signature:

```
SLTP_140001 instrument_name=DOT_USD order_type=STOP_LIMIT/TAKE_PROFIT_LIMIT ... note=Likely permission or env mismatch
```

This document has two parts:

1. **Account/config remediation** — operator action to re-enable conditional orders
   (the true root cause; no code change fixes it).
2. **Code safety guard** — what changed in the code so a naked position is never left
   again even if 140001 recurs.

---

## 1. Root cause

`140001 = EXCHANGE_API_DISABLED`. It means **conditional / trigger orders are disabled
at the account or API-key level**. SL/TP are placed as `STOP_LIMIT` and
`TAKE_PROFIT_LIMIT` (conditional) orders via `private/create-order`, so when conditional
orders are disabled the exchange rejects them with `140001` while plain `MARKET` / `LIMIT`
entries still succeed. The result: the entry fills, protection is rejected, position is naked.

Code references:
- Error-code constant and classification: `backend/app/core/exchange_formatting_week6.py:19`
  (`EXCHANGE_CODE_API_DISABLED = 140001`), `:152` (`classify_exchange_error_code`).
- `140001` is **non-retryable**: `backend/app/core/retry_circuit_week5.py:37`.
- Operator checklist helper: `operator_action_for_api_disabled()` in
  `backend/app/core/exchange_formatting_week6.py:167`.
- Broker 140001 handling: `backend/app/services/brokers/crypto_com_trade.py`
  (`place_stop_loss_order` ~`:5459`, `place_take_profit_order` ~`:5987`).
- Existing formatting/creation reference: `docs/CRYPTOCOM_SL_TP_CREATION.md` (§ "Error 140001").

**No amount of code change fixes 140001** — the account/API key must be enabled for
conditional orders. The code change below only guarantees we never leave a naked position
while that condition exists.

---

## 2. Operator remediation (account / config — NOT code)

Do these in order. Steps 1–5 are on the Crypto.com Exchange side; steps 6–7 verify.

1. **Enable conditional / trigger orders for the API key.**
   In the Crypto.com Exchange account → API Keys, confirm the key used by production has
   **trading enabled** and, specifically, permission to place **conditional / advanced /
   trigger orders** (`STOP_LIMIT`, `TAKE_PROFIT_LIMIT`). Some accounts gate advanced order
   types separately from basic spot trading.

2. **Enable derivatives / margin trading permission** (required for shorts).
   The incident was a **short** (`DOT_USD`), which requires margin/derivatives. Confirm the
   account and API key are enabled for **margin/derivatives trading**, not just spot. A key
   that can open a margin short but cannot place conditional orders is exactly the 140001 trap.

3. **Verify the IP allowlist.**
   Confirm the production host's **egress IP** (AWS `t3.small`, `ap-southeast-1`) is on the
   API key's IP allowlist. A blocked or stale IP can surface as permission errors. (Note: the
   distinct auth failure `40101` is "egress IP not allowlisted" — see
   `AUTH_40101_MESSAGE` in `app/core/crypto_com_guardrail.py`. If you see 40101, fix the IP
   allowlist first, then re-check 140001.)

4. **Check sub-account permissions.**
   If trading runs under a **sub-account**, verify the sub-account itself (not only the
   master) has conditional-order and margin permissions, and that the API key is bound to the
   correct sub-account.

5. **Confirm prod vs sandbox base host.**
   Production must use `https://api.crypto.com/exchange/v1`. A key issued for **UAT/sandbox**
   used against prod (or vice-versa) presents as a permission/env mismatch. The 140001 log
   line includes `api_env_hint` and `base_host` (see `_classify_140001_context`,
   `crypto_com_trade.py:88`) — confirm `api_env_hint=prod` and `base_host=api.crypto.com`.
   The env var driving this is the broker base URL (do **not** print secrets when checking).

6. **Validate with the probe tool (read-mostly, single instrument).**
   Once the above are changed, confirm conditional orders are accepted using the existing
   probe. Run it on the production host (it sends REAL authenticated requests; it uses a
   **far-from-market** trigger and `--dry-run` cancels any order it manages to place):

   ```bash
   # From the backend/ directory on the production host, with prod API env loaded.
   # BUY-side conditional probe on a liquid instrument, capped to a few variants, self-cleaning.
   python -m app.tools.crypto_com_trigger_probe \
     --instrument DOT_USD \
     --side BUY \
     --qty 0.1 \
     --ref-price 1.00 \
     --max-variants 20 \
     --dry-run
   ```

   **Expected PASS (conditional orders ENABLED):** at least one variant is accepted — the
   JSONL log (`/tmp/crypto_trigger_probe_<correlation_id>.jsonl`) contains an attempt with
   `http_status=200` and a returned `order_id`, and (with `--dry-run`) a recorded
   `cancel_result`. The printed summary's `grouped_keys` shows a `code: 0` (success) group,
   and **no** group with `code: 140001`.

   **Still FAILING (conditional orders DISABLED):** every attempt is grouped under
   `code: 140001` / `message: API_DISABLED` — the account/API is still not enabled; revisit
   steps 1–5. `--ref-price` should be set well away from the market so nothing can actually
   fill; adjust `--instrument`/`--ref-price` to the coin you are validating.

7. **Confirm the circuit breaker resets and entries resume.**
   After a successful probe, the code's conditional-orders circuit breaker (tripped on the
   first 140001 — see §3) will auto-clear on its next check window, or on the next successful
   SL/TP creation. Watch prod logs for `CONDITIONAL_ORDERS_DISABLED` to disappear and for a
   normal `SLTP_ATTEMPT` → SL/TP created sequence on the next entry.

> **Guardrails:** per `CLAUDE.md`, do not disable or change `HostSwapHigh`, do not touch the
> trading safety flags (`double_approval_required`, `github_write_enabled`,
> `pr_creation_enabled`, `patch_apply_enabled`), and do not enable LIVE as part of this fix.

---

## 3. Code safety guard (what changed)

The account fix above is necessary but not sufficient: the **first** 140001 (before the
breaker trips) and any race could still open a position. The code now makes the invariant
hard — **never leave an unprotected entry**.

### 3.1 Hard invariant: auto-close on protection failure (backstop)

`SignalMonitorService._create_protection_after_entry_fill(...)`
(`backend/app/services/signal_monitor.py`) is the **single choke point** that every entry
path (`_create_buy_order`, `_create_sell_order` short entry, and the orchestrator
`_place_order_from_signal`) funnels through to create SL/TP.

- **Why the old guards missed it:** `140001` is **returned** as an error in the SL/TP result
  dict (`sl_result`/`tp_result`), it is **not raised**. The pre-existing auto-close on the
  BUY path and the alert on the SELL path were `except`-only, so they never fired on 140001,
  and the orchestrator path only **logged** the failure → naked position.
- **New behaviour:** after SL/TP creation, the choke point checks
  `_protection_confirms_stop_loss(result)`. If a stop-loss was **not** actually created —
  whether the failure was a **returned error** (e.g. 140001) **or a raised exception** — the
  freshly-opened entry is **immediately flattened** with a market order:
  - long entry (`BUY`) → market **SELL** of the filled quantity;
  - short entry (`SELL`) → market **BUY** covering the position (`is_margin=True`).
- If the flatten itself fails, a `CRITICAL … AUTO-CLOSE FAILED … MANUAL INTERVENTION`
  Telegram alert is sent (it never raises).
- Dry-run entries (order id prefixed `dry`) are never flattened (no real position exists).

### 3.2 Pre-block: refuse new entries when conditional orders are known-disabled

- On the first observed 140001 during SL/TP creation, the choke point trips the broker
  circuit breaker via `trade_client._mark_conditional_orders_unavailable(...)`.
- Before placing any **new** entry that needs protection, `_place_order_from_signal` now
  calls `trade_client._check_conditional_orders_circuit_breaker()`; if conditional orders are
  known-disabled it **blocks the entry up front** and returns
  `{"error": "CONDITIONAL_ORDERS_DISABLED", "blocked": True, ...}` — so we stop opening
  positions we cannot protect until the account is fixed. The breaker auto-clears after its
  interval / on the next successful SL/TP creation.

### 3.3 Tests

`backend/tests/test_naked_position_guard.py` covers: SL-confirmation predicate, 140001
detection, long flatten (market SELL), short cover (market BUY, notional), no-flatten on
success, flatten on raised exception, dry-run skip, flatten-failure alerting, and the
up-front pre-block for both BUY and short entries (plus a positive control that a normal
entry proceeds when the breaker is clear).

### 3.4 Rollback

The change is confined to `backend/app/services/signal_monitor.py` (new guard methods + two
call-site hooks) and the new test file. Revert that commit to restore prior behaviour; no
schema, config, or infra changes are involved.
