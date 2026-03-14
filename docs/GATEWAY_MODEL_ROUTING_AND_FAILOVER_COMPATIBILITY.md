# Gateway Model Routing and Failover Compatibility

## 1. Purpose

This document defines how the **OpenClaw gateway** must accept requested models, route them correctly to provider backends, and return **failover-friendly errors**. The ATP integration sends an ordered model chain and relies on the gateway to (1) honor the `model` field in each request, (2) use that model when supported, and (3) return clear failure signals (HTTP status and/or body) when a provider fails—so ATP can try the next model in the chain. The gateway must never fake success when the upstream provider rejected the call or when generation did not complete.

**Scope:** Gateway = the server that exposes the OpenResponses HTTP API (e.g. `POST /v1/responses`) and forwards requests to LLM providers. Gateway application code lives in the **OpenClaw repository** (e.g. `ccruz0/openclaw`); this doc is the compatibility contract and implementation checklist for that repo.

**Request-body `model`:** Must be supported by the gateway (§3, §7). Status: **to be verified and implemented in the OpenClaw repo** (gateway source is not in ATP).

---

## 2. Current Behavior

- **Config-driven default:** The ATP wrapper (in this repo) writes `openclaw.json` with `agents.defaults.model.primary` and `agents.defaults.model.fallbacks` (array). The gateway is expected to read this config at startup.
- **Request body:** ATP’s `openclaw_client` sends `POST /v1/responses` with JSON body: `model`, `input`, optional `user`, optional `instructions`. Whether the gateway today **uses** the request’s `model` or only the configured default is implementation-defined and must be verified in the OpenClaw repo.
- **Failure handling:** If the gateway does not return proper HTTP status codes (429, 402, 503, etc.) or returns 200 with error text in the body, ATP cannot reliably fail over to the next model.

---

## 3. Incoming Request Contract

The gateway **must** support the following so ATP’s cheap-first fallback works end-to-end.

| Field        | Required | Current (to verify in gateway) | Required behavior |
|-------------|----------|---------------------------------|-------------------|
| **`model`** | Yes      | Confirm: parsed from body and used | String; provider/model id (e.g. `openai/gpt-4o-mini`, `anthropic/claude-3-5-haiku-20241022`). Gateway must use this when the model is supported; otherwise return 400 with a clear message. Must not silently ignore. |
| **`input`** | Yes      | -                               | Prompt/text sent to the model. |
| **`user`**  | No       | -                               | Optional user/session id (e.g. `notion-task-<id>`). |
| **`instructions`** | No | -                        | Optional system instructions. |

- **Provider:** If the gateway uses a separate `provider` field, it must be consistent with `model` (e.g. `model` may be `openai/gpt-4o-mini` and provider inferred as `openai`). Prefer a single `model` field that encodes provider/model.
- **Aliases:** If the gateway supports aliases (e.g. `openclaw` → default model), the alias must map to a single configured model; request-body `model` must still override when present and supported.
- **Fixed model only:** If the gateway currently ignores request `model` and uses only a fixed configured model, that is a **compatibility gap**; the minimal change is to accept and use request-body `model` when it is in the allowed/supported list.

---

## 4. Routing Logic

- **Resolve model:** For each request, effective model = request body `model` if present and supported; else config `agents.defaults.model.primary`.
- **Supported set:** Gateway must have a stable mapping from model id → (provider, model id for that provider). Supported models can come from config (e.g. list or map in `openclaw.json`) or from a built-in allow-list. Unsupported model id → **400** with body indicating unsupported model (see §5).
- **No silent fallback to a different model:** If the client sends `model: "openai/gpt-4o-mini"`, the gateway must not substitute a different model (e.g. Claude) without returning an error. Substitution would break ATP’s chain (ATP would believe gpt-4o-mini was used).
- **Fallbacks:** ATP handles the fallback chain (tries model A, then B, then C). The gateway does **not** need to implement multi-hop fallback; it only needs to honor the requested model and fail clearly so ATP can retry with the next.

---

## 5. Failure Behavior

The gateway must return the following so ATP can detect failover conditions and not mark the run as successful.

