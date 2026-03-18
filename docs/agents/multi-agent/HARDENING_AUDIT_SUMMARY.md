# Multi-Agent Hardening — Audit Summary

**Version:** 1.0  
**Date:** 2026-03-15

---

## Executive Summary of Gaps Found

### 1. Routing

- **Gap:** Routing decisions were implicit; no log of why an agent was selected.
- **Gap:** Agent routing init failure was logged at DEBUG; fallback was silent.
- **Fix:** Added `route_task_with_reason()` returning `(agent_id, reason)`; explicit `agent_selected` and `agent_routing_init_failed` logs at INFO/WARNING.

### 2. Fallback Handling

- **Gap:** When imports failed, `logger.debug` hid the issue; no diagnostic path.
- **Fix:** Switched to `logger.warning` with `exc_info=True`; added diagnostic message: "ensure agent_routing and openclaw_client import (httpx, etc.)".

### 3. Agent Output Schema and Validator

- **Gap:** Validator required "at least one" section; low-quality outputs could pass.
- **Gap:** No requirement for critical sections (Root Cause, Proposed Minimal Fix, Cursor Patch Prompt) to have meaningful content.
- **Fix:** Agent schema now requires all 9 sections; minimum body 500 chars; critical sections must have ≥15 chars (or valid Risk Level); actionable error messages.

### 4. Telegram and Alerts Agent

- **Gap:** Prompt did not explicitly cover repeated alerts, missing alerts, approval noise, docs-vs-code mismatches.
- **Fix:** Expanded prompt with scope list, check items, and typical issues; added keywords to routing.

### 5. Execution and State Agent

- **Gap:** Prompt did not explicitly cover exchange vs DB vs dashboard mismatches, lifecycle state, rendering/state reconciliation.
- **Fix:** Expanded prompt with scope list, check items; added "dashboard mismatch", "db mismatch", "state reconciliation" to routing keywords.

### 6. Observability

- **Gap:** No structured logs for selection, fallback, or validation outcome.
- **Fix:** Added `agent_selected`, `agent_routing_fallback`, `openclaw_fallback`, `openclaw_apply_success`, `agent_output_validation: PASSED/FAILED`.

### 7. Bug Fix

- **Gap:** `validate_bug_investigation_task` called `_writable_bug_investigations_dir()` which did not exist.
- **Fix:** Use `_note_dir_for_subdir("docs/agents/bug-investigations")` instead.

---

## Recommended Next Steps

1. **Run a live test** with a Telegram and an Execution task; confirm routing, apply, and validation logs.
2. **Add a health check** or diagnostic endpoint that verifies agent_routing and openclaw_client import without running a task.
3. **Consider cheap model chain** for Telegram/Execution agents (cost optimization) if not already configured.
4. **Extend examples** with real task IDs and outputs from production runs (sanitized).
