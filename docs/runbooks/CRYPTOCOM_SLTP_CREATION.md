# Runbook: Crypto.com SL/TP Creation

How to create Stop Loss (SL) and Take Profit (TP) orders correctly for Crypto.com Exchange, and how to fix errors 308 and 140001.

**See also:** `docs/CRYPTOCOM_SL_TP_CREATION.md`, `docs/trading/crypto_com_order_formatting.md`

---

## 1. Order types and endpoints

| Order   | Type               | Endpoint                  | Fallback on 140001        |
|---------|--------------------|---------------------------|----------------------------|
| Stop Loss  | `STOP_LIMIT`       | `private/create-order`   | `private/create-order-list` (single order) |
| Take Profit | `TAKE_PROFIT_LIMIT` | `private/create-order`   | `private/create-order-list` (single order) |

Both use **strings** for all numeric fields (`price`, `quantity`, `trigger_price`, `ref_price`). Never send floats or scientific notation.

---

## 2. Formats that work

### Price and trigger_price

- **Quantize** to the instrument’s `price_tick_size` (from `public/get-instruments`).
- **SL**: ROUND_DOWN (conservative trigger).
- **TP**: ROUND_UP (ensure profit target is met).
- **Output**: Plain decimal string, `.` separator, **no scientific notation**, no commas.
- Helpers: `app.core.exchange_formatting_week6.quantize_price`, `format_price_for_exchange`, `normalize_decimal_str`.

### Quantity

- **Quantize** to `qty_tick_size`; ROUND_DOWN.
- Must be ≥ `min_quantity`.
- Plain decimal string, no scientific notation.
- Helper: `quantize_qty`, `format_qty_for_exchange`.

### trigger_condition

- **TP**: `">= {price}"` or `">={price}"` (trigger when market ≥ TP price).
- **SL**: `"<= {price}"` or `"<={price}"` (trigger when market ≤ SL price).
- `price` must be the same string as `trigger_price` (same precision).
- Helper: `format_trigger_condition()` in `exchange_formatting_week6.py`.

### ref_price

- For **STOP_LIMIT**: set to the same value as `trigger_price` (SL price) so Trigger Condition displays correctly.
- For **TAKE_PROFIT_LIMIT**: set to the same value as `price` / `trigger_price` (TP price).
- Always use the **same string** as `trigger_price` to avoid 308.

---

## 3. Error 308 (Invalid price format)

**Cause:** Price, trigger_price, or ref_price not accepted (wrong precision, scientific notation, or not aligned to tick).

**Fixes:**

1. Use instrument metadata: `price_tick_size`, `price_decimals` from `_get_instrument_metadata(symbol)`.
2. Quantize with `quantize_price(symbol_meta, price, round_up=...)` then format with `normalize_decimal_str()` so output is never scientific notation.
3. Ensure `ref_price` and `trigger_price` are the **exact same string** when they represent the same value.
4. On 308 the code retries with multiple precision levels and uses `normalize_decimal_str` in the retry path.

**Where:** `crypto_com_trade.place_stop_loss_order` / `place_take_profit_order` (308 handling); `exchange_formatting_week6` for helpers.

---

## 4. Error 140001 (API_DISABLED)

**Meaning:** Conditional/trigger orders disabled for this account or API (permissions, IP allowlist, or account setting).

**Behaviour:**

1. We log `reason_code=EXCHANGE_API_DISABLED` and send a rate-limited alert.
2. **Automatic fallback:** Before returning, we try **once** with `private/create-order-list` (single order in the list). Some accounts accept the list endpoint when `create-order` returns 140001.
3. If the list endpoint also returns 140001, the operator must enable conditional orders for the account/API (no code change can fix it).

**Operator steps:** Enable API trading / conditional orders; check IP allowlist and sub-account permissions. See `operator_action_for_api_disabled()` in `exchange_formatting_week6.py`.

---

## 5. Quick reference: code locations

| What                | File / symbol |
|---------------------|----------------|
| Quantize/format helpers | `app.core.exchange_formatting_week6` |
| SL placement        | `crypto_com_trade.place_stop_loss_order` |
| TP placement        | `crypto_com_trade.place_take_profit_order` |
| 140001 → create-order-list | `_try_create_order_list_with_params` (called on 140001 in both SL and TP) |
| Instrument metadata | `crypto_com_trade._get_instrument_metadata` |
| Non-retryable codes | `retry_circuit_week5.NON_RETRYABLE_EXCHANGE_CODES` (308, 140001) |

---

## 6. Common errors

### 140001 (API_DISABLED)

- **Meaning:** Conditional/trigger orders are disabled for this account or API (permissions, IP allowlist, or account setting).
- **What the code does:** On 140001 from `private/create-order`, we log a single `SLTP_140001` line (no params), classify context via `_classify_140001_context(base_url)`, then try **one** fallback: call `private/create-order-list` with the same params (as strings). If that succeeds, we return the order_id; otherwise we return a structured error with `fallback_attempted` and `fallback_error`. No param values are logged (keys only).

### 308 (Invalid price format)

- **Meaning:** Price, trigger_price, or ref_price not accepted (wrong precision, scientific notation, or not aligned to tick).
- **What the code does:** All numeric payloads use decimal-only strings with tick/step quantization; no scientific notation. Helpers: `format_price_for_exchange`, `format_qty_for_exchange`; `validate_sltp_payload_numeric(params)` runs for both SL and TP before sending. Retries use `normalize_decimal_str` in the retry path.

---

## 7. Validation (doctor:sltp)

1. **Run the doctor task:**
   ```bash
   curl -sS -X POST http://127.0.0.1:8002/api/ai/run \
     -H "Content-Type: application/json" \
     -d '{"task":"doctor:sltp","mode":"sandbox","apply_changes":false}'
   ```

2. **Find the report:** Under `backend/ai_runs/<timestamp>/report.json` (latest run = latest timestamp directory).

3. **PASS criteria:**
   - `tail_logs_source` == `docker_compose`
   - `compose_dir_used` == `/app`
   - `logs_excerpt_len` > 200
   - `payload_numeric_validation` == `PASS`

---

## 8. Verifying after code changes

- Run doctor:sltp (see §7) and check the report for formatting/error handling.
- Run backend tests: `docker compose --profile aws exec backend-aws pytest backend/tests -k 'crypto_com or exchange_formatting or sltp' -v --no-header -q 2>/dev/null || true` (or install pytest in container and run `tests/test_crypto_com_sltp_140001_fallback.py` and `tests/test_ai_engine_doctor_sltp_env_mismatch.py`).
- In sandbox, place one SL and one TP and confirm payloads use string prices and no scientific notation (log payload keys only, not values).
