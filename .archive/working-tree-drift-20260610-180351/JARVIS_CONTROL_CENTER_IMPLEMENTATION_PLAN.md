# Jarvis Control Center — Implementation Plan

> **Status:** Planning (no code changes yet)  
> **Date:** 2026-06-10  
> **Author:** Architecture audit of `crypto-2.0`  
> **Goal:** Replace dormant Agent Ops / OpenClaw with a Bedrock-based **Jarvis Control Center** that acts as a controlled AI operator for trading maintenance, marketing, software building, and future business automation — without destabilizing live trading.

---

## 1. Executive Summary

Production today runs with `ATP_TRADING_ONLY=1`. The trading stack is healthy and must remain isolated. OpenClaw is legacy, externally hosted on LAB, and currently unavailable. The Agent Ops dashboard tab exists but reflects a stopped Notion scheduler and disabled automation.

**Jarvis already exists** in this codebase as a Bedrock-backed platform (`backend/app/jarvis/`, `/api/jarvis/*`) and is **not gated** by `ATP_TRADING_ONLY`. That makes Jarvis the correct foundation for the new Control Center: it can run in Advisor mode on PROD while Builder and Operator modes stay LAB-gated.

The migration strategy is **evolve, don't rip**:

1. Add a **Jarvis Control Center** dashboard tab (replacing OpenClaw UI references).
2. Unify three parallel Jarvis entry points (legacy orchestrator, LangGraph MVP, autonomous Telegram) behind one mode-aware API.
3. Reuse governance, approval, and execution-policy layers already built for Agent Ops.
4. Retire OpenClaw as an LLM backend; keep SSM/LAB infra scripts only until Operator mode no longer depends on them.
5. Keep `ATP_TRADING_ONLY=1` on PROD until Phase 3 approval gates are proven on LAB.

---

## 2. Current State Audit

### 2.1 Production posture

| Flag / setting | Current value | Effect |
|----------------|---------------|--------|
| `ATP_TRADING_ONLY` | `1` (compose default) | Disables agent/governance/AI/GitHub webhook routes; skips agent scheduler, Notion validation, Cursor bridge startup |
| Agent scheduler | Stopped / not mounted | No Notion → OpenClaw task loop |
| `AGENT_AUTOMATION_ENABLED` | Configurable (default true) | Irrelevant while trading-only |
| Jarvis routes | **Always mounted** | `/api/jarvis/*`, Bedrock, executive/audit/objectives APIs available on PROD |
| OpenClaw gateway | Unavailable (LAB) | `openclaw_client.py` calls fail; iframe tab shows broken embed |

### 2.2 Backend route inventory

#### Gated when `ATP_TRADING_ONLY=1` (via `factory.py`)

| Router | Prefix | Purpose |
|--------|--------|---------|
| `routes_agent` | `/api/agent/*` | Agent Ops visibility, SSM commands, Cursor bridge |
| `routes_governance` | `/api/governance/*` | PROD mutation manifests, approval, execution |
| `routes_ai` | `/api/ai/*` | Scaffold only — no LLM |
| `routes_github_webhook` | `/api/github/actions` | Deploy → smoke check lifecycle |

#### Always available

| Router | Prefix | Purpose |
|--------|--------|---------|
| `routes_jarvis` | `/api/jarvis/*`, `POST /jarvis` | Bedrock LangGraph MVP, audits, executive layer, objectives |
| `routes_monitoring` | `/api/monitoring/*` | Workflows, health, backend restart (restart blocked when governance enforced) |
| `routes_control` | `/api/services/*` | Trading scheduler start/stop |

### 2.3 Agent Ops service layer (Notion → OpenClaw pipeline)

| Component | Path | Role |
|-----------|------|------|
| Scheduler loop | `backend/app/services/agent_scheduler.py` | 1 task/cycle, approvals, auto-exec |
| Task executor | `backend/app/services/agent_task_executor.py` | Execute bundles, Notion comments, deploy |
| OpenClaw client | `backend/app/services/openclaw_client.py` | HTTP to external OpenClaw gateway (**replace with Bedrock**) |
| Callbacks | `backend/app/services/agent_callbacks.py` | Task-type apply functions |
| Execution policy | `backend/app/services/agent_execution_policy.py` | `read_only` / `patch_prep` / `prod_mutation` classification |
| Telegram approval | `backend/app/services/agent_telegram_approval.py` | Approve/deny deploy bundles |
| Cursor bridge | `backend/app/services/cursor_execution_bridge.py` | Staging → diff → tests → PR |
| Governance bridge | `backend/app/services/governance_agent_bridge.py` | Notion agent ↔ governance manifests |
| Activity log | `backend/app/services/agent_activity_log.py` | `logs/agent_activity.jsonl` |
| Recovery | `backend/app/services/agent_recovery.py` | Orphan smoke, stale tasks |

### 2.4 Jarvis platform (Bedrock — reuse as foundation)

