# OpenClaw PR Queue & Requirements Index

**Date:** 2026-02-15  
**Mode:** FULL (requirements harvest → audit → PR queue → contracts)  
**Source of requirements:** Repository Markdown only (docs/).

---

## Part 1 — Requirements Index (Summary)

Requirements are harvested from the following doc set and normalized into the table below. **Only** these docs are used as the requirement source.

| Source document | Domain | Section ref |
|-----------------|--------|-------------|
| [docs/REQUIREMENTS.md](../../REQUIREMENTS.md) | Canonical list (trading, risk, execution, data, alerts, observability, safety, infra) | Full doc |
| [docs/requirements/REQUIREMENTS_MAP.md](../../requirements/REQUIREMENTS_MAP.md) | Structured map with IDs (T1–T6, R1–R3, E1–E6, D1–D3, A1–A4, O1–O4, S1–S3, I1–I3) | By domain |
| [docs/SYSTEM_MAP.md](../../SYSTEM_MAP.md) | Order lifecycle, sync truth (§2.0–2.1), phases 1–8, gates (§4.1–4.3) | §2, §4 |
| [docs/ORDER_CANCELLATION_NOTIFICATIONS.md](../../ORDER_CANCELLATION_NOTIFICATIONS.md) | All 7 cancellation scenarios must send Telegram | Full doc |
| [docs/ORDER_LIFECYCLE_GUIDE.md](../../ORDER_LIFECYCLE_GUIDE.md) | Sync truth, confirmation source | Referenced in REQUIREMENTS |
| [docs/ALERTAS_Y_ORDENES_NORMAS.md](../../ALERTAS_Y_ORDENES_NORMAS.md) | Alert/trade rules, throttle, cooldown, portfolio limit | Bloqueos 1–4, Paso 4 |
| [docs/runbooks/CRYPTOCOM_SLTP_CREATION.md](../../runbooks/CRYPTOCOM_SLTP_CREATION.md) | SL/TP types, trigger_condition, 140001 fallback | §1–4 |
| [docs/telegram-safety.md](../../telegram-safety.md) | Telegram env isolation, kill switches | Full doc |
| [docs/security/EC2_EGRESS_GUARDRAILS.md](../../security/EC2_EGRESS_GUARDRAILS.md) | http_client single entry, allowlist, redirects | Full doc |
| [docs/contracts/deployment_aws.md](../../contracts/deployment_aws.md) | AWS path, Docker profile | Full doc |
| [docs/AWS_CRYPTO_COM_CONNECTION.md](../../AWS_CRYPTO_COM_CONNECTION.md) | Production Crypto.com env | Full doc |
| [docs/monitoring/business_rules_validation.md](../../monitoring/business_rules_validation.md) | BUY/SELL rules, MA checks, index | §1–4 |
| [docs/LIFECYCLE_EVENTS_COMPLETE.md](../../LIFECYCLE_EVENTS_COMPLETE.md) | Event semantics, throttle tab source | Full doc |

### Requirement IDs (Must = required; Should = strongly recommended)

| ID | Requirement (short) | Priority | Domain | Acceptance |
|----|---------------------|----------|--------|------------|
| E5 | Sync: resolve final state via order_history/trade_history; never assume missing from open_orders = canceled | Must | Execution | ORDER_CANCELED only after history/cancel API |
| A4 | All 7 cancellation scenarios send Telegram notification | Must | Alerts | Each scenario triggers one Telegram |
| O4 | TRADE_BLOCKED includes gate name and reason | Must | Observability | event_reason / reason_code stable |
| D3 | Stale data > 30 min → block (SKIP_MARKET_DATA_STALE / STALE_DATA) | Must | Data | require_fresh before order creation |
| S3 | No logging of API keys/tokens/secrets | Must | Safety | Redaction; no raw secret in logs |
| S1 | Telegram: LOCAL vs AWS env; kill switches tg_enabled_local/aws | Must | Safety | verify_telegram_safety.py |
| S2 | All HTTP via app.utils.http_client; egress allowlist | Must | Safety | Single entry point; allowlist |
| O1 | Lifecycle events ORDER_CREATED, ORDER_EXECUTED, ORDER_CANCELED, TRADE_BLOCKED, etc. recorded | Must | Observability | _emit_lifecycle_event / record_signal_event |
| O3 | Sync messages state status source (open_orders, order_history, trade_history) | Must | Observability | Log/notification includes source |
| R1 | Max open BUY orders per symbol: 3 | Must | Risk | Gate rejects when >= 3 |
| E6 | DRY_RUN / live_trading=False: do not place real orders | Must | Execution | dry run gate in place_market_order |
| T1 | BUY signal: all buy_* flags True per strategy | Must | Trading | calculate_trading_signals |
| A2 | Alert throttle: 60s cooldown + price change threshold | Must | Alerts | should_emit_signal |
| E2 | SL = STOP_LIMIT, TP = TAKE_PROFIT_LIMIT; quantize to tick sizes | Must | Execution | normalize_decimal_str, format |
| E3 | trigger_condition TP ">=", SL "<="; ref_price = trigger_price | Must | Execution | format_trigger_condition |