| Condition | Gateway response | Notes |
|----------|------------------|--------|
| **Unsupported / unknown model** | **400** Bad Request. Body must include a message containing "model" and "not supported" or "unknown" or "invalid" (so ATP can treat as non-retryable or as failover). | Do not use 200 with error in body only. |
| **Insufficient credits / payment required** | Prefer **402** Payment Required. Body may include "insufficient credit", "payment required", "quota exceeded". If provider returns 200 with such text, gateway should still return **402** or **503** and not forward the error as success. | ATP matches 402 and error text. |
| **Rate limit** | **429** Too Many Requests. Body may include "rate limit", "too many requests". | |
| **Timeout** | **504** Gateway Timeout, or **408** Request Timeout. Do not return 200 with timeout message in body. | |
| **Provider unavailable / connection error** | **503** Service Unavailable. Body may include "unavailable", "connection failed", "connection refused". | |
| **Transient 5xx from provider** | **502** Bad Gateway or **503** Service Unavailable. Do not return 200 with upstream error in body. | |
| **Upstream rejection (e.g. auth, forbidden)** | **502** or **503** with message that indicates provider rejection. | |

**Critical:** The gateway must **never** return **200** with a response body that looks like normal output when:
- the upstream provider rejected the call,
- the provider had insufficient credit,
- the requested model is unsupported,
- or generation never actually completed (e.g. partial or error placeholder).

In those cases the gateway must return an appropriate non-2xx status and/or a structured error body so ATP does not treat the run as successful.

---

## 6. Compatibility Gaps

What currently prevents ATP’s cheap-first fallback from working end-to-end (to be verified and fixed in the OpenClaw repo):

1. **Request `model` ignored:** If the gateway does not read or use `model` from the request body, ATP’s chain is ineffective (every request uses the same default).
2. **Unknown model silently mapped:** If an unknown `model` is silently replaced by the default, ATP cannot tell that the requested model failed.
3. **Provider failure → 200 + error in body:** If the gateway returns 200 and forwards the provider’s error message as “content”, ATP may treat it as success; validation may catch some cases via markers, but HTTP-level failure is more reliable.
4. **No 429/402/503 on provider errors:** If the gateway always returns 200 and puts “rate limit” or “insufficient credit” only in the body, ATP’s client may still classify it as failover via body parsing, but status codes are clearer and more robust.
5. **Unsupported model returns 200:** If requesting an unsupported model returns 200 with an error message in the body, ATP might not consistently treat it as failure; **400** for unsupported model is required.

---

## 7. Minimal Hardening Changes

Only minimal, localized changes in the gateway (OpenClaw repo):

1. **Parse and use request-body `model`:**
   - In the handler for `POST /v1/responses`, read `model` from the request body.
   - If present and non-empty, resolve it to the internal provider/model; if supported, use it for the call. If not supported, return **400** with a JSON or text body that includes a phrase like "model not supported" or "unknown model".
   - If absent or empty, use config default (`agents.defaults.model.primary`).

2. **Stable mapping:**
   - Maintain a map or allow-list from requested model id → (provider, backend model id). Populate from config (e.g. `agents.defaults.model.primary` + `fallbacks` + any alias map) or from a single source of truth so the same id always maps to the same backend.

3. **Explicit rejection of unsupported model:**
   - When the requested `model` is not in the supported set, respond with **400** and a clear message. Do not fall back to another model without returning an error.

4. **Explicit failure signals for provider failures:**
   - When the provider returns or the SDK throws:
     - rate limit → gateway returns **429**.
     - insufficient credit / payment required / quota → gateway returns **402** (or **503** with message containing "insufficient credit" or "payment required").
     - timeout → **504** or **408**.
     - connection/unavailable → **503**.
     - other upstream 5xx or rejection → **502** or **503**.
   - Do not return 200 with the error string as the only “content”; return a non-2xx status so ATP never treats it as success.

5. **No false success:**
   - After calling the provider, if the response is an error or partial/placeholder (e.g. “insufficient credit”, “rate limit”, empty or error message), do not send 200 with that as the success body. Return the appropriate non-2xx and, if needed, an error payload (e.g. `{ "error": "...", "code": "RATE_LIMIT" }`).

---

## 8. Logging Requirements

The gateway should log at least:

