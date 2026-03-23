# ATP + OpenClaw governance layer

Internal design: **LAB thinks**, **PROD executes**, **humans approve** material production changes, **events** make work visible end-to-end.

**Scope:** Two EC2 roles — **atp-prod** (full ATP runtime) and **atp-lab** (OpenClaw + investigation). OpenClaw stays; this document adds control and visibility on top.

**Implementation:** See [IMPLEMENTATION_NOTES.md](./IMPLEMENTATION_NOTES.md) and [governance_approval_flow.md](../runbooks/governance_approval_flow.md).

**Filesystem (LAB):** [PATH_GUARD_DESIGN.md](./PATH_GUARD_DESIGN.md) — path-level enforcement so OpenClaw/LAB code paths cannot persist files outside `docs/**` (plus configured artifact directories) without using `path_guard` helpers. **Static audit + CI:** `backend/scripts/path_guard_audit.py` flags (1) raw Python writes and (2) high-risk **subprocess/shell** patterns (`shell=True`, `os.system`, string-form subprocess, `create_subprocess_shell`) **only in LAB-enforced service files**; **CI** runs `lab-path-guard-audit.yml` (`--fail-on-lab-bypass --ci`) on `main`. It does not replace runtime `path_guard` or governance, and does not parse shell redirection inside opaque strings.

