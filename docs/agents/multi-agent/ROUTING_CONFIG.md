# Agent Routing Config

Explicit mapping from issue types (Notion task type, title, details, area) to the correct agent.

---

## Routing rules (priority order)

| Priority | Condition | Agent |
|----------|-----------|-------|
| 1 | `type` in (telegram, alerts, notification) OR title/details/area contains: telegram, alert, notification, throttle, dedup, kill switch, TELEGRAM, chat_id | **Telegram and Alerts** |
| 2 | `type` in (execution, order, sync) OR title/details/area contains: order, execution, sync, exchange, EXECUTED, CANCELED, open orders, order history, lifecycle | **Execution and State** |
| 3 | `type` in (signal, trading) OR title/details/area contains: signal, buy/sell, strategy, watchlist, throttle, RSI, MA | **Trading Signal** |
| 4 | `type` in (health, monitoring, infra) OR title/details/area contains: health, nginx, 502, 504, SSM, docker, market updater, disk | **System Health** |
| 5 | `type` in (doc, documentation) OR title/details/area contains: doc, runbook, readme, cursor rule | **Docs and Rules** |
| 6 | `type` in (architecture, refactor) OR title/details/area contains: architecture, refactor, dead code, tech debt | **Architecture and Refactor** |
| 7 | Fallback | **Generic** (existing OpenClaw generic prompt) |

---

## Implementation

- **Code:** `backend/app/services/agent_routing.py` — `route_task(prepared_task) -> agent_id | None`
- **Eligibility:** Each agent has `_is_<agent>_eligible(prepared_task)` in `agent_callbacks.py`
- **Callback pack:** When agent matches, return pack with agent-specific prompt builder and save subdir

---

## Save subdirs per agent

| Agent | Save subdir | File prefix |
|-------|-------------|-------------|
| Telegram and Alerts | docs/agents/telegram-alerts | notion-telegram |
| Execution and State | docs/agents/execution-state | notion-execution |
| Trading Signal | docs/agents/trading-signal | notion-signal |
| System Health | docs/agents/system-health | notion-health |
| Docs and Rules | docs/agents/generated-notes | notion-task |
| Architecture and Refactor | docs/agents/architecture | notion-arch |
