# Decision Log

Record of **significant technical and product decisions** that affect the platform. Keeping a log here helps humans and AI agents understand *why* things are done a certain way.

---

## Purpose

- Capture **what** was decided, **when**, and **why** (and optionally **who**).
- Avoid re-debating settled choices; new work can reference past decisions.
- Give agents (e.g. OpenClaw, Cursor) context so they don’t suggest options that were already rejected.

---

## Format (suggested)

For each decision, add a short markdown note (in this folder or in a dated file) with:

- **Date**
- **Decision** (one line)
- **Context** (problem or question)
- **Options considered**
- **Outcome** (what we chose and why)
- **Consequences** (follow-ups, docs to update, etc.)

---

## Example

```markdown
## 2026-03-06 — GitHub as single source of truth for docs

- **Decision**: All technical documentation lives in the repo under `/docs`. Notion holds projects/tasks/decisions and references the repo.
- **Context**: Docs were split between Notion, Cursor chats, and the repo; hard to maintain and for agents to use.
- **Options**: (A) Notion as source of truth, (B) GitHub as source of truth, (C) Duplicate in both.
- **Outcome**: GitHub = docs + code; Notion = projects + tasks + decisions; Cursor = development; OpenClaw = execution.
- **Consequences**: Audit and move docs into `/docs`, add `docs/README.md`, update root README with a Documentation section; add `docs/agents` and `docs/decision-log`.
```

---

## Recorded decisions

### 2026-03-06 — GitHub as single source of truth for documentation

- **Decision**: All technical documentation lives in the repo under `/docs`. Notion holds projects, tasks, and decisions and references the repo when needed.
- **Context**: Documentation was split between Notion, Cursor chats, and the repo; hard to maintain and for agents (e.g. OpenClaw) to use.
- **Options**: (A) Notion as source of truth, (B) GitHub as source of truth, (C) Duplicate in both.
- **Outcome**: GitHub = documentation + code; Notion = projects + tasks + decisions; Cursor = development; OpenClaw = execution.
- **Consequences**: Audit and consolidate docs under `/docs` with a clear structure (architecture, infrastructure, runbooks, integrations, operations, agents, decision-log); add `docs/README.md`; update root README with a Documentation section.

---

## Where to add new decisions

- Add a new section in this README, or
- Create a dated file, e.g. `docs/decision-log/2026-03-06-single-source-of-truth.md`, and link it from this README.

---

## Related

- [Agents](../agents/README.md) — Agent context and conventions
- [Documentation index](../README.md) — Full docs structure
