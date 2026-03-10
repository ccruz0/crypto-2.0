# Documentation — Single Source of Truth

**GitHub is the canonical source for all technical documentation** for the Automated Trading Platform. All architecture, runbooks, and system documentation live in this repository under `/docs`.

- **Notion** → projects, tasks, and decisions (references this repo when needed).
- **Cursor** → development (reads and updates docs here).
- **OpenClaw** → execution (reads this repo as the knowledge base).

---

## Directory Structure

| Directory | Purpose |
|-----------|---------|
| [**architecture**](architecture/) | System design, components, data flow |
| [**trading-strategy**](trading-strategy/) | Strategy logic, signals, risk, throttling |
| [**infrastructure**](infrastructure/) | AWS, Docker, runtime environment |
| [**runbooks**](runbooks/) | Deploy, restart, troubleshoot (procedures) |
| [**integrations**](integrations/) | External APIs (Crypto.com, Telegram, etc.) |
| [**operations**](operations/) | Monitoring, health checks, alerts |
| [**agents**](agents/) | AI-readable context: [context.md](agents/context.md), [task-system.md](agents/task-system.md); for autonomous agents (Cursor, OpenClaw) |
| [**decision-log**](decision-log/) | Record of significant technical decisions |

Additional existing folders (audit, aws, openclaw, portfolio, monitoring, etc.) remain; the canonical entry points above link to them where relevant.

---

## Quick Links

- [**System map**](architecture/system-map.md) — **Start here for agents**: components, APIs, data flow, dependencies.
- [System overview](architecture/system-overview.md)
- [AWS setup](infrastructure/aws-setup.md)
- [Docker setup](infrastructure/docker-setup.md)
- [Deploy runbook](runbooks/deploy.md)
- [Restart services](runbooks/restart-services.md)
- [Orchestration debugging](runbooks/PRODUCTION_ORCHESTRATION_DEBUGGING_GUIDE.md) — Log sources, keywords, and commands for debugging the agent orchestration pipeline in production.
- [Crypto.com API](integrations/crypto-api.md)
- [Monitoring](operations/monitoring.md)
- [Agent context](agents/context.md) — How agents should work in this repo.
- [Task system](agents/task-system.md) — Task lifecycle and validation.
- [Notion AI Task System schema & prompts](agents/notion-ai-task-system-schema.md) — Properties the backend uses; [field mapping](agents/notion-task-fields-mapping.md); [ChatGPT prompt structure](agents/CHATGPT_NOTION_PROMPT_STRUCTURE.md) for generating Notion setup prompts.
- [Decision log](decision-log/README.md)

---

## For Humans and AI Agents

- Documentation is written in clear Markdown.
- Use headings, tables, and code blocks for structure.
- Cross-link between docs with relative paths (e.g. `[Deploy](runbooks/deploy.md)`).
- When adding new procedures or architecture, place them under the appropriate `/docs` directory and link from this index.