| Layer | Key paths | Notes |
|-------|-----------|-------|
| LLM client | `backend/app/jarvis/bedrock_client.py` | `boto3 bedrock-runtime`, Claude via Bedrock |
| LangGraph MVP | `backend/app/jarvis/mvp/{graph,agents,service,tools,risk}.py` | `POST /api/jarvis/task`, dry-run gate |
| Action policy | `backend/app/jarvis/action_policy.py` | `auto_execute` vs `requires_approval` per action type |
| Risk classifier | `backend/app/jarvis/mvp/risk.py` | Keyword-based high/medium/low |
| Autonomous missions | `backend/app/jarvis/autonomous_orchestrator.py` | Telegram `/mission` flow |
| Legacy orchestrator | `backend/app/jarvis/orchestrator.py` | `POST /jarvis` — deprecate |
| Repo worker MVP | `backend/app/jarvis/repo_worker_mvp.py` | Staging clone verify; blocked on trading-only |
| Marketing tools | `backend/app/jarvis/marketing_*.py`, `google_ads_*.py` | GA4, GSC, Google Ads proposals |
| Ops tools | `backend/app/jarvis/ops_tools.py`, `ops_agent.py` | Docker/env diagnostics |
| Approval storage | `backend/app/jarvis/approval_storage.py` | In-memory today — **must persist for Control Center** |

Canonical reference: `backend/docs/jarvis/JARVIS_ARCHITECTURE_MANIFEST.md`

### 2.5 Existing database models

| Table / store | Model / bootstrap | Scope |
|---------------|-------------------|-------|
| `agent_approval_states` | SQLAlchemy `AgentApprovalState` | Telegram execution bundles for Notion tasks |
| `governance_tasks` | `GovernanceTask` | Governed work units |
| `governance_events` | `GovernanceEvent` | Append-only audit stream |
| `governance_manifests` | `GovernanceManifest` | Digest-bound PROD mutation intent |
| `jarvis_task_runs` | boot hook in `database.py` | LangGraph MVP history |
| `jarvis_*` (15+ tables) | boot hooks | Audits, objectives, decisions, followups, etc. |
| `logs/agent_activity.jsonl` | file | Scheduler/recovery/smoke events |

### 2.6 Frontend inventory

| Surface | Path | State |
|---------|------|-------|
| Agent Ops tab | `frontend/src/app/components/tabs/AgentOpsTab.tsx` | Read-only polling dashboard (8 endpoints) |
| OpenClaw tab | `frontend/src/app/components/tabs/OpenClawTab.tsx` | Iframe to `/openclaw/` (broken) |
| OpenClaw route | `frontend/src/app/openclaw/page.tsx` | Duplicate iframe page |
| Governance viewer | `frontend/src/app/governance/task/page.tsx` | Read-only timeline; bearer in `sessionStorage` |
| Monitoring panel | `frontend/src/app/components/MonitoringPanel.tsx` | Action pattern: confirm + POST + loading |
| Jarvis UI | **None** | Backend/Telegram only |

API client split: agent ops in `frontend/src/app/api.ts`; trading/monitoring in `frontend/src/lib/api.ts`.

---

## 3. Reuse vs Remove vs Rename

### 3.1 Reuse (high value, minimal change)

| Asset | Reuse strategy |
|-------|----------------|
| `bedrock_client.py` | Single LLM backend for all Jarvis modes |
| `jarvis/mvp/` LangGraph pipeline | Core planner/responder for Advisor + Builder planning |
| `action_policy.py` | Extend with Control Center action types and mode gates |
| `mvp/risk.py` | Pre-flight risk scoring; extend with trading-specific blocklist |
| `agent_execution_policy.py` | Fail-closed PROD classification — wire into Operator mode |
| `governance_*` tables + routes | Operator mode approval + digest-bound execution |
| `agent_approval_states` | Keep for Telegram parity; link to new `jarvis_approvals` |
| `cursor_execution_bridge.py` | Builder mode: branch, diff, test, PR |
| `repo_worker_mvp.py` | Builder mode staging verification |
| `agent_activity_log.py` | Mirror events into unified audit table |
| `routes_jarvis.py` | Extend, don't replace |
| `AgentOpsTab.tsx` widgets | Embed as "Legacy Ops Telemetry" sub-panel inside Control Center |
| `governance/task/page.tsx` | Reuse timeline component for approval detail drawer |
| `MonitoringPanel.tsx` patterns | Approve/deny/run button UX |
| Jarvis executive/audit/objectives APIs | Advisor mode dashboards and context |

### 3.2 Deprecate then remove (OpenClaw)

| Asset | Action | Timeline |
|-------|--------|----------|
| `OpenClawTab.tsx`, `/openclaw` route | Remove tab; replace with Jarvis Control Center | Phase 1 |
| `openclaw_client.py` | Stop calling from new code; adapter shim for legacy scheduler until Phase 3 | Phase 1–3 |
| `agent_callbacks.py` OpenClaw delegation | Route through Bedrock Jarvis planner | Phase 2 |
| `agent_scheduler.py` Notion loop | Optional re-enable behind Jarvis Operator, not OpenClaw | Phase 3 |
| Nginx `/openclaw/` proxy block | Remove after UI tab gone | Phase 1 |
| `scripts/openclaw/*` (50+ files) | Archive operational runbooks; delete redundant diagnostics | Phase 4 |
| `openclaw/` Docker image build | Stop maintaining | Phase 4 |
| `TELEGRAM_CLAW_*` env vars | Rename to Jarvis bot or consolidate | Phase 3 |
| `OPENCLAW_API_TOKEN` | Rename to `JARVIS_API_TOKEN` with compat alias | Phase 1 |

### 3.3 Consolidate / refactor

