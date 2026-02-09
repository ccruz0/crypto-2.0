# Week 5 Audit Report: Trading Safety, Idempotency, Retries, Observability

**Goal:** Enforce trading safety invariants, idempotency/dedup, bounded retries/backpressure, and observability.

---

## Checklist A–F

| Item | Description | Status | Evidence |
|------|-------------|--------|----------|
| **A** | Safety invariants (valid symbol/side, quantity > 0, price format, TP/SL requires fill, SELL requires position) | PASS | [ops/evidence/week5_file_checks.txt](../ops/evidence/week5_file_checks.txt) (invariants), [week5_pytest.txt](../ops/evidence/week5_pytest.txt) (test_invariants_week5) |
| **B** | Idempotency/dedup: deterministic key, TTL window, block order and alert on duplicate | PASS | [week5_file_checks.txt](../ops/evidence/week5_file_checks.txt) (dedup), [week5_pytest.txt](../ops/evidence/week5_pytest.txt) (test_dedup_week5) |
| **C** | Bounded retries (max_attempts, base_delay, jitter, max_delay) and circuit breaker (N failures → cooldown, CIRCUIT_OPEN) | PASS | [week5_file_checks.txt](../ops/evidence/week5_file_checks.txt) (retry/circuit), [week5_pytest.txt](../ops/evidence/week5_pytest.txt) (test_retry_circuit_week5) |
| **D** | Correlation ID at start of signal evaluation and propagated through evaluate → decision → order → TP/SL → notify | PASS | [week5_file_checks.txt](../ops/evidence/week5_file_checks.txt) (correlation_id) |
| **E** | Health snapshot: last N decisions, dedup count, circuit state | PASS | [week5_file_checks.txt](../ops/evidence/week5_file_checks.txt) (health), [week5_diagnostics.txt](../ops/evidence/week5_diagnostics.txt) |
| **F** | All Week 5 tests pass | PASS | [week5_pytest.txt](../ops/evidence/week5_pytest.txt) (36 passed) |

---

## File Paths and Line Ranges

### A) Safety invariants
- **Module:** `backend/app/core/trading_invariants_week5.py`
  - `validate_symbol_and_side`, `validate_quantity`, `validate_price_format`, `validate_tp_sl_requires_fill`, `validate_sell_position_exists`, `validate_trading_decision`
  - `_log_blocked`: single structured log with `correlation_id`, `symbol`, `decision=BLOCKED`, `reason_code`
- **Wiring:** `backend/app/services/signal_monitor.py` (lines ~8068–8098): invariants run at start of `_place_order_from_signal`; on failure returns `{ "error": reason_code, "blocked": True }`.

### B) Idempotency / dedup
- **Key:** `backend/app/services/dedup_events_week5.py`: `compute_dedup_key(symbol, side, strategy_name, timeframe, trigger_price_bucket, time_bucket)`, `compute_dedup_key_from_context(symbol, side, strategy_key, trigger_price, now)`.
- **Table:** `backend/app/models/dedup_events_week5.py` (`DedupEventWeek5`), migration `backend/migrations/20260209_create_dedup_events_week5.sql` (`dedup_events`: id, created_at, key, correlation_id, symbol, action, payload_json).
- **Enforce:** `check_and_record_dedup(db, key, ..., ttl_minutes=15)`. If key exists within TTL → return `("DEDUPED", False)`, log `decision=DEDUPED`.
- **Wiring:** `backend/app/services/alert_emitter.py` (lines ~67–98): before sending alert, compute key and call `check_and_record_dedup`; if `DEDUPED`, return `False` (no alert, no order for that event).

### C) Bounded retries and circuit breaker
- **Retry:** `backend/app/core/retry_circuit_week5.py`: `retry_with_backoff(fn, max_attempts=3, base_delay=1.0, jitter=0.2, max_delay=60.0)`, `is_retryable_error(exc, http_code)`.
- **Circuit:** `CircuitBreaker(name, failure_threshold=5, window_minutes=5.0, cooldown_minutes=2.0)`; `record_failure` / `record_success`; `is_open()`; log `decision=CIRCUIT_OPEN` when opening.
- **Singletons:** `get_exchange_circuit()`, `get_telegram_circuit()` for health snapshot.