- **Requested model:** e.g. `gateway request model=<from body or "default">`.
- **Effective provider/model used:** e.g. `gateway effective model=<resolved backend model> provider=<name>`.
- **Rejection before generation:** e.g. `gateway model not supported requested=<id>` when returning 400.
- **Reason for failover-worthy failure:** e.g. `gateway provider error status=429 reason=rate limit` or `gateway provider error reason=insufficient credit` when returning 429/402/503.
- **Response completion/failure:** e.g. `gateway response status=200` or `gateway response status=503 reason=...`.

This allows operators to confirm that the requested model was used and to debug why a request failed (so ATP can rely on the next model in the chain).

---

## 9. Verification Plan

1. **Request-body `model` honored:** Send `POST /v1/responses` with `model: "openai/gpt-4o-mini"` (or a supported cheap model). Verify in gateway logs that the effective model is the requested one and the response is from that provider. Repeat with an unsupported `model`; expect **400** and no generation.
2. **Unsupported model → 400:** Send `model: "nonexistent/model"`. Expect **400** and a body containing "model" and "not supported" or similar. Response must not be 200.
3. **Rate limit → 429:** Simulate or trigger a rate limit from the provider. Expect gateway to return **429** (and optionally body with "rate limit"). ATP client should treat this as failover.
4. **Insufficient credit → 402 or 503:** Simulate or use an account with exhausted credits. Expect **402** or **503** with message indicating credit/payment. Must not be 200 with error only in body.
5. **Timeout → 504/408:** Cause a long-running request to time out. Expect **504** or **408**, not 200.
6. **No success on provider failure:** For any of the above, confirm that the gateway never returns 200 with the error message as the sole “content” so that ATP never marks the run as successful.

---

## 10. Recommended Default Stabilization Policy

- **Cheap-first default:** During stabilization, the default model (when request does not specify one) should be a low-cost model (e.g. `openai/gpt-4o-mini` or `anthropic/claude-3-5-haiku-20241022`), not the most capable/expensive.
- **Recommended ATP chain (cost control):** `gpt-4o-mini` → `claude-3.5-haiku` → `claude-3.5-sonnet` → `gpt-4o` → `claude-sonnet-4`. This prevents wasting credits while debugging; the gateway only needs to support these model ids when present in config.
- **Config:** The ATP wrapper already sets `agents.defaults.model.primary` and `agents.defaults.model.fallbacks` in `openclaw.json`. Use `primary` as the default when request `model` is missing; order `fallbacks` cheap-first so that any gateway-internal fallback (if kept) is consistent. Prefer ATP to drive the chain via request `model` and gateway to honor it and fail clearly.

---

## Config Variables (Wrapper / Gateway)

| Variable | Used by | Purpose |
|----------|---------|--------|
| `OPENCLAW_MODEL_PRIMARY` | ATP wrapper (openclaw.json) | Default model when request does not specify one; cheap-first default: `openai/gpt-4o-mini`. |
| `OPENCLAW_MODEL_FALLBACKS` | ATP wrapper (openclaw.json) | Comma-separated fallback list; order should be cheap-first for stabilization. |
| Request body `model` | Gateway (OpenClaw repo) | Client-specified model; gateway must honor when supported and return 400 when unsupported. |

No new env vars are required in the gateway for request-body `model`; the gateway only needs to read the existing request body and add the parsing/routing/failure behavior described in §7.

---

## Reference: ATP Side

- **Strategy:** [OPENCLAW_LOW_COST_MODEL_FALLBACK_STRATEGY.md](OPENCLAW_LOW_COST_MODEL_FALLBACK_STRATEGY.md)
- **Client:** `backend/app/services/openclaw_client.py` (sends `model` in body, interprets status and error text for failover)
- **Wrapper (this repo):** `openclaw/docker-entrypoint.sh` (writes `openclaw.json` with `agents.defaults.model.primary` and `fallbacks`; defaults updated for cheap-first)

---

---

## 11. Gateway Code Inspection (OpenClaw Repo)

These questions must be answered in the **OpenClaw gateway repository** (not in ATP). ATP only provides the wrapper config and this contract.