| Issue | Resolution |
|-------|------------|
| Three Jarvis entry points (`orchestrator`, MVP, autonomous) | Single `JarvisControlService` with `mode` parameter |
| In-memory `approval_storage.py` | Postgres tables (see §4) |
| Jarvis tables via boot hooks | Proper SQL migrations under `backend/migrations/` |
| Duplicate `fetchAPI` in frontend | Single `lib/jarvisApi.ts` client module |
| `/api/ai/run` scaffold | Delete or redirect to Jarvis Control Center | Phase 2 |
| Agent Ops + Jarvis as separate tabs | Merge into Control Center with sub-nav | Phase 1 |

### 3.4 Do not touch (trading stability)

| Area | Rule |
|------|------|
| `routes_orders`, `routes_signals`, `routes_engine`, trading scheduler | No Jarvis imports; no shared mutation paths |
| `ATP_TRADING_ONLY=1` on PROD | Keep until Operator gates validated on LAB |
| Order placement, SL/TP, strategy config writers | Blocklist in Operator mode (§7) |
| Exchange credentials, API keys | Never exposed to LLM context; never writable without approval |

---

## 4. Proposed Data Model

New tables integrate with existing `governance_*` and `jarvis_task_runs`. Use SQLAlchemy models + migrations (follow Prisma conventions where applicable: IDs, timestamps, indexes).

### 4.1 Entity relationship (conceptual)

```
jarvis_control_sessions
    └── jarvis_control_tasks (1:N)
            ├── jarvis_control_actions (1:N)  — planned steps
            ├── jarvis_control_approvals (1:N) — approval requests
            └── jarvis_control_audit_events (1:N) — append-only log

Optional links:
  jarvis_control_tasks.governance_task_id → governance_tasks.task_id
  jarvis_control_tasks.legacy_task_run_id → jarvis_task_runs.task_id
  jarvis_control_approvals.governance_manifest_id → governance_manifests.manifest_id
  jarvis_control_approvals.agent_approval_id → agent_approval_states.id
```

### 4.2 `jarvis_control_sessions`

User or system-initiated Control Center session (groups related tasks).

| Column | Type | Notes |
|--------|------|-------|
| `id` | `cuid()` PK | |
| `session_id` | `string` unique | External reference |
| `created_by` | `string` | `dashboard:{user}`, `telegram:{chat}`, `scheduler`, `api` |
| `default_mode` | `enum` | `advisor`, `builder`, `operator` |
| `environment` | `enum` | `prod`, `lab`, `local` |
| `domain` | `enum` | `trading`, `marketing`, `software`, `ops`, `general` |
| `status` | `enum` | `active`, `closed`, `failed` |
| `metadata_json` | `text` | UI context, correlation IDs |
| `created_at`, `updated_at` | `timestamptz` | |

Indexes: `(created_by, created_at DESC)`, `(status)`.

### 4.3 `jarvis_control_tasks`

Primary work unit — evolves `jarvis_task_runs` with explicit mode and lifecycle.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `cuid()` PK | |
| `task_id` | `string` unique | e.g. `jcc-{uuid}` |
| `session_id` | FK → sessions | |
| `mode` | `enum` | `advisor`, `builder`, `operator` |
| `domain` | `enum` | Same as session |
| `prompt` | `text` | User natural-language request |
| `status` | `enum` | `queued`, `planning`, `running`, `awaiting_approval`, `completed`, `failed`, `cancelled` |
| `risk_level` | `enum` | `low`, `medium`, `high` |
| `dry_run` | `boolean` | Forced `true` in Advisor mode |
| `plan_json` | `text` | Bedrock planner output |
| `tool_results_json` | `text` | Tool execution results |
| `final_answer` | `text` | Human-readable summary |
| `estimated_cost_usd` | `float` | Bedrock token cost estimate |
| `builder_artifact_json` | `text` | Branch name, diff path, test report, PR URL |
| `governance_task_id` | `string` nullable | Link to governance |
| `legacy_task_run_id` | `string` nullable | Back-compat with MVP |
| `error` | `text` nullable | |
| `created_at`, `completed_at`, `updated_at` | `timestamptz` | |

Indexes: `(session_id)`, `(status, created_at DESC)`, `(mode, domain)`.

### 4.4 `jarvis_control_actions`

Individual planned or executed actions within a task (mirrors LangGraph tool steps + Operator commands).

| Column | Type | Notes |
|--------|------|-------|
| `id` | `cuid()` PK | |
| `action_id` | `string` unique | |
| `task_id` | FK → tasks | |
| `sequence` | `int` | Order in plan |
| `action_type` | `string` | From `action_policy.py` registry |
| `title` | `string` | |
| `execution_mode` | `enum` | `auto_execute`, `requires_approval`, `blocked`, `requires_input` |
| `risk_level` | `enum` | |
| `status` | `enum` | `pending`, `approved`, `rejected`, `executing`, `completed`, `failed`, `skipped` |
| `input_json` | `text` | Tool parameters (redacted secrets) |
| `output_json` | `text` | Result payload |
| `digest` | `string` nullable | SHA-256 of canonical action payload for approval binding |
| `requires_approval_reason` | `string` nullable | |
| `created_at`, `executed_at` | `timestamptz` | |

Indexes: `(task_id, sequence)`, `(status)`, `(digest)`.

### 4.5 `jarvis_control_approvals`

