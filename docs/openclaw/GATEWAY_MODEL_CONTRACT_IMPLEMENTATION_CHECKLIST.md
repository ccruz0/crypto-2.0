# OpenClaw Gateway: Model Contract Implementation Checklist

**Context:** ATP is ready. The only remaining work is in the **OpenClaw repo** (`ccruz0/openclaw`). The gateway must implement the contract so ATP’s cheap-first fallback works end-to-end.

**Contract reference (ATP):** `docs/GATEWAY_MODEL_ROUTING_AND_FAILOVER_COMPATIBILITY.md`  
**Verification script (ATP):** `scripts/openclaw/verify_gateway_model_routing.sh`

---

## 0. 10-second diagnostic (does the gateway read `body.model`?)

From any machine that can reach the gateway (set `OPENCLAW_GATEWAY_URL` and `OPENCLAW_API_TOKEN` first):

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST "$OPENCLAW_GATEWAY_URL/v1/responses" \
  -H "Authorization: Bearer $OPENCLAW_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "model": "unsupported/fake-model-id",
        "input": "gateway model routing test"
      }'
```

| Result | Meaning |
|--------|--------|
| **400** | Gateway contract implemented correctly (read body.model, validated, rejected fake model). |
| **200** | Gateway is ignoring model (e.g. uses fixed `DEFAULT_MODEL`); implement contract in OpenClaw repo. |
| **401** | Token wrong or missing — check `OPENCLAW_API_TOKEN`. |
| **404** | Wrong path — in OpenClaw repo search for `/responses` or `OpenResponses`. |
| **000** or connection error | URL not set or gateway unreachable — set `OPENCLAW_GATEWAY_URL` and ensure the machine can reach it. |

Optional: if the gateway logs the requested model, run `docker logs openclaw | grep requested_model` and confirm you see `requested_model=unsupported/fake-model-id`.

---

## 1. Open the correct repo

- **File → Open Folder → `ccruz0/openclaw`**
- Do **not** implement this in `automated-trading-platform`; gateway code lives in OpenClaw.

---

## 2. Find the responses handler

Search for:

- `/v1/responses`
- `OpenResponses`
- `responses`

Look for something like:

- `app.post("/v1/responses")`
- `router.post("/v1/responses")`

---

## 3. Check whether the handler uses `body.model`

**Case A (best):** Already has `const { model } = req.body` (or equivalent).

- Verify that `model` is actually used when calling the provider.
- Verify that an unsupported model is rejected (e.g. 400), not silently replaced.

**Case B (most likely):** Gateway ignores `model` and uses a fixed default.

- Example: `const model = process.env.DEFAULT_MODEL`
- Change to: `const requestedModel = body.model || DEFAULT_MODEL` (or config default).
- Validate `requestedModel` against the supported set; if not supported → return **400**.

---

## 4. Minimal correct gateway behavior

**Request example:**

```http
POST /v1/responses
Content-Type: application/json

{
  "model": "openai/gpt-4o-mini",
  "input": "test"
}
```

**Gateway logic:**

1. **Validate model**  
   `if (!supportedModels.includes(model)) return 400`  
   Body should indicate model is not supported / unknown / invalid (so ATP can treat as non-retryable or failover).

2. **Call provider** with the validated model.

3. **On provider failure** return one of:
   - **402** (payment required / insufficient credits)
   - **429** (rate limit)
   - **502** / **503** (bad gateway / unavailable)
   - **504** (gateway timeout)

   **Never:** **200** with an error message in the body. ATP relies on HTTP status for failover.

---

## 5. Run verification from ATP repo

After implementing the above:

```bash
# From automated-trading-platform repo
OPENCLAW_GATEWAY_URL=http://gateway:port \
OPENCLAW_API_TOKEN=token \
./scripts/openclaw/verify_gateway_model_routing.sh
```

**Expected:**

- Valid supported model → **200**
- Unsupported model → **400** (and body contains “model” and “not supported” or “unknown” or “invalid”)

---

## 6. Cost control (cheap-first order)

ATP’s recommended chain (so you don’t burn credits while debugging):

1. `gpt-4o-mini`
2. `claude-3.5-haiku`
3. `claude-3.5-sonnet`
4. `gpt-4o`
5. `claude-sonnet-4`

Gateway only needs to honor the requested model and fail clearly; ATP handles the chain.

---

## 7. Recommended log line (add after it works)

One structured log line per request makes debugging much easier, e.g.:

```
OpenClaw request requested_model=openai/gpt-4o-mini effective_model=openai/gpt-4o-mini provider=openai
```

---

## Summary

| ATP (this repo) | OpenClaw repo |
|-----------------|----------------|
| Contract doc ✅ | Implement: read `body.model`, validate, use it |
| Verification script ✅ | Return 400 for unsupported model |
| Sends model, handles fallback ✅ | Return 402/429/502/503/504 on provider failure, never 200 with error |
| Not the blocker | **This is the only remaining piece** |
