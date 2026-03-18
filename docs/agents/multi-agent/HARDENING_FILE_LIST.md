# Multi-Agent Hardening — File List

**Version:** 1.0  
**Date:** 2026-03-15

---

## Modified Files

| File | Change |
|------|--------|
| `backend/app/services/agent_routing.py` | Added `route_task_with_reason()`; explicit logging in `route_task()`; new keywords (repeated alerts, missing alerts, approval noise, dashboard mismatch, db mismatch, state reconciliation) |
| `backend/app/services/agent_callbacks.py` | Fixed `_writable_bug_investigations_dir` → `_note_dir_for_subdir`; use `route_task_with_reason`; WARNING on agent init failure; `agent_selected` / `agent_routing_fallback` logs; agent validator: require all 9 sections, min 500 chars, critical section checks; observability logs (`openclaw_fallback`, `openclaw_apply_success`) |
| `backend/app/services/openclaw_client.py` | Hardened `build_telegram_alerts_prompt` and `build_execution_state_prompt` with scope lists, check items, typical issues |
| `docs/agents/multi-agent/HOW_TO_USE.md` | Added example issue-to-agent mappings; failure/fallback behavior section |
| `docs/agents/telegram-alerts/README.md` | (unchanged; examples in EXAMPLES.md) |
| `docs/agents/execution-state/README.md` | (unchanged; examples in EXAMPLES.md) |

---

## Created Files

| File | Purpose |
|------|---------|
| `docs/agents/telegram-alerts/EXAMPLES.md` | Issue-to-agent mappings, example output, validation checklist |
| `docs/agents/execution-state/EXAMPLES.md` | Issue-to-agent mappings, example output, validation checklist |
| `docs/agents/multi-agent/HARDENING_AUDIT_SUMMARY.md` | Executive summary of gaps and fixes |
| `docs/agents/multi-agent/HARDENING_FILE_LIST.md` | This file |