### D) Correlation ID propagation
- **Start:** `backend/app/services/signal_monitor.py`: `evaluation_id = str(uuid.uuid4())[:8]` (or `E2E_CORRELATION_ID`) at start of `_check_signal_for_coin_sync`.
- **Order:** `_place_order_from_signal(..., correlation_id=evaluation_id)`; call sites pass `correlation_id=evaluation_id`.
- **Logging:** `_log_pipeline_stage(..., correlation_id=evaluation_id)`; structured logs include `correlation_id`, `symbol`, `step`, `decision`, `order_id`, `reason_code` when blocked.

### E) Health snapshot
- **Script:** `scripts/run_week5_health_snapshot.py`: last N decisions (from `watchlist_signal_state`), `dedup_events_last_60min`, `circuit_exchange`, `circuit_telegram`.

### F) Tests
- `backend/tests/test_invariants_week5.py`: all invariant helpers and `validate_trading_decision`.
- `backend/tests/test_dedup_week5.py`: key determinism, `check_and_record_dedup` (ALLOWED/DEDUPED/refresh), same signal twice → second DEDUPED.
- `backend/tests/test_retry_circuit_week5.py`: retry stops after max_attempts, non-retryable does not retry, circuit opens after threshold, closes after cooldown.

---

## Exact Commands (with cd)

```bash
# Run Week 5 tests
cd /Users/carloscruz/automated-trading-platform/backend
python3 -m pytest tests/test_invariants_week5.py tests/test_dedup_week5.py tests/test_retry_circuit_week5.py -v

# Run pipeline diagnostics (may FAIL if no DB/exchange env)
cd /Users/carloscruz/automated-trading-platform
PYTHONPATH=backend python3 scripts/run_pipeline_diagnostics.py 2>&1

# Week 5 health snapshot (last decisions, dedup count, circuit state)
cd /Users/carloscruz/automated-trading-platform
PYTHONPATH=backend python3 scripts/run_week5_health_snapshot.py 2>&1

# Git state
cd /Users/carloscruz/automated-trading-platform
git rev-parse HEAD
git status
```

---

## Evidence Files (relative from docs/)

| File | Description |
|------|-------------|
| [../ops/evidence/week5_file_checks.txt](../ops/evidence/week5_file_checks.txt) | File:line references for invariants, dedup, retry/circuit, correlation, health |
| [../ops/evidence/week5_pytest.txt](../ops/evidence/week5_pytest.txt) | Full pytest run for Week 5 tests (35 passed) |
| [../ops/evidence/week5_diagnostics.txt](../ops/evidence/week5_diagnostics.txt) | Diagnostics script output (note: may fail due to env) |
| [../ops/evidence/week5_git_state.txt](../ops/evidence/week5_git_state.txt) | `git rev-parse HEAD` and `git status` |

---

## Config and Defaults

- **Dedup TTL:** `DEDUP_TTL_MINUTES = 15` in `backend/app/services/dedup_events_week5.py`.
- **Retry:** `DEFAULT_MAX_ATTEMPTS=3`, `DEFAULT_BASE_DELAY=1.0`, `DEFAULT_JITTER=0.2`, `DEFAULT_MAX_DELAY=60.0` in `backend/app/core/retry_circuit_week5.py`.
- **Circuit:** `failure_threshold=5`, `window_minutes=5.0`, `cooldown_minutes=2.0` for exchange and telegram breakers.
- **Migration:** Run `backend/migrations/20260209_create_dedup_events_week5.sql` on Postgres to create `dedup_events` table.

---

## Summary

- **Invariants:** Centralized in `trading_invariants_week5.py`; enforced in `_place_order_from_signal`; structured log `decision=BLOCKED` with `reason_code`.
- **Dedup:** Key = hash(symbol, side, strategy, timeframe, trigger_price_bucket, time_bucket); stored in `dedup_events`; 15-min TTL; enforced in `emit_alert` (block duplicate alert and thus duplicate order for same event).
- **Retry/Circuit:** Centralized in `retry_circuit_week5.py`; retry with backoff and error classification; circuit breaker with `CIRCUIT_OPEN` logging; available for wiring to exchange/telegram calls.
- **Observability:** `correlation_id` (evaluation_id) at start of signal check and passed into `_place_order_from_signal` and pipeline logs; health snapshot script reports last decisions, dedup count, circuit state.
- **Tests:** 36 tests in `test_invariants_week5.py`, `test_dedup_week5.py`, `test_retry_circuit_week5.py`; all pass (including same-signal-twice → only one order placement).
