# Runbook: governance approval and PROD execution

## Prerequisites

- DB migration applied: `backend/migrations/20260322_create_governance_tables.sql`
- Bearer token: `GOVERNANCE_API_TOKEN` or `OPENCLAW_API_TOKEN` in the server environment
- Base URL: `https://<host>/api` (example paths below use `/api/governance/...`)

## Agent release-candidate deploy (Telegram) — wired path

When **`ATP_GOVERNANCE_AGENT_ENFORCE=true`** and **`ENVIRONMENT=aws`**:

1. Scheduler sends **release-candidate deploy approval** (`send_release_candidate_approval`).
2. Before the Telegram is delivered, the backend creates:
   - Governance task `gov-notion-<notion_page_id>`
   - A pending manifest whose `commands_json` includes **`agent_deploy_bundle`** (strategy patch + GitHub `workflow_dispatch`)
   - `TradingSettings` key `governance_deploy_manifest:<notion_page_id>` → `manifest_id`
3. The approval message includes **`manifest_id`**, the **`gov-notion-…`** task id, the Notion page id, and a **timeline** link or path (when the API base URL is configured) so operators can jump to the unified timeline without guessing handles.
4. On **Approve Deploy**, the handler calls **`approve_manifest`** then **`execute_governed_manifest`** — it does **not** run the legacy inline patch/deploy path.
5. Digest tampering after creation invalidates approval; execution is denied with governance **error** events.

**Trace in DB:** `governance_events` where `task_id = 'gov-notion-<notion_id>'`; `governance_manifests` by `manifest_id`; agent activity JSONL may mirror `governance_*` events.

**Without agent enforce:** legacy behavior (direct `apply_prepared_strategy_patch_after_approval` + `trigger_deploy_workflow` on Approve Deploy).

## Agent task execution (`execute_prepared_notion_task`) — wired path

When **`ATP_GOVERNANCE_AGENT_ENFORCE=true`** and **`ENVIRONMENT=aws`**, and the callback pack classifies as **`prod_mutation`** (`backend/app/services/agent_execution_policy.py` — e.g. strategy-patch, profile-setting-analysis):

1. **`send_task_approval_request`** (before Telegram is sent) creates:
   - The same governance task id `gov-notion-<notion_page_id>` (shared with deploy manifests over the task lifetime)
   - A pending manifest whose `commands_json` includes **`agent_execute_prepared_pipeline`** with an auditable **`audit`** object (`selection_reason`, callback names, flags)
   - `TradingSettings` key **`governance_execute_manifest:<notion_page_id>`** → `manifest_id`
2. The Telegram card includes **`manifest_id`**, governance + Notion ids, and a **timeline** link/path (same pattern as deploy) for the execution digest.
3. On **Approve**, **`record_approval`** also calls **`approve_manifest`** for that execution manifest. **`agent_approval_states.approved` alone is not sufficient** for PROD apply when enforce is on.
4. When **`execute_prepared_notion_task`** runs (scheduler or **`execute_prepared_task_from_telegram_decision`** → **`execute_prepared_task_if_approved`**), it checks **`is_manifest_approved_and_valid(..., expected_commands=...)`** and runs **`execute_governed_manifest`**, which executes the whitelisted step. The step loads the approved bundle from DB and calls **`execute_prepared_task_if_approved`** with **`_governance_pipeline_internal`** set so the gate is not re-entered.
5. **Patch-prep / investigation** callbacks (non–`prod_mutation`) **do not** use this manifest; they behave as before.

### Bundle fingerprint / re-selection drift

Callables are not stored in Postgres; **`agent_approval_states.prepared_bundle_json`** holds `prepared_task`, approval metadata, **`bundle_identity`**, and **`bundle_fingerprint`**. On load for execution, callbacks are still resolved via **`select_default_callbacks_for_task`**, but:

- If a fingerprint exists, **Notion type refresh is skipped** so task routing inputs match the approved snapshot.
- At **`execute_prepared_task_if_approved`**, the resolved apply/validate/deploy identities are hashed again and compared to **`bundle_fingerprint_approved`**.

The execution manifest’s **`audit.bundle_fingerprint`** (in `commands_json`) is part of the signed digest, so tampering or “silent” callback changes break **`is_manifest_approved_and_valid`** or the post-load drift check.

**If drift is detected (`governance_bundle_drift_detected`, or `governance.error=bundle_drift`):**

1. Confirm the Notion task was not edited in a way that changes routing (type/title/area) after approval.
2. Re-run preparation + **`send_task_approval_request`** so a new bundle JSON + manifest digest are created.
3. Have the operator **Approve** again in Telegram.

**After upgrading to a build that adds fingerprints:** in-flight approvals whose manifest `audit` omits `bundle_fingerprint` may fail digest validation on first execute; send a **fresh** approval to mint a new manifest.