| Question | How to answer in OpenClaw repo |
|----------|-------------------------------|
| Does the gateway already accept `model` in the request body? | Search for the `/v1/responses` (or OpenResponses) handler and the code that parses the request body; check for a `model` field. |
| If yes, where is it parsed? | Identify the request schema or body parser (e.g. Zod, express.json(), or similar) and the property used for model. |
| If yes, where is it mapped to a provider/model? | Find where the chosen model is resolved to a provider and backend model id (config, map, or allow-list). |
| If not, what is the minimal change to support it? | In the handler, read `body.model`; if present and in the supported set, use it; else if present and unsupported, return 400; else use config default. |
| Does the gateway currently ignore unknown models silently? | If unknown `model` falls back to default without returning an error, that is a bug; return 400 for unsupported model. |
| Does the gateway return proper status codes on provider failure? | In the provider call path, catch rate limit (429), credit (402), timeout, 5xx, and set gateway response status to 429/402/504/503/502 instead of 200. |
| Can provider failure still produce a misleading 200? | If the gateway ever sends 200 with the provider’s error message as the only content, fix by returning non-2xx and optional error body. |

---

## 12. Supported Request Format (Contract)

**Endpoint:** `POST /v1/responses`  
**Headers:** `Authorization: Bearer <token>`, `Content-Type: application/json`

**Request body (JSON):**

```json
{
  "model": "openai/gpt-4o-mini",
  "input": "User prompt text.",
  "user": "notion-task-abc123",
  "instructions": "Optional system instructions."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model` | string | Yes | Provider/model id (e.g. `openai/gpt-4o-mini`). Gateway must use it when supported; else 400. |
| `input` | string | Yes | Prompt to send to the model. |
| `user` | string | No | Client-defined user/session id. |
| `instructions` | string | No | System instructions. |

**Success:** **200** with JSON body containing the model output (e.g. `output` array or `output_text`).  
**Failure:** See **Exact error semantics** below.

### Exact error semantics

| HTTP status | When to use | Response body (optional but recommended) |
|-------------|-------------|------------------------------------------|
| **400** | Unsupported or unknown `model` in request | `{"error":"model not supported","requested":"<id>"}` or message containing "model" and "not supported" / "unknown" / "invalid" |
| **402** | Insufficient credit, payment required, quota exceeded | `{"error":"insufficient credit"}` or "payment required" / "quota exceeded" |
| **429** | Provider rate limit, too many requests | `{"error":"rate limit"}` or "too many requests" |
| **408** | Client/request timeout before generation completed | `{"error":"request timeout"}` |
| **502** | Upstream provider error (5xx, bad gateway) | `{"error":"provider error","message":"..."}` |
| **503** | Provider unavailable, connection failed, service unavailable | `{"error":"service unavailable"}` or "connection failed" / "unavailable" |
| **504** | Gateway timeout waiting for provider | `{"error":"gateway timeout"}` |

Never return **200** when: upstream rejected the call, insufficient credit, unsupported model, or generation did not complete (error or placeholder in upstream response).

---

## 13. Verification Steps (Checklist)

1. In OpenClaw repo, run gateway and send `POST /v1/responses` with `model: "openai/gpt-4o-mini"` (or first in your chain). Confirm logs show requested model and response 200.
2. Send with `model: "unsupported/fake"`. Confirm **400** and message containing "model" and "not supported" (or similar).
3. Trigger or simulate provider rate limit. Confirm gateway returns **429**.
4. Trigger or simulate insufficient credit. Confirm **402** or **503**, not 200 with error in body.
5. Confirm gateway never returns 200 when the upstream call failed (e.g. error placeholder in body). Use logs from §8.

---

## 14. Rollback Steps

- **Gateway:** Revert the change that reads request-body `model` and restore “fixed default model only” if needed; ensure failed provider calls still return non-2xx (no regression on failure behavior).
- **ATP wrapper:** Set `OPENCLAW_MODEL_PRIMARY` and `OPENCLAW_MODEL_FALLBACKS` back to previous values; redeploy wrapper so `openclaw.json` is regenerated. ATP client will still send `model` in the body; gateway will ignore it if reverted.
- **ATP client:** No change required for rollback; it already sends `model` and handles status/body. To stop using the chain, set `OPENCLAW_MODEL_CHAIN` to a single model.

---

## 15. OpenClaw repo: implementation checklist

Apply these in the **OpenClaw repository** (the one that builds the gateway image).

### 1) Locate the `/v1/responses` handler

- Search for: `responses`, `openresponses`, `v1/responses`, or the route that handles `POST` for the OpenResponses API.
- Identify: request body parsing (e.g. `req.body`, Zod schema, or similar). Confirm whether `body.model` is already read.

### 2) Request-body `model`