Human approval gate — unifies dashboard, Telegram, and governance manifest approval.

| Column | Type | Notes |
|--------|------|-------|
| `id` | `cuid()` PK | |
| `approval_id` | `string` unique | |
| `task_id` | FK → tasks | |
| `action_id` | FK → actions nullable | Single action or batch |
| `approval_status` | `enum` | `pending`, `approved`, `rejected`, `expired` |
| `execution_status` | `enum` | `not_executed`, `ready`, `executing`, `executed`, `failed` |
| `risk_level` | `enum` | |
| `scope_summary` | `string` | Human-readable description |
| `digest` | `string` | Must match action/manifest digest |
| `allowed_envs` | `string` | e.g. `lab` only for builder artifacts |
| `requested_by` | `string` | `jarvis`, `user:{id}` |
| `approved_by` | `string` nullable | |
| `approved_at`, `expires_at` | `timestamptz` | TTL default 24h |
| `governance_manifest_id` | `string` nullable | |
| `agent_approval_state_id` | `int` nullable | Legacy link |
| `telegram_message_id` | `string` nullable | |
| `execution_result_json` | `text` nullable | |
| `created_at`, `updated_at` | `timestamptz` | |

Indexes: `(approval_status, created_at DESC)`, `(digest)`, `(task_id)`.

### 4.6 `jarvis_control_audit_events`

Append-only audit log (superset of `governance_events` + `agent_activity.jsonl` for Control Center).

| Column | Type | Notes |
|--------|------|-------|
| `id` | `cuid()` PK | |
| `event_id` | `string` unique | |
| `task_id` | `string` nullable | |
| `session_id` | `string` nullable | |
| `approval_id` | `string` nullable | |
| `ts` | `timestamptz` | |
| `type` | `string` | `task_created`, `plan_generated`, `tool_invoked`, `approval_requested`, `approval_decided`, `action_executed`, `policy_blocked`, etc. |
| `actor_type` | `enum` | `human`, `jarvis`, `system`, `scheduler` |
| `actor_id` | `string` nullable | |
| `environment` | `string` | |
| `payload_json` | `text` | Redacted structured payload |
| `created_at` | `timestamptz` | |

Indexes: `(task_id, ts DESC)`, `(type, ts DESC)`, `(session_id, ts DESC)`.

### 4.7 Migration from existing stores

| Legacy | Migration approach |
|--------|-------------------|
| `jarvis_task_runs` | Read-only backfill into `jarvis_control_tasks` with `legacy_task_run_id`; new writes go to control tables |
| `governance_*` | Operator actions create governance task + manifest; link via FK |
| `agent_approval_states` | Dual-write during Phase 3; Telegram callbacks update both |
| `approval_storage.py` (memory) | Replace with `jarvis_control_approvals` |
| `agent_activity.jsonl` | Continue writing; async mirror to `jarvis_control_audit_events` |

---

## 5. Proposed API Endpoints

All new routes under `/api/jarvis/control/*`. Existing `/api/jarvis/*` endpoints remain for executive/audit/objectives until consolidated.

Auth: Bearer `JARVIS_API_TOKEN` (rename from `OPENCLAW_API_TOKEN` with backward-compatible alias). Dashboard uses session cookie or admin key for read; write/approve requires elevated token.

### 5.1 Sessions & tasks

| Method | Route | Mode | Description |
|--------|-------|------|-------------|
| POST | `/api/jarvis/control/sessions` | all | Create session `{ domain, default_mode, metadata }` |
| GET | `/api/jarvis/control/sessions/{session_id}` | all | Session detail + task list |
| POST | `/api/jarvis/control/tasks` | all | Submit task `{ session_id, mode, prompt, domain?, dry_run? }` |
| GET | `/api/jarvis/control/tasks` | all | List tasks (filters: mode, status, domain, limit) |
| GET | `/api/jarvis/control/tasks/{task_id}` | all | Full task detail (plan, actions, approvals) |
| POST | `/api/jarvis/control/tasks/{task_id}/cancel` | all | Cancel queued/running task |
| GET | `/api/jarvis/control/tasks/{task_id}/stream` | all | SSE stream for plan/tool progress (Phase 1 nice-to-have) |

### 5.2 Advisor mode (Phase 1)

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/api/jarvis/control/advisor/analyze` | Shortcut: `{ prompt, domain }` → read-only analysis |
| GET | `/api/jarvis/control/advisor/context/{domain}` | Pre-loaded context (trading health, audit summaries, marketing KPIs) |

Wraps existing: `POST /api/jarvis/task` with `dry_run=true`, plus new persistence in control tables.

### 5.3 Builder mode (Phase 2)

| Method | Route | Description |
|--------|-------|-------------|
| POST | `/api/jarvis/control/builder/prepare` | Plan + staging setup; returns branch name |
| GET | `/api/jarvis/control/builder/{task_id}/diff` | Unified diff artifact |
| GET | `/api/jarvis/control/builder/{task_id}/tests` | Test report JSON |
| POST | `/api/jarvis/control/builder/{task_id}/run-tests` | Re-run pytest/npm in staging |
| POST | `/api/jarvis/control/builder/{task_id}/open-pr` | Create PR (requires approval if targeting main) |

Internally delegates to `cursor_execution_bridge` + `repo_worker_mvp`. **Blocked on PROD when `ATP_TRADING_ONLY=1`.**

### 5.4 Operator mode (Phase 3)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/jarvis/control/approvals` | Pending approvals inbox |
| GET | `/api/jarvis/control/approvals/{approval_id}` | Approval detail + digest + scope |
| POST | `/api/jarvis/control/approvals/{approval_id}/approve` | `{ approved_by, note? }` |
| POST | `/api/jarvis/control/approvals/{approval_id}/reject` | `{ rejected_by, reason }` |
| POST | `/api/jarvis/control/approvals/{approval_id}/execute` | Execute approved action (idempotent) |
| POST | `/api/jarvis/control/operator/run` | Submit operator task (auto-creates approval for gated actions) |