**Tracing:** `governance_events` / `governance_manifests` for `gov-notion-<id>`; agent activity JSONL: `governance_bypassed_legacy_path` when enforce is off; `governance_execution_blocked` when enforce is on but manifest is missing or not approved; grep logs for `governance_bundle_fingerprint_*` and `governance_bundle_drift_detected`.

**Fail-closed:** If manifest creation fails in `send_task_approval_request`, the Telegram is **not** sent. If execution runs without a valid approved digest, `execute_prepared_notion_task` returns failure with a **`governance`** object on the result. If **`bundle_drift`** is returned, execution did not run the loaded callbacks — re-approve after fixing metadata.

## End-to-end flow

### 1. Create a governance task

```http
POST /api/governance/tasks
Authorization: Bearer <token>
Content-Type: application/json

{
  "task_id": "gov-deploy-2025-03-22",
  "source_type": "manual",
  "risk_level": "medium",
  "title": "Redeploy backend-aws"
}
```

Optional transitions (e.g. document work in DB only):

```http
POST /api/governance/tasks/gov-deploy-2025-03-22/transition
Authorization: Bearer <token>
Content-Type: application/json

{ "to_state": "investigating", "actor_id": "carlos", "reason": "logs reviewed" }
```

### 2. Attach a manifest (moves task toward `awaiting_approval`)

```http
POST /api/governance/tasks/gov-deploy-2025-03-22/manifests
Authorization: Bearer <token>
Content-Type: application/json

{
  "commands": [
    { "type": "docker_compose_restart", "profile": "aws", "service": "backend-aws", "compose_relative": "docker-compose.yml" },
    { "type": "http_health", "url": "http://127.0.0.1:8000/health" }
  ],
  "scope_summary": "Restart backend-aws then hit local health",
  "risk_level": "medium",
  "attach_and_await_approval": true
}
```

Response includes `manifest_id` and `digest`. Telegram may show **approval needed** (if Claw is configured).

### 3. Human approval

```http
POST /api/governance/manifests/<manifest_id>/approve
Authorization: Bearer <token>
Content-Type: application/json

{ "approved_by": "carlos" }
```

Approval is bound to the **exact digest**. TTL starts (see `IMPLEMENTATION_NOTES.md`).

To deny:

```http
POST /api/governance/manifests/<manifest_id>/deny
Authorization: Bearer <token>
Content-Type: application/json

{ "denied_by": "carlos", "reason": "wrong window" }
```

### 4. Execute (PROD mutation)

Task must be in `awaiting_approval`.

```http
POST /api/governance/execute
Authorization: Bearer <token>
Content-Type: application/json

{
  "task_id": "gov-deploy-2025-03-22",
  "manifest_id": "<manifest_id>"
}
```

Response includes `ok`, `steps`, and on failure `error` (events are still committed for audit).

### 5. Inspect events

```http
GET /api/governance/tasks/gov-deploy-2025-03-22/events?limit=100
Authorization: Bearer <token>
```

### 5b. Merged timeline (manifests + agent bundle + ordered events)

Read-only operator view (same Bearer token):

```http
GET /api/governance/tasks/gov-deploy-2025-03-22/timeline
Authorization: Bearer <token>
```

For Notion-originated tasks (`gov-notion-<notion_page_id>`):

```http
GET /api/governance/by-notion/<notion_page_id>/timeline
Authorization: Bearer <token>
```

Response shape and `coverage` flags: [CONTROL_PLANE_TASK_VIEW.md](../governance/CONTROL_PLANE_TASK_VIEW.md). Tracing guide: [trace_task_end_to_end.md](./trace_task_end_to_end.md).

## When `POST /api/monitoring/backend/restart` returns 403

Set `ATP_GOVERNANCE_ENFORCE=true` on AWS. Use the governed flow above instead of the monitoring restart button.

To allow the legacy endpoint again (not recommended on PROD): unset or set `ATP_GOVERNANCE_ENFORCE=false`.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| `not approved` | Manifest `approval_status` must be `approved`; call approve endpoint |
| `approval expired` | Re-approve within TTL or create a new manifest |
| `manifest invalidated (digest mismatch)` | Commands JSON was changed after creation; create a **new** manifest and re-approve |
| `command list does not match approved digest` | Executor’s parsed commands don’t match stored JSON — corruption or bug |
| `task not in awaiting_approval` | Transition task correctly; create manifest with `attach_and_await_approval: true` |
| `service not allowed` | Only `backend-aws` is allowed for `docker_compose_restart` in v1 |

## SQL (read-only debugging)

```sql
SELECT task_id, status, current_manifest_id, risk_level, updated_at FROM governance_tasks ORDER BY updated_at DESC LIMIT 20;
SELECT manifest_id, task_id, digest, approval_status, approved_by, expires_at FROM governance_manifests ORDER BY created_at DESC LIMIT 20;
SELECT task_id, type, ts, payload_json FROM governance_events WHERE task_id = 'gov-deploy-2025-03-22' ORDER BY ts DESC LIMIT 50;
```