*(Full set in [docs/requirements/REQUIREMENTS_MAP.md](../../requirements/REQUIREMENTS_MAP.md).)*

---

## Part 2 — PR Queue (Priority Order)

### Already implemented (evidence in [2026-02-15_audit.md](2026-02-15_audit.md))

| PR | Goal | Severity | Status | Evidence |
|----|------|----------|--------|----------|
| PR1 | No secrets in logs (redaction, no API key/token in log) | P0 | **DONE** | test_redaction.py, test_no_secret_logging_strings.py |
| PR2 | Sync truth: missing ≠ canceled; resolve via order_history | P1 | **DONE** | test_sync_missing_not_canceled.py |
| PR3 | All terminal notifications (CANCELLED/EXPIRED/REJECTED) with idempotency | P1 | **DONE** | test_terminal_order_notifier.py, last_notified_terminal_status |
| PR4 | TRADE_BLOCKED reason codes (canonical ReasonCode, Telegram + logs) | P2 | **DONE** | test_trade_blocked_reason_codes.py |
| PR5 | 30-min stale data gate (require_fresh before order creation) | P2 | **DONE** | test_stale_data_gate.py, data_freshness.py |

### Proposed next (from LATEST_AUDIT)

| PR | Goal | Severity | Status | Branch (proposed) |
|----|------|----------|--------|-------------------|
| PR6 | Stale data gate on SELL path: call require_fresh before _create_sell_order | P2 | **READY** | openclaw/pr-06-sell-stale-gate |
| PR7 | Contract tests in CI (run test_system_contracts.py on push/PR) | P2 | **READY** | openclaw/pr-07-contract-ci |
| PR8 | Evidence scripts: pr-01 … pr-06 + run_evidence_all.sh | P2 | **READY** | openclaw/pr-08-evidence-scripts |

### Execution order (after audit approval)

1. **PR6** — Minimal: add require_fresh + TRADE_BLOCKED(STALE_DATA) before `asyncio.run(self._create_sell_order(...))` in signal_monitor (same pattern as BUY).
2. **PR7** — Add backend/tests/test_system_contracts.py enforcing invariants from SYSTEM_CONTRACT.md; add to CI if present.
3. **PR8** — Add EVIDENCE/pr-01.md … pr-06.md with exact commands (cd + pytest / rg) and expected output snippet.

---

## Part 3 — Links

- **Audit report:** [LATEST_AUDIT.md](LATEST_AUDIT.md)
- **System contracts (invariants):** [SYSTEM_CONTRACT.md](SYSTEM_CONTRACT.md)
- **Previous audit (2026-02-15):** [2026-02-15_audit.md](2026-02-15_audit.md)
- **Fix plan (chunks 1–5):** [2026-02-15_fix_plan.md](2026-02-15_fix_plan.md)
- **Evidence (per-PR):** [EVIDENCE/](EVIDENCE/)
  - [pr-01.md](EVIDENCE/pr-01.md) — No secrets in logs
  - [pr-02.md](EVIDENCE/pr-02.md) — Sync truth (missing ≠ canceled)
  - [pr-03.md](EVIDENCE/pr-03.md) — Terminal notifications
  - [pr-04.md](EVIDENCE/pr-04.md) — TRADE_BLOCKED reason codes
  - [pr-05.md](EVIDENCE/pr-05.md) — Stale data gate (BUY)
  - [pr-06.md](EVIDENCE/pr-06.md) — Stale data gate (SELL)
- **Run all evidence:** `bash docs/audits/openclaw/run_evidence_all.sh` (from repo root; logs under [EVIDENCE/logs/](EVIDENCE/logs/))