Proxies to `governance_service` for PROD mutations; uses `agent_execution_policy.classify_callback_action` before any apply.

### 5.5 Audit & status (all phases)

| Method | Route | Description |
|--------|-------|-------------|
| GET | `/api/jarvis/control/audit` | Paginated audit events |
| GET | `/api/jarvis/control/audit/{task_id}/timeline` | Task timeline (reuse governance timeline assembler) |
| GET | `/api/jarvis/control/status` | Control Center health: Bedrock, mode availability, trading-only flag |
| GET | `/api/jarvis/control/capabilities` | Tool registry by mode/domain (for UI) |

### 5.6 Legacy compatibility shims (temporary)

| Legacy route | Shim behavior |
|--------------|-----------------|
| `POST /api/jarvis/task` | Delegate to control tasks with `mode=advisor` default |
| `POST /jarvis` | Deprecation header; redirect to control API |
| `GET /api/agent/status` | Include Jarvis Control Center status fields |
| `POST /api/governance/*` | Unchanged; Operator mode creates records here |

---

## 6. Proposed Frontend Screens

New tab: **Jarvis Control Center** (`jarvis-control`). Remove **OpenClaw** tab. Optionally fold **Agent Ops** into a sub-panel.

### 6.1 Navigation changes (`frontend/src/app/page.tsx`)

```
Tabs (proposed order):
  Portfolio | Watchlist | Signals | Orders | ... | Monitoring | Jarvis Control Center | Version History

Remove: openclaw tab, openclaw/page.tsx (or redirect to /?tab=jarvis-control)
Keep: agent-ops as sub-route OR embed inside Control Center → "Ops Telemetry"
```

Use URL query `?tab=jarvis-control` for deep-linking (new — currently tabs are not linkable).

### 6.2 Screen: Control Center Home

**Component:** `JarvisControlCenterTab.tsx`

Layout:

```
┌─────────────────────────────────────────────────────────────────┐
│ Jarvis Control Center          [Mode: Advisor ▼] [Domain: All ▼]│
│ Status: Bedrock ✓ | Trading-only: ON | Pending approvals: 2     │
├─────────────────────────────────────────────────────────────────┤
│ ┌─ New Task ─────────────────────────────────────────────────┐  │
│ │ [Natural language input........................] [Submit]  │  │
│ │ Mode chips: Advisor | Builder (LAB) | Operator (LAB)       │  │
│ └────────────────────────────────────────────────────────────┘  │
├──────────────────────────┬──────────────────────────────────────┤
│ Task Inbox               │ Task Detail                          │
│ • Analyze SL/TP drift    │ Plan steps, tool results, risk badge │
│ • Fix monitoring alert   │ [Approve] [Reject] [View diff]       │
│ • Weekly marketing review│ Audit timeline (collapsible)         │
└──────────────────────────┴──────────────────────────────────────┘
```

Reuse from `AgentOpsTab`: `StatusBadge`, `EventList`, polling pattern (45s).

### 6.3 Screen: Task Detail Drawer

- Plan steps with action-type badges (`auto_execute` vs `requires_approval`)
- Tool result viewers (JSON collapse, diff viewer for Builder)
- Risk level banner (from `mvp/risk.py`)
- Link to governance timeline for Operator tasks

Reuse: `governance/task/page.tsx` timeline rendering → extract `GovernanceTimeline.tsx`.

### 6.4 Screen: Approvals Inbox (Phase 3)

- Table: pending approvals with scope, digest (copy button), expiry, risk
- Approve/Reject with confirmation modal (pattern from `MonitoringPanel.handleRunWorkflow`)
- Optional: "Approve & Execute" two-step for high-risk

### 6.5 Screen: Builder Artifacts (Phase 2)

- Branch name, commit SHA, file list changed
- Side-by-side or unified diff viewer
- Test results: pass/fail counts, log excerpt
- "Open PR" button (gated)

### 6.6 Screen: Domain dashboards (Phase 1 Advisor context panels)

| Domain | Panel content | Data source |
|--------|---------------|-------------|
| Trading | Scheduler status, recent signals, portfolio health | Existing monitoring + `/api/jarvis/crypto-audits` |
| Marketing | GA4/GSC/Ads readiness, recent proposals | `/api/admin/secrets-status`, Jarvis marketing tools |
| Software | Open PRs, failed CI, repo health | GitHub API (read-only) |
| Ops | AWS audit summary, follow-ups | `/api/jarvis/audits`, `/api/jarvis/followups` |

### 6.7 Screen: Ops Telemetry (embedded legacy Agent Ops)

Collapsible section inside Control Center showing current `AgentOpsTab` content — scheduler state, smoke checks, deploy tracker. Read-only on PROD until automation re-enabled on LAB.

