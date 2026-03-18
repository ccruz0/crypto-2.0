# Multi-Agent Operator Structure

**Version:** 1.0  
**Date:** 2026-03-15  
**Status:** First implementation — Telegram/Alerts and Execution/State agents active; others scaffolded.

---

## Executive Summary

The multi-agent operator system adds **specialized analysis agents** on top of the existing AWS/LAB setup. Agents are **not** for direct trading execution. They perform analysis, diagnosis, patch proposal, and verification for operational issues.

### Design principles

- **Additive:** No changes to trading engine, order execution, or production Telegram sending.
- **Localized:** Each agent has a clear scope, owned files, and exclusions.
- **Structured output:** All agents use a shared schema (issue summary, root cause, proposed fix, validation plan, cursor patch prompt).
- **Routing:** Explicit config maps issue types to the correct agent.
- **OpenClaw-hosted:** Agents run via OpenClaw on LAB; prompts and routing live in ATP.

### Agents (6 total)

| Agent | Purpose | Status |
|-------|---------|--------|
| **Telegram and Alerts** | Alert delivery, throttle, dedup, kill switch, channel config | Implemented |
| **Execution and State** | Order lifecycle, sync, exchange state, DB consistency | Implemented |
| Trading Signal | Signal logic, strategy, throttle, watchlist | Scaffolded |
| System Health | Market updater, backend, nginx, SSM, disk | Scaffolded |
| Docs and Rules | Runbooks, architecture, cursor rules | Scaffolded |
| Architecture and Refactor | Code structure, dead code, tech debt | Scaffolded |

### How it fits today

- **Notion task** → `select_default_callbacks_for_task` → **agent routing** → if Telegram/Execution eligible → agent-specific prompt → OpenClaw → structured note → validate → Cursor handoff.
- **Unchanged:** Trading, exchange sync, Telegram send logic, dashboard, PostgreSQL.
- **OpenClaw:** Remains on LAB; receives prompts from backend; returns structured output.

### Mac Mini readiness

The agent structure is **host-agnostic**. When OpenClaw moves from LAB to Mac Mini, only `OPENCLAW_API_URL` changes. Agent definitions, routing, prompts, and output schema stay identical.

### Telegram channel separation

- **ATP Control** — command/control interface (private group or direct chat) for `/investigate`, `/agent`, `/runtime-check`
- **HILOVIVO3.0** — alerts-only; no commands
- **Claw** — OpenClaw native bot (`/new`, `/reset`, `/status`, `/context`)
- **AWS_alerts** — technical alerts only

See [AGENT_OPERATING_MODEL.md](../AGENT_OPERATING_MODEL.md), [ATP_CONTROL_SETUP.md](../ATP_CONTROL_SETUP.md), and [TELEGRAM_AGENT_COMMANDS.md](../TELEGRAM_AGENT_COMMANDS.md).

---

## Quick reference

- **Agent definitions:** [AGENT_DEFINITIONS.md](AGENT_DEFINITIONS.md)
- **Shared output schema:** [SHARED_OUTPUT_SCHEMA.md](SHARED_OUTPUT_SCHEMA.md)
- **Routing config:** [ROUTING_CONFIG.md](ROUTING_CONFIG.md)
- **How to use:** [HOW_TO_USE.md](HOW_TO_USE.md)
- **Implementation plan:** [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)
- **Mac Mini readiness:** [MAC_MINI_READINESS.md](MAC_MINI_READINESS.md)
- **File list:** [FILE_LIST.md](FILE_LIST.md)
- **Hardening audit:** [HARDENING_AUDIT_SUMMARY.md](HARDENING_AUDIT_SUMMARY.md)
- **Hardening file list:** [HARDENING_FILE_LIST.md](HARDENING_FILE_LIST.md)
- **Live validation runbook:** [LIVE_VALIDATION_RUNBOOK.md](LIVE_VALIDATION_RUNBOOK.md)
- **First live run readiness:** [FIRST_LIVE_RUN_READINESS.md](FIRST_LIVE_RUN_READINESS.md)
- **First live run worksheet:** [FIRST_LIVE_RUN_WORKSHEET.md](FIRST_LIVE_RUN_WORKSHEET.md)
- **Acceptance checklist:** [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md)
- **Real-world test tasks:** [REAL_WORLD_TEST_TASKS.md](REAL_WORLD_TEST_TASKS.md)
- **Telegram commands:** [../TELEGRAM_AGENT_COMMANDS.md](../TELEGRAM_AGENT_COMMANDS.md)
- **Channel separation:** [../AGENT_OPERATING_MODEL.md](../AGENT_OPERATING_MODEL.md)
