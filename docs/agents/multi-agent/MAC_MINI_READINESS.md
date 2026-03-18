# Future Mac Mini Readiness

**Version:** 1.0  
**Date:** 2026-03-15

---

## Why This Design Makes the Host Migration Easier

The multi-agent structure is **host-agnostic**:

1. **Routing and prompts live in ATP:** `agent_routing.py`, `openclaw_client.py`, and `agent_callbacks.py` contain all routing rules, prompt builders, and schema. These stay in the repo regardless of where OpenClaw runs.

2. **Single configuration change:** Moving OpenClaw from LAB to Mac Mini requires only updating `OPENCLAW_API_URL` (and optionally `OPENCLAW_API_TOKEN` if the gateway changes). No code changes.

3. **No trading coupling:** Agents never touch order placement, exchange sync, or Telegram send logic. The migration does not affect production trading.

4. **Structured output is portable:** The shared schema (Issue Summary, Root Cause, Cursor Patch Prompt, etc.) is defined in docs and enforced in code. It does not depend on the OpenClaw host.

5. **Callback flow unchanged:** `select_default_callbacks_for_task` → `route_task` → prompt builder → OpenClaw → save note. The HTTP client (`openclaw_client.py`) talks to whatever URL is configured.

---

## What Remains Unchanged When OpenClaw Moves

| Component | Location | Change on migration |
|-----------|----------|----------------------|
| Agent definitions | `docs/agents/multi-agent/AGENT_DEFINITIONS.md` | None |
| Routing config | `docs/agents/multi-agent/ROUTING_CONFIG.md` | None |
| Shared output schema | `docs/agents/multi-agent/SHARED_OUTPUT_SCHEMA.md` | None |
| Routing logic | `backend/app/services/agent_routing.py` | None |
| Prompt builders | `backend/app/services/openclaw_client.py` | None |
| Callback selection | `backend/app/services/agent_callbacks.py` | None |
| Artifact dirs | `docs/agents/telegram-alerts/`, etc. | None |
| Validation logic | `_validate_openclaw_note`, `parse_agent_output_sections` | None |

---

## What Changes on Migration

| Item | Before (LAB) | After (Mac Mini) |
|------|--------------|------------------|
| `OPENCLAW_API_URL` | `http://172.31.3.214:8080` (or LAB host) | Mac Mini host (e.g. `http://192.168.x.x:8080`) |
| OpenClaw process | Runs on LAB | Runs on Mac Mini |
| Network path | Backend → LAB | Backend → Mac Mini (same LAN or VPN) |

---

## Migration Checklist (for later)

1. Deploy OpenClaw on Mac Mini.
2. Update `OPENCLAW_API_URL` in backend env (e.g. `.env`, SSM, or deployment config).
3. Verify connectivity: `curl -H "Authorization: Bearer $OPENCLAW_API_TOKEN" $OPENCLAW_API_URL/v1/responses` (or health endpoint).
4. Run a test task that routes to Telegram or Execution agent; confirm note is saved.
5. No changes to agent definitions, routing, or prompts.