- If **not** parsed: in the handler, read `model` from the request body (e.g. `const model = body?.model ?? config?.agents?.defaults?.model?.primary`).
- **Supported set:** Build a list from config: `agents.defaults.model.primary` + `agents.defaults.model.fallbacks` (array). Optionally allow an alias (e.g. `openclaw` → primary). Any other value = unsupported.
- If request has `model` and it is **in** the supported set → use it for the provider call.
- If request has `model` and it is **not** in the supported set → return **400** with body e.g. `{ "error": "model not supported", "requested": "<id>" }`. Log: `gateway model not supported requested=<id>`.
- If request has no `model` or empty → use config default (primary). Log: `gateway request model=default` (or `model=<primary>`).

### 3) Map model to provider

- Where the gateway calls the LLM provider, pass the **resolved** model id (the one from the request or default). Ensure the same id is used for provider selection (e.g. `openai/gpt-4o-mini` → OpenAI client with that model). Log: `gateway effective model=<id> provider=<name>`.

### 4) Provider failures → non-2xx

- In the code path that calls the provider (or handles its response/exception):
  - **Rate limit** (provider 429 or SDK/error message containing "rate limit", "too many requests") → set gateway response **429**, body optional `{ "error": "rate limit" }`. Log: `gateway provider error status=429 reason=rate limit`.
  - **Credit / payment** (402 or message "insufficient credit", "payment required", "quota exceeded") → set gateway response **402** or **503**, body optional. Log: `gateway provider error reason=insufficient credit`.
  - **Timeout** → **504** or **408**. Log: `gateway provider error reason=timeout`.
  - **Connection / unavailable** → **503**. Log: `gateway provider error reason=unavailable`.
  - **Other upstream 5xx or rejection** → **502** or **503**. Log: `gateway provider error status=<code> reason=...`.
- Do **not** return 200 and put the provider’s error text in the success payload. Return a non-2xx status so ATP never treats the run as successful.

### 5) No fake success

- After receiving the provider response, if it is an error, empty, or a known placeholder/error string (e.g. "insufficient credit", "rate limit"), do not send 200. Return the appropriate non-2xx and optionally `{ "error": "..." }`.

### 6) Logging

- **Recommended single line per request** (makes debugging much easier):
  ```
  OpenClaw request requested_model=<from body or "default"> effective_model=<resolved id> provider=<openai|anthropic|...>
  ```
  Example: `OpenClaw request requested_model=openai/gpt-4o-mini effective_model=openai/gpt-4o-mini provider=openai`
- At request start: `gateway request model=<requested or "default">`.
- After resolving: `gateway effective model=<id> provider=<name>`.
- On unsupported model: `gateway model not supported requested=<id>`.
- On provider failure: `gateway provider error status=<code> reason=<short reason>`.
- On success: `gateway response status=200` (or log completion). On failure: `gateway response status=<code> reason=...`.

---

## 16. Verification script (manual)

From ATP repo, run **`scripts/openclaw/verify_gateway_model_routing.sh`** with gateway base URL and token. It tests (1) valid supported model → 200, (2) unsupported model → 400 with body indicating model error.

```bash
OPENCLAW_GATEWAY_URL=http://127.0.0.1:8080 OPENCLAW_API_TOKEN=<token> ./scripts/openclaw/verify_gateway_model_routing.sh
```

**Exact verification steps:**

| # | Test | Command / action | Expected |
|---|------|------------------|----------|
| 1 | Valid supported model → 200 | `POST /v1/responses` with `model: "<primary or first fallback>"`, valid `input` | 200, body has output; logs show `effective model=<requested>` |
| 2 | Unsupported model → 400 | `POST /v1/responses` with `model: "unsupported/fake"` | 400, body contains "model" and "not supported" (or similar) |
| 3 | Credit/payment failure → non-200 | Use exhausted-credit account or mock | 402 or 503, not 200 |
| 4 | Rate limit → 429 | Trigger provider rate limit or mock | 429 |
| 5 | Provider/upstream failure → non-200 | Unavailable provider or mock 5xx | 502 or 503, not 200 |
| 6 | No fake success on failed generation | Any of the above failure cases | Gateway must not return 200 with error text as content |

---

*Gateway implementation lives in the OpenClaw repository. This document is the compatibility contract; implement the minimal hardening there and verify with the steps in §9, §13, and §16.*
