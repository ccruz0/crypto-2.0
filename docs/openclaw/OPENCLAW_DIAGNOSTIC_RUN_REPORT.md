# OPENCLAW DIAGNOSTIC REPORT

**Date:** 2026-03-04  
**Repo:** automated-trading-platform  
**Source:** `docs/openclaw/README.md` — official diagnostic script.

---

## Script executed

**Path:** `scripts/openclaw/run_openclaw_diagnosis_local.sh`  
**Command (from repository root):** `bash scripts/openclaw/run_openclaw_diagnosis_local.sh`

---

## Full script output

```
=== OpenClaw diagnosis (local curl + optional SSM) ===
Base URL: https://dashboard.hilovivo.com

--- 1) GET https://dashboard.hilovivo.com/openclaw/ ---
HTTP status: 401

--- 2) GET https://dashboard.hilovivo.com/openclaw/ws ---
HTTP status: 401

--- 3) SSM (Dashboard PROD) ---
Dashboard (i-087953603011543c5) PingStatus: ConnectionLost

=== Summary ===
Proxy and upstream: OK (HTTP 401 — auth or redirect as expected)
WebSocket endpoint: OK (HTTP 401)
Classification: E. Everything appears healthy (from public URLs)
NEXT ACTION: Open https://dashboard.hilovivo.com/openclaw/ in browser; use Basic auth if prompted.
Note: SSM to Dashboard is ConnectionLost. To run server-side checks see docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md
```

**Exit code:** 0

---

## Detected state

**STATE A**

---

## Explanation

- **https://dashboard.hilovivo.com/openclaw/** → HTTP **401** (Unauthorized; `WWW-Authenticate: Basic realm="OpenClaw"`).
- **https://dashboard.hilovivo.com/openclaw/ws** → HTTP **401** (same).

Technically this means:

1. The nginx `/openclaw` block is present and loaded on the dashboard host (no 404).
2. The dashboard can reach the OpenClaw upstream (no 502/504).
3. The upstream (OpenClaw on LAB) is responding and requiring Basic authentication.
4. Both the main UI and the WebSocket path are reachable through the proxy.

SSM to the Dashboard instance (i-087953603011543c5) is **ConnectionLost**; that does not affect public URL reachability. Server-side checks (e.g. `run_openclaw_check_via_ssm.sh`) require SSM to be Online (see `docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md`).

---

## NEXT ACTION

**Instruction:** Open **https://dashboard.hilovivo.com/openclaw/** in the browser and authenticate with the configured Basic auth credentials.

No nginx or upstream changes are required for normal access; the 401 is expected until the user supplies credentials.
