# Agent Operating Model — Channel Separation

**Version:** 1.0  
**Date:** 2026-03-15

---

## Overview

ATP uses three distinct Telegram channels. Each has a clear responsibility. Operators must use the correct channel for each type of task.

---

## Telegram Channel Responsibilities

### Claw

- **What:** OpenClaw's own Telegram bot and native command interface
- **Use for:** OpenClaw-native commands such as `/new`, `/reset`, `/status`, `/context`
- **Not for:** Main operator channel for ATP agents — agent investigations and routing happen in HILOVIVO3.0

### HILOVIVO3.0

- **What:** ATP backend operator channel for agent commands
- **Use for:**
  - `/investigate <problem>` — describe an issue; backend auto-selects the best agent
  - `/agent <agent_name> <problem>` — force a specific agent (Sentinel, Ledger, etc.)
  - `/runtime-check` — verify runtime dependencies
- **Backend:** Routes these tasks to Sentinel, Ledger, and other agents

### AWS_alerts

- **What:** Technical alerts / health / anomaly channel
- **Use for:** System health, anomalies, scheduler alerts, ops notifications
- **Not for:** Main conversation channel for agent investigations — use HILOVIVO3.0 for that

---

## Operator Guidance

| Task | Channel | Example |
|------|---------|---------|
| Investigate repeated BTC alerts | HILOVIVO3.0 | `/investigate repeated BTC alerts` |
| Force Sentinel to investigate alerts | HILOVIVO3.0 | `/agent sentinel investigate repeated BTC alerts` |
| Check runtime dependencies | HILOVIVO3.0 | `/runtime-check` |
| OpenClaw session control | Claw | `/new`, `/reset`, `/status`, `/context` |
| View system health alerts | AWS_alerts | Read-only; alerts are pushed here |

---

## Related Docs

- [TELEGRAM_AGENT_COMMANDS.md](TELEGRAM_AGENT_COMMANDS.md) — command reference and parsing rules
- [multi-agent/README.md](multi-agent/README.md) — agent structure and routing
