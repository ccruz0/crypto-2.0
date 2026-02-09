# Week 6 Audit Report: TP/SL Creation Reliability on Crypto.com

**Goal:** Make TP/SL creation reliable; eliminate "Invalid price format" failures; handle API_DISABLED cleanly with clear operator action; add tests, evidence, and audit report.

---

## Checklist

| Item | Description | Status | Evidence |
|------|-------------|--------|----------|
| **1** | Robust formatting + validation for TP/SL (quantize to tick/step, no scientific notation, trigger_condition format) | PASS | [ops/evidence/week6_file_checks.txt](../ops/evidence/week6_file_checks.txt), [exchange_formatting_week6.py](../backend/app/core/exchange_formatting_week6.py) |
| **2** | On API_DISABLED (140001): decision=BLOCKED, reason_code=EXCHANGE_API_DISABLED, operator_action in log | PASS | crypto_com_trade.py (STOP_LIMIT ~4851–4879, TAKE_PROFIT_LIMIT ~5441–5468) |
| **3** | On Invalid price format (308): decision=FAILED, reason_code=INVALID_PRICE_FORMAT, pre_quantized/quantized in log (no secrets) | PASS | crypto_com_trade.py (STOP_LIMIT ~4691–4706, TAKE_PROFIT_LIMIT ~5434–5448) |
| **4** | Unit tests: formatting/quantization, trigger_condition, error classification (308, 140001) | PASS | [ops/evidence/week6_pytest.txt](../ops/evidence/week6_pytest.txt) (25 passed) |
| **5** | Docs: CRYPTOCOM_SL_TP_CREATION.md (order types, fields, rounding, debug 308/140001) | PASS | [docs/CRYPTOCOM_SL_TP_CREATION.md](CRYPTOCOM_SL_TP_CREATION.md) |
| **6** | 308 and 140001 classified non-retryable (retry/circuit) | PASS | retry_circuit_week5.py NON_RETRYABLE_EXCHANGE_CODES, is_exchange_code_retryable |

---

## File paths and line ranges

### Formatting layer
- **backend/app/core/exchange_formatting_week6.py**
  - `normalize_decimal_str`, `quantize_price`, `quantize_qty`, `validate_price_tick`, `validate_qty_step`, `format_trigger_condition`
  - `classify_exchange_error_code` (308 → INVALID_PRICE_FORMAT, 140001 → EXCHANGE_API_DISABLED)
  - `operator_action_for_api_disabled()` (operator checklist, no secrets)

### TP/SL payload building
- **backend/app/services/brokers/crypto_com_trade.py**
  - `place_stop_loss_order`: normalize_price, normalize_quantity, trigger_str (lines ~4131–4221); 308/140001 handling (~4691–4706, ~4851–4879)
  - `place_take_profit_order`: normalize_price, normalize_quantity, trigger_str (lines ~4950–5010); 308/140001 handling (~5434–5448, ~5441–5468)
  - `normalize_price`, `normalize_quantity`, `_get_instrument_metadata` (lines ~5601–5598, 5525–5598)
- **backend/app/services/tp_sl_order_creator.py**: `create_take_profit_order` / `create_stop_loss_order` call broker (276, 493)

### Error classification (retry/circuit)
- **backend/app/core/retry_circuit_week5.py**: `NON_RETRYABLE_EXCHANGE_CODES = {308, 140001}`, `is_exchange_code_retryable()`, `is_retryable_error(..., exchange_code=...)`

### Tests
- **backend/tests/test_exchange_formatting_week6.py**: normalize_decimal_str, quantize_price/qty, validate_*, format_trigger_condition, classify_exchange_error_code, operator_action
- **backend/tests/test_tp_sl_week6.py**: 308/140001 classification, non-retryable, is_retryable_error(exchange_code=...)

---

## Commands run (with cd)

```bash
# File evidence
cd /Users/carloscruz/automated-trading-platform
rg -n "tp_sl|trigger_condition|Invalid price format|API_DISABLED|Error 308|140001|place_.*order" backend/app > ops/evidence/week6_file_checks.txt

# Week 6 tests
cd /Users/carloscruz/automated-trading-platform/backend
python3 -m pytest tests/test_exchange_formatting_week6.py tests/test_tp_sl_week6.py -v | tee ../ops/evidence/week6_pytest.txt

# Git state
cd /Users/carloscruz/automated-trading-platform
( git rev-parse HEAD && git status --porcelain ) > ops/evidence/week6_git_state.txt
```

---

## Evidence files (relative from docs/)

| File | Description |
|------|-------------|
| [../ops/evidence/week6_file_checks.txt](../ops/evidence/week6_file_checks.txt) | File:line references for formatting, TP/SL payload, error handling, retry |
| [../ops/evidence/week6_pytest.txt](../ops/evidence/week6_pytest.txt) | Pytest run for Week 6 tests (25 passed) |
| [../ops/evidence/week6_diagnostics.txt](../ops/evidence/week6_diagnostics.txt) | Note: no new diagnostics script; pipeline diagnostics unchanged |
| [../ops/evidence/week6_git_state.txt](../ops/evidence/week6_git_state.txt) | git rev-parse HEAD and git status --porcelain |

---

## Summary of changes

- **New:** `backend/app/core/exchange_formatting_week6.py` — Decimal-based helpers: `normalize_decimal_str`, `quantize_price`, `quantize_qty`, `validate_price_tick`, `validate_qty_step`, `format_trigger_condition`; error classification and `operator_action_for_api_disabled`.
- **Broker:** In `crypto_com_trade.py`, on 140001: structured log `decision=BLOCKED reason_code=EXCHANGE_API_DISABLED` and `operator_action`; on 308: structured log `decision=FAILED reason_code=INVALID_PRICE_FORMAT` with pre_quantized/quantized values (no secrets).
- **Retry/circuit:** In `retry_circuit_week5.py`, 308 and 140001 added to `NON_RETRYABLE_EXCHANGE_CODES`; `is_exchange_code_retryable()` and `is_retryable_error(..., exchange_code=...)` added so these codes are not retried.
- **Tests:** 25 tests in `test_exchange_formatting_week6.py` and `test_tp_sl_week6.py` (formatting, trigger_condition, error classification).
- **Docs:** `docs/CRYPTOCOM_SL_TP_CREATION.md` (order types, required fields, rounding example, 308/140001 debug, where to change formatting).
- **No unrelated refactors.** TP/SL creation still uses existing `normalize_price` / `normalize_quantity` in the broker; Week 6 adds a reusable formatting module and structured error handling.

---

## Close-out

- A filled order can create TP and SL using existing broker normalization; when the exchange returns 308, we log INVALID_PRICE_FORMAT with safe values and try format variants; when it returns 140001, we block once with EXCHANGE_API_DISABLED and a clear operator checklist.
- Unit tests cover formatting and error classification; docs and evidence are in place; no secrets are printed and no full payloads including auth are logged.
