# Telegram Agent Commands — Multi-Agent Operator Interface

**Version:** 2.0  
**Date:** 2026-03-15

Single Telegram bot; backend routes tasks to the correct agent. No separate bots per agent.

---

## Telegram Context Responsibilities

| Context | Purpose | Use For |
|---------|---------|---------|
| **ATP Control** | Command/control interface (private group or direct chat) | `/investigate`, `/agent`, `/runtime-check`, `/help` — all agent commands |
| **HILOVIVO3.0** | Alerts-only channel | Signals, orders, reports — no commands |
| **Claw** | OpenClaw native bot | OpenClaw-native commands: `/new`, `/reset`, `/status`, `/context` |
| **AWS_alerts** | Technical alerts channel | System health, anomalies, ops — read-only |

**Rule:** Agent operations must happen in **ATP Control** (private group or direct chat). HILOVIVO3.0 is alerts-only. See [ATP_CONTROL_SETUP.md](ATP_CONTROL_SETUP.md).

---

## Commands

| Command | Purpose | Context |
|---------|---------|---------|
| `/investigate <problem text>` | Describe an issue; backend auto-selects the best agent | ATP Control |
| `/agent <agent_name> <problem text>` | Force a specific agent | ATP Control |
| `/runtime-check` | Verify runtime dependencies (pydantic, etc.) | ATP Control |
| `/help` | Show all commands including agent section | ATP Control |

---

## Parsing Rules

### /investigate

- Everything after the command is the problem text
- Whitespace is trimmed
- Empty input → usage example

### /agent

- First token after `/agent` = agent name (case-insensitive)
- Remaining text = problem text
- Empty problem → usage with valid agent names
- Unknown agent → error plus valid agent list

---

## Agent Names and Roles

| Name | Role | Status |
|------|------|--------|
| **Sentinel** | Alerts, Telegram, duplicates, missing notifications, approval noise, throttling | Active |
| **Ledger** | Orders, execution state, exchange/DB/dashboard mismatch, lifecycle | Active |
| Archivist | Docs, rules, runbooks, docs-vs-code mismatch | Planned |
| Architect | System design, refactor boundaries, structural review | Planned |
| Analyst | Signal behavior, threshold tuning, strategy analysis | Planned |

---

## Examples

```
/investigate repeated BTC alerts
/investigate order not in open orders
/investigate dashboard mismatch for open orders
/agent sentinel investigate repeated alerts
/agent ledger investigate order not in open orders
/agent archivist compare docs vs code for alert rules
```

---

## Acknowledgment Format

### On accepted task

```
Task received
Agent selected: <name>
Reason: <route reason or "forced by operator">
Mode: analysis
```

### On unclear routing (/investigate)

```
No clear specialist matched.

Suggested agents:
• Sentinel — alerting issues
• Ledger — order/execution issues

Try:
/agent sentinel investigate repeated alerts
/agent ledger investigate missing order state
```

### On unknown agent (/agent)

```
Unknown agent: <name>
Valid agents: sentinel, ledger, archivist, architect, analyst
```

---

## Routing Model

- **/investigate:** Backend uses `route_task_with_reason()` — keywords and task type.
- **/agent:** Operator forces agent; routing is bypassed.
- One bot; backend routes internally. No parallel agent system.

---

## Fallback Behavior

| Situation | Behavior |
|-----------|----------|
| No match for /investigate | Clarification message with suggested agents |
| Forced agent not active | "Agent X is planned but not yet active" |
| OpenClaw not configured | Apply fails; error returned |
| Parse error | Usage message |

---

## Future Commands (Not Implemented)

- `/status` — agent/scheduler status
- `/last` — last run summary
- `/task` — task history

---

## Mac Mini Readiness

The Telegram command layer is host-agnostic. When OpenClaw moves from LAB to Mac Mini, only `OPENCLAW_API_URL` changes. Commands, routing, and agent mapping stay identical. The bot continues to use the same backend API.
