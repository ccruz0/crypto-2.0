# OpenClaw Low-Cost Model Fallback Strategy

## 1. Purpose

This document defines a **low-cost, robust model-routing and fallback strategy** for OpenClaw task execution. The goal is to maximize reliability while minimizing model spend during the stabilization phase. By preferring cheap or nearly-free models first and escalating only when necessary, we reduce cost and avoid exhausting expensive provider credits (e.g. Anthropic) when rate limits or transient errors occur.

## 2. Current Problem

- **Anthropic credit exhaustion:** Runs fail when the primary (often expensive) model hits insufficient credits or payment-required, with no automatic switch to another provider.
- **Rate limit failures:** Provider rate limits (429 or similar) cause the entire run to fail instead of failing over to the next configured model.
- **Weak validation:** A run can be marked successful even when the upstream LLM call failed, or when the deliverable is partial/generic (e.g. template fallback or error message in the body).
- **Partial outputs treated as success:** If the gateway returns 200 with an error message or placeholder in the body, the integration layer may still treat it as success and write a “deliverable” that does not meet the task.

## 3. Desired Routing Policy

- **Cheap primary:** Default execution path uses the cheapest configured model first (e.g. a small/free-tier model or a low-cost API).
- **Cheap secondary fallback:** If the primary fails with a failover condition, try the next model in the chain (also cheap when possible).
- **Medium-cost fallback:** Further fallbacks can include mid-tier models for harder tasks.
- **Expensive model only as final or approved escalation:** Use high-cost models only when:
  - the task is explicitly marked high-complexity, or
  - all cheaper models in the chain have been tried and failed after configured retries.

Policy is configurable via an ordered model list; no code change is required to reorder or add models.

## 4. Failover Conditions

Treat the following as **failover conditions** (try next model in chain, do not mark success):

| Condition | Detection |
|-----------|-----------|
| Insufficient credit / low balance / payment required | HTTP 402, or response body/text containing phrases like "insufficient credit", "payment required", "low balance", "quota exceeded" (provider-specific) |
| Rate limit | HTTP 429 or body containing "rate limit", "too many requests" |
| Timeout | Request timeout (e.g. `OPENCLAW_TIMEOUT_SECONDS` exceeded) |
| Provider unavailable | Connection errors, DNS failures, connection refused |
| Transient 5xx | HTTP 500, 502, 503, 504 |
| Model not available / rejected | HTTP 400/404 with model-related message, or body containing "model not available", "model not found" |

When any of these occur, the client should log the reason, optionally apply a short backoff, then try the next model in the chain. Only when all models are exhausted should the run be marked failed.

## 5. Retry and Backoff Policy

- **Per-model retries:** Optional: up to 1 retry for the same model on transient 5xx or timeout (configurable). Default: 1 retry with a short delay (e.g. 5 seconds).
- **Failover to next model:** On failover condition, do not retry the same model again; move immediately to the next model in the chain (after optional minimal backoff to avoid thundering herd).
- **Backoff:** Minimal: e.g. 2–5 seconds before trying the next model. No exponential backoff required for stabilization phase; keep logic simple.

## 6. Validation Hardening

A run **cannot** be marked successful if any of the following are true:

1. **Upstream LLM call failed:** The last request to the OpenClaw gateway returned `success: false` or a non-2xx status, or the client hit a failover condition and never received a valid response.
2. **Requested deliverable file was not created:** The expected output file (e.g. investigation note under `docs/agents/bug-investigations/` or equivalent) must exist after the apply step.
3. **Deliverable is missing required sections:** For structured outputs (e.g. investigation reports), at least the required section headings must be present; otherwise the run is failed (e.g. "Task Summary", "Root Cause", "Recommended Fix", etc. as defined in the template).
4. **Response contains fallback/error markers:** If the body contains known error or template-fallback phrases (e.g. "openclaw not configured", "template fallback", "connection failed"), the run is failed even if HTTP 200.

Existing validation in the integration layer (e.g. `_call_openclaw_once`, `_validate_openclaw_note`) should enforce these rules; any gap should be closed so that partial or generic output is never treated as success.

## 7. Configuration Model

- **Ordered model chain:** Configured via a single ordered list, e.g.:
  - `OPENCLAW_MODEL_CHAIN=model1,model2,model3` (comma-separated), or
  - `OPENCLAW_PRIMARY_MODEL`, `OPENCLAW_FALLBACK_MODEL_1`, `OPENCLAW_FALLBACK_MODEL_2`, ...
- **Cheap-first mode:** A boolean or policy flag, e.g. `OPENCLAW_CHEAP_FIRST_MODE=true` (default). When true, the chain is used as-is (assumed to be ordered cheap → expensive). When false, a different policy could apply (e.g. task-type-based routing); for stabilization, cheap-first is the default.
- **Escalation rule:** Escalation to a more expensive model is allowed only when:
  - `OPENCLAW_CHEAP_FIRST_MODE=true` and a cheaper model has already failed with a failover condition, or
  - The task is explicitly marked high-complexity (if such a field exists in the task payload).
