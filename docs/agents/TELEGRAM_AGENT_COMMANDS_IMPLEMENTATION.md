# Telegram Agent Commands — Implementation Summary

**Version:** 1.0  
**Date:** 2026-03-15

---

## Summary

First version of a Telegram command interface for the multi-agent operator system. Single bot; backend routes tasks through the existing routing framework. Commands: `/investigate`, `/agent`, `/runtime-check`, `/help` (agent section).

**Channel separation:** HILOVIVO3.0 is the main operator channel for ATP agent commands. Claw is OpenClaw-native. AWS_alerts is for technical alerts. See [AGENT_OPERATING_MODEL.md](AGENT_OPERATING_MODEL.md).

---

## File List

### Created

| File | Purpose |
|------|---------|
| `backend/app/services/agent_telegram_commands.py` | Command parsing, routing, apply/validate, help content |
| `docs/agents/TELEGRAM_AGENT_COMMANDS.md` | Operator documentation |
| `docs/agents/TELEGRAM_AGENT_COMMANDS_IMPLEMENTATION.md` | This file |

### Modified

| File | Change |
|------|--------|
| `backend/app/services/telegram_commands.py` | Added `/investigate` and `/agent ` handlers; appended agent section to `/help`; added investigate/agent to bot command menu |

---

## Implemented Now

- `/investigate <problem text>` — auto-route via `route_task_with_reason`
- `/agent <agent_name> <problem text>` — force agent (Sentinel, Ledger)
- `/help` — includes multi-agent section
- Parsing: predictable, case-insensitive agent names
- Acknowledgment format: Task received, Agent selected, Reason, Mode
- Completion: Run complete, Validation, Summary, Next action
- Logging: `telegram_command_received`, `command`, `selected_agent`, `route_reason`, `routing=automatic|forced`

---

## Planned (Not Implemented)

- `/status`, `/last`, `/task` — future commands
- Archivist, Architect, Analyst — return "planned but not yet active"
- Async apply (currently blocking)

---

## Mac Mini Readiness

The Telegram command layer is host-agnostic. When OpenClaw moves from LAB to Mac Mini, only `OPENCLAW_API_URL` changes. Commands, routing, and agent mapping stay identical.
