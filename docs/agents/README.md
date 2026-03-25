# Agents

The **`/docs/agents`** directory provides **structured context for autonomous agents** (Cursor, OpenClaw, or other development/execution tools) working on this repository. It is optimized for AI readability and decision-making, not only for human reading.

---

## Purpose

- **Cursor** — Development; uses repo + `.cursor/rules/`; docs under `/docs` are the single source of truth.
- **OpenClaw** — Autonomous execution; reads this repo (code + `/docs`) as the knowledge base.
- **Other agents** — Any tool that needs to understand the system, plan work, or apply changes safely should start from the agent docs.

This directory exists so agents can understand the system, know what not to break, and follow consistent procedures **without depending on prior conversations**.

---

## Contents (read order for agents)

| Document | Use |
|----------|-----|
| [**context.md**](context.md) | What the project does, main components, **critical modules to never break**, where docs and config live. |
| [**task-system.md**](task-system.md) | Canonical ATP lifecycle (Telegram → planned → in-progress → investigation → investigation-complete → patch approval → patching → awaiting-deploy-approval → deploy approval → deploying → smoke → done/blocked), plus planning/validation guidance. |
| [**notion-task-intake.md**](notion-task-intake.md) | How to read pending Notion tasks and turn them into actionable work; priority order; safe execution; use of system-map, context, task-system, decision-log. |
| [**task-preparation-flow.md**](task-preparation-flow.md) | How the agent selects the next task, infers repo area, claims it (planned → in-progress), and appends a plan. |
| [**task-execution-flow.md**](task-execution-flow.md) | Controlled execution aligned to canonical lifecycle, with injected callbacks and approval/deploy gates. |
| [**human-approval-gate.md**](human-approval-gate.md) | When execution may run automatically (low-risk) vs when human approval is required; trading/order/runtime/deploy blocked by default. |
| [**telegram-approval-flow.md**](telegram-approval-flow.md) | Canonical Telegram approval callbacks (patch/deploy/smoke) and legacy callback notes. |
| [**telegram-agent-console.md**](telegram-agent-console.md) | Read-only Telegram console for recent activity, pending approvals, and recent failures. |
| [**callback-selection.md**](callback-selection.md) | Which task types get which callbacks; documentation and monitoring triage as first safe pack. |
| [**strategy-analysis-callback.md**](strategy-analysis-callback.md) | Analysis-only callback for strategy/signal/alert improvement proposals with version metadata. |
| [**signal-performance-analysis-callback.md**](signal-performance-analysis-callback.md) | Analysis-only callback for historical signal-outcome performance proposals with confidence score. |
| [**profile-setting-analysis-callback.md**](profile-setting-analysis-callback.md) | Analysis-only callback for per-symbol/profile/side setting proposals with confidence score. |
| [**strategy-patch-callback.md**](strategy-patch-callback.md) | Controlled manual-only patch callback for allowlisted low-risk business-logic tuning. |
| [**agent-activity-log.md**](agent-activity-log.md) | Structured agent activity log (JSONL); event types, schema, and how to read it. |
| [**versioning-flow.md**](versioning-flow.md) | Version proposal → approval → release traceability across Notion, Telegram, activity logs, and changelog. |
| [**agent-scheduler.md**](agent-scheduler.md) | Scheduler cycle: one task per run; approval request or low-risk auto-execution; in-flight skip; recommended cron. |
| [**cursor-bridge/README.md**](cursor-bridge/README.md) | Cursor Execution Bridge: staging workspace, Cursor CLI invocation, diff capture, tests, Notion ingestion, PR creation. |
| [**notion-connection-check.md**](notion-connection-check.md) | Operational script to verify Notion connectivity (env, database metadata read, database query). |
| **README.md** (this file) | Overview of the agents directory and pointer to the rest of `/docs`. |

### Notion AI Task System — schema and prompts

| Document | Use |
|----------|-----|
| [**notion-ai-task-system-schema.md**](notion-ai-task-system-schema.md) | All properties the backend reads/writes on the AI Task System database; names, types, status values. |
| [**notion-task-fields-mapping.md**](notion-task-fields-mapping.md) | Mapping from form fields (Task Title, Description, Objective, etc.) to Notion properties and backend keys. |
| [**notion-test-status-property.md**](notion-test-status-property.md) | Test Status property: why it matters, setup, and deploy gate fallback. |
| [**notion-deploy-progress.md**](notion-deploy-progress.md) | Deploy Progress (0–100) for progress bar in Notion during deploy and smoke check. |
| [**CHATGPT_NOTION_PROMPT_STRUCTURE.md**](CHATGPT_NOTION_PROMPT_STRUCTURE.md) | **Estructura de prompts para Notion:** instrucciones para ChatGPT (u otro LLM) para generar prompts que creen propiedades en la base AI Task System con nombres exactos y tipos correctos. Incluye formato, tipos de Notion, lista de propiedades del backend y ejemplo listo para copiar. |

**Recommended first read for any agent:** [System map](../architecture/system-map.md) (components, APIs, data flow, dependencies), then [context.md](context.md).

---

## Single source of truth

- **GitHub** = documentation + code.
- **Notion** = projects, tasks, decisions (references this repo when needed).
- **Cursor** = development (edits code and docs here).
- **OpenClaw** = execution (reads this repo as the knowledge base).

All technical documentation lives under `/docs`. Agents should prefer `/docs` and the root [README.md](../../README.md) over external or chat-only context.

---

## Related

- [Architecture](../architecture/system-map.md) — System map (start here); [system overview](../architecture/system-overview.md).
- [Runbooks](../runbooks/deploy.md) — Deploy, restart, troubleshoot.
- [Infrastructure](../infrastructure/aws-setup.md), [Docker](../infrastructure/docker-setup.md).
- [Integrations](../integrations/crypto-api.md), [Operations](../operations/monitoring.md).
- [Decision log](../decision-log/README.md) — Record of important decisions.