- Model names are provider/model identifiers as understood by the OpenClaw gateway (e.g. `openai/gpt-4o-mini`, `anthropic/claude-3-5-haiku-20241022`). The gateway is responsible for mapping these to actual API calls.

Configuration is read from environment (or equivalent) so that the model chain can be changed without code changes.

## 8. Logging and Observability

Log the following for troubleshooting and spend tracking:

- **Primary model selected:** At the start of a request, log which model is tried first (e.g. `openclaw_client: primary_model=openai/gpt-4o-mini task_id=...`).
- **Fallback used:** When a failover occurs, log which model was tried, the failover reason, and the next model (e.g. `openclaw_client: failover reason=rate limit model_tried=... next_model=... task_id=...`).
- **Failover reason:** Explicit reason (e.g. `HTTP 429`, `timeout`, `insufficient credit`, `connection failed`).
- **Escalation to expensive model:** When the first model that succeeds is not the primary (e.g. we had to use fallback 2 or 3), log that escalation occurred (e.g. `openclaw_client: escalation_used=true primary_failed model_used=... task_id=...`).

These logs allow operators to confirm cheap-first behavior and to detect when credit or rate limits are frequently hit.

## 9. Rollout Strategy

1. **Deploy config and code:** Add the new env vars with cheap-first defaults (e.g. `OPENCLAW_MODEL_CHAIN=openai/gpt-4o-mini,anthropic/claude-3-5-haiku-20241022,...` and `OPENCLAW_CHEAP_FIRST_MODE=true`). Ensure the OpenClaw gateway accepts the `model` parameter in the request body.
2. **Run with cheap-first:** Execute tasks using the new client; verify in logs that the primary model is the cheapest and that fallback is used when the primary fails.
3. **Monitor:** Watch for false failures (e.g. cheap model always failing for a given task type) and adjust the chain or add a high-complexity path if needed.
4. **Rollback:** To revert, set `OPENCLAW_MODEL_CHAIN` to a single model (e.g. previous default) or remove the fallback logic via feature flag if one is added; no data migration required.

## 10. Verification

- **Confirm fallback is working:** Trigger a scenario where the primary model would fail (e.g. temporarily use an invalid or rate-limited primary, or inspect logs after a known 429). Verify logs show:
  - `primary_model=...`
  - `failover reason=...`
  - `next_model=...` and a subsequent successful response with a different model.
- **Confirm cheap-first:** Check logs that the first model in the chain is the cheapest one configured.
- **Confirm validation:** After a run that hit an upstream error (e.g. 502), confirm the run is not marked successful and the deliverable is not written or is clearly marked as failed.
- **Confirm no success on LLM failure:** Simulate an upstream failure (e.g. wrong API key for primary); the run must end with `success: false` and no file created for the task.

## 11. Default Cheap-First Routing Order (Recommended)

For stabilization, use cheap/free-tier models first. Example (gateway-dependent model names):

1. **Primary:** `openai/gpt-4o-mini` (low cost)
2. **Fallback 1:** `anthropic/claude-3-5-haiku-20241022` (low cost)
3. **Fallback 2:** `anthropic/claude-3-5-sonnet-20241022` (medium)
4. **Final:** `anthropic/claude-sonnet-4-20250514` or similar only if needed

Set via: `OPENCLAW_MODEL_CHAIN=openai/gpt-4o-mini,anthropic/claude-3-5-haiku-20241022,anthropic/claude-3-5-sonnet-20241022`

If the gateway uses a single alias (e.g. `openclaw`) and resolves models internally, set that alias as the only element or configure the chain to match what the gateway accepts.

## 12. Verification Steps

1. **Confirm primary model in logs:** Run a task and check logs for `openclaw_client: primary_model=...` — should show the first model in your chain.
2. **Confirm fallback on failure:** Temporarily set `OPENCLAW_PRIMARY_MODEL` to an invalid or rate-limited model; run a task; verify logs show `failover reason=...`, `next_model=...`, and then either success with `model_used=<fallback>` or final failure.
3. **Confirm no success on LLM failure:** With wrong token or unreachable URL, the run must end with `success: false` and no deliverable file created.
4. **Confirm validation rejects error-in-body:** If the gateway ever returns 200 with "insufficient credit" or "rate limit" in the body, the integration must not mark the run successful (fallback markers in `agent_callbacks`).

## 13. Rollback Steps

- **Revert to single model:** Set `OPENCLAW_MODEL_CHAIN=openclaw` (or your previous single model). Restart the process that calls OpenClaw. No code revert needed.
- **Disable cheap-first (use chain as-is):** Set `OPENCLAW_CHEAP_FIRST_MODE=false`. Chain order is still respected; only logging/interpretation may change.
- **Revert code:** Restore `openclaw_client.send_to_openclaw` to a single-model POST and remove `_model_chain`, `_post_one`, `_is_failover_condition`; remove the extra `_OPENCLAW_FALLBACK_MARKERS` entries in `agent_callbacks`.

---

*See also: `backend/app/services/openclaw_client.py` (model chain and failover), `backend/app/services/agent_callbacks.py` (validation and apply flow).*