**Boundaries:** **Governance** = PROD/runtime mutation (manifests, executor, approval). **Path guard** = LAB-safe persistence (docs, analysis, handoffs, approved artifact dirs). **Audit + CI** = regression control on LAB-enforced modules for unguarded writes and obvious shell bypasses. **Staging subprocess** (git/cursor in `cursor_execution_bridge`) stays outside path_guard by design; **docs/** outputs from that flow use `path_guard` where applicable (e.g. captured diffs).

---

# 1. Target architecture

| Layer | Responsibility |
|--------|------------------|
| **PROD (atp-prod)** | Runs trading backend, schedulers, Telegram pollers, DB, secrets-backed services. **Only PROD** may execute changes that affect live behavior: deploy, restart, migrations, env, secrets, compose. Exposes **read APIs** (logs, health, read-only SSM/Session Manager) and an **approved execution channel** (scripts or CI triggered after human approval). |
| **LAB (atp-lab)** | Runs OpenClaw, mirrors or shallow-clones repo for analysis, runs tests locally, produces patches/PRs, **read-only** inspection of PROD (logs, `docker ps`, file read where IAM allows). **No** direct writes to PROD filesystem, compose, or DB schema without going through approval → execution on PROD. |
| **Agent (OpenClaw / ATP agents)** | Produces plans, diffs, commands, and evidence. Emits **events** (plan, action, finding, decision, result, error). May run **locally on LAB** freely; may only trigger **PROD mutations** through a **governed executor** that checks approval and audit context. |
| **Human approval layer** | Authoritative for: deploy, service restart, migrations, secret/env changes, any action affecting trading, alerts, DB, or runtime. Implemented as explicit **approve/deny** (e.g. Telegram callbacks, dashboard button, or signed CI gate) tied to a **task_id** and **action manifest**. |

---

# 2. Permission model

Legend: **RO** = read-only, **RW** = may perform, **AP** = allowed only after recorded human approval on PROD side, **—** = not applicable.

| Action | LAB | PROD | Approval |
|--------|-----|------|----------|
| Read repo (clone, fetch, branch) | RW | RO (via deploy checkout) | No |
| Read logs (`journalctl`, `docker logs`, app logs) | RO on PROD via SSM | RW (local) | No |
| Inspect docker/services (`ps`, `inspect`, stats) | RO on PROD | RW | No |
| Prepare patch / PR / local edit | RW | — | No |
| Run unit tests / linters on LAB | RW | — | No |
| Edit files on PROD filesystem | — | AP | **Yes** |
| `git pull` / deploy image on PROD | — | AP | **Yes** |
| Restart containers / systemd units | — | AP | **Yes** |
| Run DB migrations | — | AP | **Yes** |
| Modify secrets (SSM, `.env`, Secrets Manager) | — | AP | **Yes** |
| Change env files / compose overrides on PROD | — | AP | **Yes** |
| Run read-only SQL / SELECT on PROD DB | RO | RW | No (sensitive: restrict by IAM + query allowlist) |
| Run DDL / DML on PROD DB | — | AP | **Yes** |
| Change trading flags / kill switch / risk params | — | AP | **Yes** |
| Send Telegram alerts (informational) | RW on LAB bot if configured | RW on PROD | No if non-destructive broadcast; **Yes** if tied to executed change |
| Impersonate production Telegram command bot polling | — | PROD only | **Yes** if changing token assignment (normally never from LAB) |

**Rule of thumb:** If PROD **behavior or persisted state** changes, it needs **AP**. If it is **observation or LAB-local** work, it does not.

---

# 3. Task lifecycle

| State | Meaning | Typical actions |
|-------|---------|-----------------|
| **requested** | Human or system opened a governed task (title, scope, severity). | Create `task_id`, initial `plan` or `finding` event. |
| **planned** | Agent or human outlined steps, risks, rollback. | Emit `plan` events; optional human ack (not necessarily approval). |
| **investigating** | Read-only work: logs, code, repro on LAB. | `action` + `finding` events; no PROD writes. |
| **findings_ready** | Root cause / options documented. | `finding` + `decision` (recommendation) events. |
| **patch_ready** | Diff or PR exists; validated on LAB. | Link artifact (branch, PR, patch digest) in `result` or `finding`. |
| **awaiting_approval** | Manifest of PROD actions submitted; blocked until human decision. | `decision` (pending); PROD executor **must not** run without approved manifest. |
| **applying** | Approved steps run **on PROD** (automated or runbook). | `action` events with `approved: true`; stream `result` / `error`. |
| **validating** | Smoke checks, health, spot log grep, canary. | `action` (read-only checks) + `finding` or `result`. |
| **completed** | Success criteria met; task closed. | Final `result`; archive timeline. |
| **failed** | Blocked error or rollback. | `error` + `finding`; may re-enter **planned** or **awaiting_approval** after fix. |

Invalid transitions (policy): **applying** without **awaiting_approval** + stored approval record → denied by executor.

---

# 4. Event / channels model

All events append to an audit stream (DB table and/or JSONL). Use a single envelope:

**Envelope (required on every event):** `event_id`, `ts` (ISO8601 UTC), `task_id`, `type`, `actor` (`human` \| `agent` \| `system`), `environment` (`lab` \| `prod`), `payload`.

## 4.1 `plan`

- **Purpose:** Intent, steps, risk, rollback sketch.
- **Required fields:** `summary`, `steps` (array of strings).

```json
{
  "event_id": "01JQZ...",
  "ts": "2025-03-22T18:00:00.000Z",
  "task_id": "gov-2025-03-22-fix-telegram-task",
  "type": "plan",
  "actor": "agent",
  "environment": "lab",
  "payload": {
    "summary": "Verify PROD telegram_commands.py vs repo; redeploy if skew",
    "steps": [
      "Grep running container for handler_name == task",
      "Correlate logs for /task send",
      "If stale, deploy image tag main-abc"
    ],
    "risk": "low",
    "rollback": "Redeploy previous image tag"
  }
}
```

## 4.2 `action`

- **Purpose:** Something was run or attempted (command, API call, deploy step).
- **Required fields:** `name`, `status` (`started` \| `completed` \| `skipped`), `target` (e.g. `atp-prod:backend-aws`).

```json
{
  "event_id": "01JQZ...",
  "ts": "2025-03-22T18:05:12.000Z",
  "task_id": "gov-2025-03-22-fix-telegram-task",
  "type": "action",
  "actor": "system",
  "environment": "prod",
  "payload": {
    "name": "docker_compose_pull_backend_aws",
    "status": "completed",
    "target": "atp-prod:backend-aws",
    "approved_manifest_id": "mfst-01JQZ",
    "command_digest": "sha256:...",
    "duration_ms": 42000
  }
}
```

## 4.3 `finding`

- **Purpose:** Evidence, metrics, file excerpt pointers (not necessarily full logs).

```json
{
  "event_id": "01JQZ...",
  "ts": "2025-03-22T18:07:00.000Z",
  "task_id": "gov-2025-03-22-fix-telegram-task",
  "type": "finding",
  "actor": "agent",
  "environment": "lab",
  "payload": {
    "title": "Running container lacks /task early-dispatch",
    "severity": "high",
    "evidence": {
      "container_path": "/app/app/services/telegram_commands.py",
      "grep_exit_code": 1
    }
  }
}
```

## 4.4 `decision`

- **Purpose:** Human or policy gate outcome.

```json
{
  "event_id": "01JQZ...",
  "ts": "2025-03-22T18:10:00.000Z",
  "task_id": "gov-2025-03-22-fix-telegram-task",
  "type": "decision",
  "actor": "human",
  "environment": "prod",
  "payload": {
    "decision": "approved",
    "approver": "carlos",
    "manifest_id": "mfst-01JQZ",
    "scope": ["deploy:backend-aws", "restart:backend-aws"],
    "notes": "Deploy after market quiet window"
  }
}
```

## 4.5 `result`

- **Purpose:** Outcome of a phase or whole task.

```json
{
  "event_id": "01JQZ...",
  "ts": "2025-03-22T18:20:00.000Z",
  "task_id": "gov-2025-03-22-fix-telegram-task",
  "type": "result",
  "actor": "system",
  "environment": "prod",
  "payload": {
    "outcome": "success",
    "checks": [
      { "name": "health_endpoint", "ok": true },
      { "name": "telegram_task_smoke", "ok": true }
    ],
    "summary": "Image main-abc live; /task creates Notion row"
  }
}
```

## 4.6 `error`

- **Purpose:** Failure with enough context to retry safely.

```json
{
  "event_id": "01JQZ...",
  "ts": "2025-03-22T18:21:30.000Z",
  "task_id": "gov-2025-03-22-fix-telegram-task",
  "type": "error",
  "actor": "system",
  "environment": "prod",
  "payload": {
    "phase": "applying",
    "code": "DEPLOY_FAILED",
    "message": "docker compose pull: manifest unknown",
    "retryable": true,
    "details": { "image": "atp-backend:main-abc" }
  }
}
```

---

# 5. Visibility model

| Surface | Content | Audience |
|---------|---------|----------|
| **Telegram** | Short lines: task state changes, approval requests (with **task_id** + 1-line scope), pass/fail of **applying** / **validating**. Link or opaque id to dashboard for detail. | On-call / approver |
| **Dashboard** | Full timeline: filters by `task_id`, event type, environment; expandable payloads; manifest diff; approval buttons. | Deep debugging |
| **Governance timeline API** | Read-only merged view: `GET /api/governance/tasks/{task_id}/timeline` and `GET /api/governance/by-notion/{page_id}/timeline` (Bearer token). See [CONTROL_PLANE_TASK_VIEW.md](./CONTROL_PLANE_TASK_VIEW.md). | Operators / scripts (Phase 1; no UI yet) |
| **Logs / database** | Append-only **structured** events (envelope + payload); correlation ids; optional mirror to JSONL for agents. | Audit, forensics |

**Principle:** Telegram = **paging + approve**; dashboard = **narrative**; DB = **truth**.

---

# 6. Approval model

## 6.1 Requires human approval (PROD)

- Deploy / rollback of application images
- Container or host **restart** of trading-affecting services
- **Database migrations** or destructive SQL
- **Secrets** and **environment** changes (SSM, `.env`, compose env)
- Infra toggles: Telegram token routing, poller enablement, kill switch, strategy flags
- Any automated **write** to PROD repo checkout used for runtime

## 6.2 Does not require approval

- LAB-local edits, tests, lint
- Read-only PROD inspection (logs, metrics, `docker ps`, read-only DB)
- Draft plans and findings (events only)
- Creating a **governance task** and uploading a **patch** to a branch (no merge to deploy branch without approval)

## 6.3 Implementation note

ATP already has patterns for **persisted approval** (`agent_approval_states`, `agent_telegram_approval.py`). Reuse the same **idea**: a row keyed by `task_id` / `manifest_id` with status `pending` → `approved` | `denied`. Extend or parallel a **governance_manifest** table if agent bundles and deploy manifests differ.

---

# 7. Minimum implementation plan

## Phase 1 — Quick win (days)

- **Build:** IAM + SSM/session policy: LAB role = **read-only** on PROD; remove broad `ssm:SendCommand` write unless wrapped. Runbook: “All PROD changes via approved script on PROD or CI.”
- **Outcome:** LAB cannot accidentally `docker compose up` on PROD.
- **Risk reduction:** Cuts largest foot-gun without new services.

## Phase 2 — Proper governance (1–2 weeks)

- **Build:** `governance_tasks` + `governance_events` tables (or extend existing agent tables); small API on **PROD** to append events and to submit **manifest**; Telegram notification on **awaiting_approval**; executor on PROD that **only** runs whitelisted commands when `manifest_id` is **approved**.
- **Outcome:** Every production mutation has a **task_id**, **manifest**, and **decision** record.
- **Risk reduction:** Traceability and enforceable gate.

## Phase 3 — Hardened production workflow (ongoing)

- **Build:** Dashboard page for timeline + approve; signed manifests (hash of command list); optional dual approval for migrations/secrets; automatic rollback hooks; rate limits on executor.
- **Outcome:** Production-grade audit and safer blast radius.
- **Risk reduction:** Abuse and mistake resistance.

---

# 8. Suggested code changes (ATP codebase)

Aligned with what exists today:

| Concern | Suggestion |
|---------|------------|
| **Emit events** | Start in: `agent_task_executor.py` (prepare/execute boundaries), `agent_telegram_approval.py` (request/approve/deny), any future `governance_executor.py`. Wrap with `log_governance_event(type, task_id, payload)` that writes DB + optional JSONL. |
| **Task state** | New table `governance_tasks` (`task_id`, `status`, `title`, `created_at`, `updated_at`, `created_by`, `environment_origin`) or reuse a single **workflow id** shared with Notion/agent tasks if you want one id everywhere. |
| **Approval state** | Extend **`AgentApprovalState`** or add `governance_manifests` (`manifest_id`, `task_id`, `payload_json`, `status`, `approved_by`, `decision_at`). Keep **PROD DB** as source of truth. |
| **Persist structured events** | Table `governance_events` with indexed `(task_id, ts)` and `type`; or reuse `log_agent_event` pattern in `agent_activity_log.py` and **also** mirror to DB for dashboard queries (file-only is weak for multi-host). |
| **Telegram summaries** | Small function: on event insert, if `type in (decision, result, error)` or state transition to **awaiting_approval**, format 2–4 lines + `task_id`, call existing Telegram send helper (same channel as operational alerts). |

**Minimal schema sketch:**

- `governance_tasks(id, external_ref, status, title, meta_json, created_at, updated_at)`
- `governance_events(id, task_id, type, actor, environment, payload_json, ts)`
- `governance_manifests(id, task_id, digest, commands_json, status, approved_by, decision_at)`

---

# 9. Naming and ops cleanup

| Old / vague | Suggested stable name |
|-------------|------------------------|
| PROD EC2 | **atp-prod** |
| LAB EC2 | **atp-lab** |
| Environment tags | `ATP_ENV=prod` \| `ATP_ENV=lab` |
| SSH / SSM targets | Use **DNS** (`atp-prod.internal`) or **SSM resource tags** (`Environment=atp-prod`) |

**Avoid hardcoded instance IDs in scripts:**

- Read from **SSM Parameter Store**: `/atp/prod/instance_id` maintained by Terraform/user-data, or
- `aws ec2 describe-instances --filters "Name=tag:Name,Values=atp-prod" --query ...`, or
- **AWS Resource Groups** / **Systems Manager** managed node lists by tag.

Local helper pattern: `scripts/ops/target.sh` exports `ATP_SSM_TARGET=atp-prod` and maps to tag query.

---

# 10. Final recommendation

Keep **two-box** architecture: **atp-lab** (OpenClaw + analysis) and **atp-prod** (runtime). Add **governance** as a thin layer: **events everywhere**, **approval before any PROD mutation**, **LAB read-only to PROD** via IAM. Implement **Phase 1** immediately (permissions + runbook), then **Phase 2** (DB events + manifest executor + Telegram approval) so agent work stays fast in LAB while PROD stays controlled and visible.

Do **not** replace OpenClaw; **instrument** it and **gate** its outputs at the PROD boundary.

---

*Document version: 1.0 — internal use.*
