# Multi-Agent Implementation Plan

**Version:** 1.0  
**Date:** 2026-03-15

---

## Phase 1: Foundation (Done)

- [x] Define 6 agents in `AGENT_DEFINITIONS.md`
- [x] Define shared output schema in `SHARED_OUTPUT_SCHEMA.md`
- [x] Define routing rules in `ROUTING_CONFIG.md`
- [x] Implement `agent_routing.py` with `route_task`, `get_save_subdir`, `get_file_prefix`
- [x] Add `AGENT_OUTPUT_SECTIONS` and `parse_agent_output_sections` to `openclaw_client.py`
- [x] Add `build_telegram_alerts_prompt` and `build_execution_state_prompt`
- [x] Add `sections` parameter to `_validate_openclaw_note` and `_make_openclaw_validator`
- [x] Add `use_agent_schema` to `_apply_via_openclaw` and `_make_openclaw_callback`
- [x] Wire agent routing into `select_default_callbacks_for_task` for Telegram and Execution
- [x] Create `docs/agents/telegram-alerts/` and `docs/agents/execution-state/` artifact dirs
- [x] Fix `_verify_openclaw_solution` (missing `root` definition)
- [x] Create HOW_TO_USE.md, MAC_MINI_READINESS.md, FILE_LIST.md

---

## Phase 2: Scaffolded Agents (Current)

- [x] Create `docs/agents/trading-signal/`, `docs/agents/system-health/`, `docs/agents/architecture/`
- [ ] Add `build_trading_signal_prompt`, `build_system_health_prompt`, `build_architecture_prompt` (when needed)
- [ ] Wire routing for Trading Signal, System Health, Architecture when prompts are ready
- [ ] Docs and Rules reuses `docs/agents/generated-notes` and existing documentation prompt

---

## Phase 3: Future Enhancements (Optional)

- [ ] Add agent-specific cheap model chain for Telegram/Execution (cost optimization)
- [ ] Add telemetry: which agent handled which task, success rate
- [ ] Add Cursor Bridge integration for one-click “apply agent fix”
- [ ] Extend routing with repo_area `matched_rules` for finer control

---

## File Touch Points

| File | Role |
|------|------|
| `backend/app/services/agent_routing.py` | Routing logic |
| `backend/app/services/agent_callbacks.py` | Callback selection, apply/validate/verify |
| `backend/app/services/openclaw_client.py` | Prompts, schema, HTTP client |
| `docs/agents/multi-agent/*.md` | Definitions, schema, routing config, how-to |