### 6.8 New frontend modules

| File | Purpose |
|------|---------|
| `frontend/src/lib/jarvisControlApi.ts` | Typed client for `/api/jarvis/control/*` |
| `frontend/src/app/components/tabs/JarvisControlCenterTab.tsx` | Main tab |
| `frontend/src/app/components/jarvis/TaskInbox.tsx` | Task list |
| `frontend/src/app/components/jarvis/TaskDetail.tsx` | Detail panel |
| `frontend/src/app/components/jarvis/ApprovalsInbox.tsx` | Phase 3 |
| `frontend/src/app/components/jarvis/BuilderArtifacts.tsx` | Phase 2 |
| `frontend/src/app/components/jarvis/GovernanceTimeline.tsx` | Extracted from governance page |

---

## 7. Safety Rules & Permission Levels

### 7.1 Operating modes (hard gates)

| Mode | Allowed on PROD (`ATP_TRADING_ONLY=1`) | Allowed on LAB | LLM | Tools |
|------|----------------------------------------|----------------|-----|-------|
| **Advisor** | Yes | Yes | Bedrock | Read-only: audits, logs, metrics, docs, status APIs |
| **Builder** | **No** | Yes | Bedrock | Staging git, diff, tests, PR draft; no deploy |
| **Operator** | **No** (until explicit PROD operator flag) | Yes first | Bedrock | Approved mutations, SSM, deploy, config writes |

Enforcement layers (all must pass):

1. **Mode gate** — API rejects Builder/Operator on trading-only hosts.
2. **Action policy** — `action_policy.py` execution_mode per action type.
3. **Execution policy** — `agent_execution_policy.py` fail-closed on AWS.
4. **Governance** — digest-bound manifest for PROD mutations when `ATP_GOVERNANCE_AGENT_ENFORCE=1`.
5. **Trading blocklist** — regex + explicit action type deny (below).

### 7.2 Trading critical blocklist (always `requires_approval`; Operator on PROD = deny)

No autonomous execution, even after approval, without a separate break-glass flag `JARVIS_PROD_TRADING_OPERATOR=1`:

- Live order placement, cancellation, modification
- Strategy enable/disable, profile changes affecting live trades
- Stop loss / take profit parameter changes
- Capital allocation, position sizing, leverage
- Exchange API key / credential rotation
- Deployment to PROD trading backend
- Database migrations affecting orders, signals, portfolio tables
- `ATP_TRADING_ONLY` env change on PROD

Advisor mode may **analyze** these topics but tools must not invoke writers.

### 7.3 Permission levels (RBAC)

| Level | Capabilities |
|-------|--------------|
| **viewer** | Read task history, audit log, Advisor outputs |
| **advisor** | Submit Advisor tasks |
| **builder** | Submit Builder tasks (LAB only) |
| **operator** | Submit Operator tasks; approve low/medium risk |
| **admin** | Approve high-risk; configure domains; break-glass flags |

Implementation: extend existing Bearer token model; map Telegram chat IDs to roles for mobile approval parity.

### 7.4 Approval rules

| Risk | Advisor | Builder | Operator |
|------|---------|---------|----------|
| Low | Auto-complete | Auto through staging | Auto-execute read-only ops |
| Medium | Auto-complete | Auto through staging; PR needs approval | Human approval required |
| High | Recommend only | Human approval before any file write | Human approval + digest re-check at execute |
| Blocked | Policy refusal | Policy refusal | Policy refusal |

Additional rules:

- Approvals expire after 24h (configurable).
- Execute endpoint verifies digest matches approved payload (same as governance manifests).
- Two-person rule optional for PROD deploy: `JARVIS_DEPLOY_DUAL_APPROVAL=1`.
- All approvals logged to `jarvis_control_audit_events` and Telegram ops channel.

### 7.5 Bedrock / data handling

- Never pass secrets, API keys, or raw credentials in prompts; use secret presence checks only.
- Redact `payload_json` in audit events before persist.
- `JARVIS_DRY_RUN_ONLY=1` forces Advisor behavior globally (emergency kill switch).

---

## 8. Target Architecture

```
┌────────────────────────────────────────────────────────────────────────────┐
│                         DASHBOARD (Next.js)                                 │
│  Jarvis Control Center Tab  │  Monitoring  │  Trading tabs (unchanged)  │
└─────────────────────────────┬──────────────────────────────────────────────┘
                              │ /api/jarvis/control/*
┌─────────────────────────────▼──────────────────────────────────────────────┐
│                    JARVIS CONTROL SERVICE (new)                             │
│  mode router │ session manager │ approval orchestrator │ audit writer      │
└──────┬───────────────┬─────────────────┬──────────────────┬────────────────┘
       │               │                 │                  │
       ▼               ▼                 ▼                  ▼
┌─────────────┐ ┌──────────────┐ ┌───────────────┐ ┌─────────────────────┐
│ Bedrock     │ │ LangGraph    │ │ Governance    │ │ Cursor Bridge       │
│ Client      │ │ MVP graph    │ │ Service       │ │ (Builder)           │
└─────────────┘ └──────────────┘ └───────────────┘ └─────────────────────┘
       │               │                 │                  │
       ▼               ▼                 ▼                  ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  PostgreSQL: jarvis_control_* │ governance_* │ agent_approval_states       │
│  File: logs/agent_activity.jsonl (mirror)                                   │
└────────────────────────────────────────────────────────────────────────────┘

PROD (ATP_TRADING_ONLY=1):  Advisor mode only ──► read-only tools ──► no mutations
LAB:                        Advisor + Builder + Operator ──► approval gates ──► execute
```

