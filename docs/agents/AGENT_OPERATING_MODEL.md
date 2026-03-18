# Agent Operating Model — Channel Separation

**Version:** 2.0  
**Date:** 2026-03-15

---

## Overview

ATP uses distinct Telegram contexts. Each has a clear responsibility. Operators must use the correct context for each type of task.

**Commands do not work in HILOVIVO3.0.** Use ATP Control (private group or direct chat) for all interactive commands.

---

## Telegram Context Responsibilities

### ATP Control (private group or direct bot chat)

- **What:** Command/control interface for ATP agent operations
- **Use for:**
  - `/help` — show all commands
  - `/runtime-check` — verify runtime dependencies
  - `/investigate <problem>` — describe an issue; backend auto-selects the best agent
  - `/agent <agent_name> <problem>` — force a specific agent (Sentinel, Ledger, etc.)
  - All other dashboard commands (portfolio, watchlist, signals, etc.)
- **Setup:** Create a private group or use direct chat. Add the bot. Add your group ID or user ID to `TELEGRAM_AUTH_USER_ID` or `TELEGRAM_CHAT_ID`. See [ATP_CONTROL_SETUP.md](ATP_CONTROL_SETUP.md).

### HILOVIVO3.0

- **What:** Alerts-only channel (signals, orders, reports)
- **Use for:** Outbound alerts only — no commands
- **Not for:** Interactive commands — use ATP Control

### AWS_alerts

- **What:** Technical alerts / health / anomaly channel
- **Use for:** System health, anomalies, scheduler alerts, ops notifications
- **Not for:** Main conversation or agent investigations

### Claw

- **What:** OpenClaw's own Telegram bot and native command interface
- **Use for:** OpenClaw-native commands such as `/new`, `/reset`, `/status`, `/context`
- **Not for:** ATP agent commands — use ATP Control

---

## Operator Guidance

| Task | Context | Example |
|------|---------|---------|
| Investigate repeated BTC alerts | ATP Control | `/investigate repeated BTC alerts` |
| Force Sentinel to investigate alerts | ATP Control | `/agent sentinel investigate repeated BTC alerts` |
| Check runtime dependencies | ATP Control | `/runtime-check` |
| View system health alerts | AWS_alerts | Read-only; alerts are pushed here |
| View trading signals | HILOVIVO3.0 | Read-only; alerts are pushed here |
| OpenClaw session control | Claw | `/new`, `/reset`, `/status`, `/context` |

---

## Related Docs

- [ATP_CONTROL_SETUP.md](ATP_CONTROL_SETUP.md) — setup guide for ATP Control
- [TELEGRAM_AGENT_COMMANDS.md](TELEGRAM_AGENT_COMMANDS.md) — command reference and parsing rules
- [multi-agent/README.md](multi-agent/README.md) — agent structure and routing
