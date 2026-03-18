# File List: Multi-Agent Implementation

**Version:** 1.0  
**Date:** 2026-03-15

---

## Created Files

| File | Reason |
|------|--------|
| `docs/agents/multi-agent/README.md` | Executive summary, design principles, agent list |
| `docs/agents/multi-agent/AGENT_DEFINITIONS.md` | Purpose, scope, exclusions, owned files per agent |
| `docs/agents/multi-agent/SHARED_OUTPUT_SCHEMA.md` | Shared output format for all agents |
| `docs/agents/multi-agent/ROUTING_CONFIG.md` | Routing rules, keywords, save subdirs |
| `docs/agents/multi-agent/HOW_TO_USE.md` | How to route, invoke, review; fit with OpenClaw/Cursor |
| `docs/agents/multi-agent/MAC_MINI_READINESS.md` | Why design helps migration; what stays/changes |
| `docs/agents/multi-agent/IMPLEMENTATION_PLAN.md` | Phased implementation plan |
| `docs/agents/multi-agent/FILE_LIST.md` | This file |
| `backend/app/services/agent_routing.py` | `route_task`, `get_save_subdir`, `get_file_prefix` |
| `docs/agents/telegram-alerts/README.md` | Artifact dir for Telegram and Alerts agent |
| `docs/agents/execution-state/README.md` | Artifact dir for Execution and State agent |
| `docs/agents/trading-signal/README.md` | Scaffold dir for Trading Signal agent |
| `docs/agents/system-health/README.md` | Scaffold dir for System Health agent |
| `docs/agents/architecture/README.md` | Scaffold dir for Architecture and Refactor agent |

---

## Modified Files

| File | Change | Reason |
|------|--------|--------|
| `backend/app/services/openclaw_client.py` | Added `AGENT_OUTPUT_SECTIONS`, `parse_agent_output_sections`, `build_telegram_alerts_prompt`, `build_execution_state_prompt`, `_AGENT_STRUCTURED_OUTPUT_INSTRUCTION` | Multi-agent schema and Telegram/Execution prompts |
| `backend/app/services/agent_callbacks.py` | Added `sections` param to `_validate_openclaw_note` and `_make_openclaw_validator`; added `use_agent_schema` to `_apply_via_openclaw` and `_make_openclaw_callback`; added `sections` to `_call_openclaw_once`; wired agent routing into `select_default_callbacks_for_task`; fixed `_verify_openclaw_solution` (missing `root`) | Support agent output schema; route Telegram/Execution tasks to specialized agents |

---

## Unchanged (by design)

- Trading engine, order execution, Crypto.com trade placement
- Production Telegram sending logic
- PostgreSQL schema, dashboard
- OpenClaw hosting (remains on LAB)