### LLM backend

**AWS Bedrock only** via existing `bedrock_client.py`. Model ID from `JARVIS_BEDROCK_MODEL_ID`. No OpenClaw HTTP delegation in new code paths.

### Trading isolation

Jarvis Control Service runs in the same FastAPI process but:

- No imports from order execution modules in tool registry for Advisor on PROD.
- Builder/Operator subprocess work uses `ATP_STAGING_ROOT` or LAB SSM — never PROD workspace writes.
- Trading scheduler (`backend/app/services/scheduler.py`) remains independent; Jarvis cron jobs (KR refresh, followups) continue as read-only/reporting.

---

## 9. Phased Implementation

### Phase 1 — Jarvis Advisor only (4–6 weeks)

**Goal:** Replace OpenClaw tab with Control Center; Bedrock analysis on PROD without side effects.

| Work item | Details |
|-----------|---------|
| DB migration | Create `jarvis_control_sessions`, `jarvis_control_tasks`, `jarvis_control_audit_events` |
| Backend | `JarvisControlService` + `/api/jarvis/control/advisor/*` + task CRUD |
| Bedrock | Wire LangGraph MVP through control service; force `dry_run=true` for Advisor |
| Frontend | `JarvisControlCenterTab` — prompt input, task inbox, detail view |
| UI cleanup | Remove OpenClaw tab; redirect `/openclaw` → Control Center |
| Rename | UI strings OpenClaw → Jarvis; env alias `JARVIS_API_TOKEN` |
| Context panels | Trading health + AWS audit + executive summary (read-only) |
| Tests | API tests for mode gate; verify no write tools on PROD |
| Ops | Document `JARVIS_ENABLED=1`, Bedrock IAM on PROD instance |

**Exit criteria:**

- User can submit Advisor tasks from dashboard on PROD.
- No write tools invoked; audit log populated.
- OpenClaw tab removed; trading unaffected.

### Phase 2 — Builder with branch/diff/test (4–6 weeks)

**Goal:** Software building on LAB; prepare PRs without merging.

| Work item | Details |
|-----------|---------|
| DB | Add `jarvis_control_actions`, `builder_artifact_json` column usage |
| Backend | Builder routes; integrate `cursor_execution_bridge` + `repo_worker_mvp` |
| Mode gate | Reject Builder API when `ATP_TRADING_ONLY=1` |
| Frontend | Diff viewer, test report panel, branch info |
| Action policy | Tighten `code_change`, `perico_apply_patch` to `requires_approval` for PR to main |
| Deprecate | Stop routing new tasks through `openclaw_client.py` |
| Tests | E2E: prompt → staging → diff → tests (LAB) |

**Exit criteria:**

- Builder task produces branch, diff artifact, test report on LAB.
- PR creation requires approval for default branch.
- PROD returns 403 for Builder endpoints.

### Phase 3 — Operator with approval gates (6–8 weeks)

**Goal:** Execute approved operational actions from dashboard + Telegram.

| Work item | Details |
|-----------|---------|
| DB | `jarvis_control_approvals`; persist `approval_storage.py` logic |
| Backend | Approval inbox API; execute with digest verification; governance bridge |
| Frontend | Approvals inbox; approve/reject/execute UI |
| Telegram | Inline keyboards update `jarvis_control_approvals` (parity with dashboard) |
| Policy | Wire `agent_execution_policy`, trading blocklist, governance enforce |
| Agent Ops | Re-enable scheduler on LAB only (`ATP_TRADING_ONLY=0`); Jarvis replaces OpenClaw LLM calls |
| Optional | Re-mount `/api/governance/*` on LAB stack |
| Tests | Approval TTL, digest mismatch rejection, fail-closed AWS classification |

**Exit criteria:**

- Operator task requiring approval stays blocked until human approves in UI or Telegram.
- PROD mutation attempts without manifest are rejected on AWS.
- Trading blocklist actions never auto-execute.

### Phase 4 — Multi-domain tools (8+ weeks)

**Goal:** Marketing, software, AWS, Telegram, HubSpot automation under unified Control Center.

| Domain | Tools to register | Approval default |
|--------|-------------------|------------------|
| Marketing | GA4, GSC, Google Ads (existing `marketing_tools.py`, `google_ads_*`) | `requires_approval` for mutations |
| Software | GitHub PR, CI status, Cursor bridge | Builder path |
| AWS | `aws_auditor_tools.py` (read); SSM runners (write, approved) | Read auto; write approved |
| Telegram | Broadcast, channel config (read first) | Approved |
| HubSpot | **New integration** — contacts, campaigns (read Phase 4a; write Phase 4b) | Approved |
| Trading maintenance | Log analysis, config **proposals** only on PROD; apply on LAB | Strict blocklist |

| Work item | Details |
|-----------|---------|
| Tool registry | `/api/jarvis/control/capabilities` driven config |
| HubSpot | New `jarvis/hubspot_tools.py` + secrets in `required_secrets_registry` |
| Cleanup | Archive `scripts/openclaw/*`; remove OpenClaw Docker/Nginx |
| Migrations | Promote all `jarvis_*` boot hooks to SQL migrations |
| Consolidate | Deprecate `POST /jarvis` legacy orchestrator |
| Docs | Operator runbooks per domain |

**Exit criteria:**

- Domain selector in UI routes to correct tool subset.
- HubSpot read works; writes require approval.
- OpenClaw fully removed from runtime path.

---

## 10. Environment Variables (proposed)

| Variable | Default | Purpose |
|----------|---------|---------|
| `JARVIS_CONTROL_ENABLED` | `1` | Master switch for Control Center API |
| `JARVIS_API_TOKEN` | — | Dashboard/API auth (alias: `OPENCLAW_API_TOKEN`) |
| `JARVIS_DEFAULT_MODE` | `advisor` | Default mode for new sessions |
| `JARVIS_BUILDER_ALLOWED` | auto | `false` when `ATP_TRADING_ONLY=1` |
| `JARVIS_OPERATOR_ALLOWED` | auto | `false` when `ATP_TRADING_ONLY=1` |
| `JARVIS_PROD_TRADING_OPERATOR` | `0` | Break-glass for trading mutations on PROD |
| `JARVIS_APPROVAL_TTL_HOURS` | `24` | Approval expiry |
| `JARVIS_DEPLOY_DUAL_APPROVAL` | `0` | Two-person deploy rule |
| `JARVIS_BEDROCK_REGION` | `us-east-1` | Bedrock region |
| `JARVIS_BEDROCK_MODEL_ID` | — | Model ID |

Existing Jarvis and governance vars remain unchanged.

---

## 11. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Jarvis on PROD accidentally mutates trading | Advisor mode hard-coded read-only tools; integration tests; `ATP_TRADING_ONLY` blocks Builder/Operator |
| Bedrock IAM missing on PROD | Phase 1 preflight in `/api/jarvis/control/status`; fail gracefully |
| Approval bypass via legacy routes | Deprecation shims log warnings; governance enforce on AWS |
| Dual approval systems (Telegram + dashboard) drift | Single `jarvis_control_approvals` source of truth |
| Large diff in Builder crashes UI | Paginate diff API; max artifact size |
| Cost overrun on Bedrock | Per-task cost tracking (already in MVP); daily budget cap env var |
| OpenClaw removal breaks undocumented flows | Keep shim 90 days; grep CI for `openclaw` references |

---

## 12. Success Metrics

| Metric | Target |
|--------|--------|
| Trading incidents from Jarvis | 0 |
| Advisor task latency (p95) | < 30s |
| Builder task success rate (LAB) | > 80% produce valid diff + tests |
| Approval compliance | 100% gated actions have approval record before execute |
| OpenClaw dependency | 0 runtime calls by Phase 4 |
| Audit coverage | 100% control tasks have `jarvis_control_audit_events` trail |

---

## 13. Immediate Next Steps (when implementation begins)

1. Review and approve this plan.
2. Create GitHub epic with Phase 1 stories.
3. Add SQL migration for Phase 1 tables.
4. Implement `JarvisControlService` skeleton + Advisor endpoint behind feature flag `JARVIS_CONTROL_ENABLED`.
5. Build `JarvisControlCenterTab` MVP (prompt + task list).
6. Remove OpenClaw tab in same PR as Control Center alpha (feature-flagged).
7. Validate on PROD with `ATP_TRADING_ONLY=1`: Advisor only, no regressions in trading tabs.

---

## Appendix A — File reference map

| Category | Path |
|----------|------|
| Factory / mounting | `backend/app/factory.py` |
| Agent routes | `backend/app/api/routes_agent.py` |
| Governance routes | `backend/app/api/routes_governance.py` |
| Jarvis routes | `backend/app/api/routes_jarvis.py` |
| Bedrock | `backend/app/jarvis/bedrock_client.py` |
| LangGraph MVP | `backend/app/jarvis/mvp/` |
| Action policy | `backend/app/jarvis/action_policy.py` |
| Execution policy | `backend/app/services/agent_execution_policy.py` |
| Cursor bridge | `backend/app/services/cursor_execution_bridge.py` |
| OpenClaw client (deprecate) | `backend/app/services/openclaw_client.py` |
| Agent Ops UI | `frontend/src/app/components/tabs/AgentOpsTab.tsx` |
| OpenClaw UI (remove) | `frontend/src/app/components/tabs/OpenClawTab.tsx` |
| Architecture manifest | `backend/docs/jarvis/JARVIS_ARCHITECTURE_MANIFEST.md` |
| Agent Ops docs | `docs/architecture/AGENT_OPS_VISIBILITY.md` |

## Appendix B — Decision log

| Decision | Rationale |
|----------|-----------|
| Bedrock over OpenClaw | OpenClaw unavailable; Bedrock already integrated; single AWS bill/IAM |
| Keep `ATP_TRADING_ONLY=1` on PROD through Phase 2 | Zero risk to live trading; Advisor works without flag change |
| New `jarvis_control_*` tables vs overloading MVP tables | Clean mode/approval lifecycle without breaking existing Jarvis executive layer |
| Merge Agent Ops into Control Center | Single operator surface; Agent Ops becomes telemetry sub-panel |
| Governance tables unchanged | Proven digest-bound PROD mutation model; Operator mode links in |
