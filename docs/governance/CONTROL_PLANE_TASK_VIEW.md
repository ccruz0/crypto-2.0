# Control-plane task timeline (Phase 1 + resolve usability)

Read-only **view model** over existing PostgreSQL rows. It does **not** introduce a new source of truth.

**Phase 2:** `GET /api/governance/resolve` maps a single handle (`task_id`, `notion_page_id`, or `manifest_id`) to normalized ids, status, manifest hints, and timeline paths — convenience only; the DB rows remain authoritative.

## Source-of-truth hierarchy

| Layer | Role |
|--------|------|
| **PROD mutation** | `governance_manifests` (`digest`, `approval_status`) + `governance_executor` |
| **Lifecycle + audit (DB)** | `governance_tasks`, `governance_events` |
| **Prepared agent work** | `agent_approval_states.prepared_bundle_json` (`bundle_fingerprint`, `bundle_identity`, …) |
| **Human narrative** | Notion task page (not mirrored into this API beyond linkage) |
| **This timeline API** | Presentation / operator clarity only |

## Correlation spine

- **Governance task id:** often `gov-notion-<notion_page_id>` for Notion-originated work (`notion_to_governance_task_id` in `governance_agent_bridge.py`). On AWS with **`ATP_GOVERNANCE_AGENT_ENFORCE`**, that row may be created **earlier** (Notion prepare after claim, or before Telegram approval preflight) via **`ensure_notion_governance_task_stub`** — **without** a manifest. **Presence of a governance task row is not execution approval**; **`governance_manifests`** + approval status still define what may run.
- **`correlation_id`:** in API responses, equal to `governance_task_id` (stable handle for the row).
- **`manifest_id` + `digest`:** bind what may execute under enforce.
- **`bundle_fingerprint`:** binds prepared callback identity; may appear in manifest `commands_json[0].audit` and in `agent_approval_states` JSON.

## API (Bearer token)

Same auth as other governance routes: `GOVERNANCE_API_TOKEN` or `OPENCLAW_API_TOKEN` as `Authorization: Bearer <token>`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/governance/resolve` | **Query (exactly one):** `task_id` (= `governance_tasks.task_id`), `notion_page_id` (Notion page UUID; maps to `gov-notion-{page_id}`), or `manifest_id`. Returns `governance_task_id`, `notion_page_id` (when derivable), `current_status`, `current_manifest_id`, `latest_manifest_id`, and timeline path/url fields. **400** if zero or multiple query params; **404** if nothing resolves. |
| GET | `/api/governance/tasks/{task_id}/timeline` | Timeline for an existing `governance_tasks.task_id`. **404** if the row is missing. |
| GET | `/api/governance/by-notion/{page_id}/timeline` | Resolves to `gov-notion-{page_id}` then same as above. **404** if that governance task row was never created. |

### `GET /governance/resolve` response (compact)

| Field | Description |
|--------|-------------|
| `governance_task_id` | Row in `governance_tasks`. |
| `notion_page_id` | Parsed from `gov-notion-…` when applicable; else `null`. |
| `current_status` | `governance_tasks.status`. |
| `current_manifest_id` | From task row (may be `null`). |
| `latest_manifest_id` | Newest `governance_manifests.created_at` for this task (may be `null`). |
| `timeline_by_task_path` | e.g. `/api/governance/tasks/{task_id}/timeline` (URL-encoded segment when needed). |
| `timeline_by_notion_path` | Same as by-notion timeline path when `notion_page_id` is known; else `null`. |
| `timeline_by_task_url`, `timeline_by_notion_url` | Absolute URLs when `API_BASE_URL` / `PUBLIC_BASE_URL` resolves; else `null`. |

Telegram governance summaries (approval / deny / complete / fail, and agent **prod_mutation** approval cards under enforce) append a short **Notion** / **mfst** line when applicable plus **Timeline** (`<a href=…>` when base URL is set, else a copy-paste path).

## Response shape (top level)

| Field | Description |
|--------|-------------|
| `correlation_id` | Same as `governance_task_id`. |
| `governance_task_id` | Primary key string in `governance_tasks`. |
| `notion_page_id` | Set when `task_id` starts with `gov-notion-`; else `null`. |
| `current_status` | `governance_tasks.status`. |
| `risk_level`, `source_type`, `source_ref`, `current_manifest_id` | From task row. |
| `task_created_at`, `task_updated_at` | ISO8601 timestamps. |
| `coverage` | Honesty flags (see below). |
| `manifests` | All `governance_manifests` for this `task_id`, newest metadata preserved. |
| `agent_bundle` | Summary from `agent_approval_states` when Notion id matches and a row exists; else `null`. |
| `signal_counts` | Read-model aggregate: `{ "failed", "drift", "classification_conflict", "blocked" }` — counts of timeline items with that **primary** `signal` (see below). Not a lifecycle state machine. |
| `timeline` | Ordered list derived from `governance_events` (ascending `ts`). |

### Timeline signals (read model)

Per-event **`signal`** is computed in **`governance_timeline.resolve_timeline_event_signal`**: if **`payload_json.signal_hint`** is present and one of the known values, that value is used; otherwise **`derive_timeline_event_signal`** runs (same as before) on `event_type`, derived **`phase`**, full payload dict, and the **summary** string. **Derivation priority:** `failed` → `classification_conflict` → `drift` → `blocked` → `null`.

**Explicit hints:** new emissions set **`signal_hint`** on obvious paths (e.g. executor pre-execute / validation errors, step failures, failed results, manifest digest integrity error, expiry / deny / supersede decisions, plus agent-path **`classification_conflict`**, **`blocked`** (execute-prepared manifest gate), and **`drift`** (bundle fingerprint mismatch when enforce blocks)). **Older rows** without `signal_hint` still rely on derivation only. Agent-path emissions use **`governance_service.emit_visibility_error_if_governance_task_exists`**: they are written **only when** a **`governance_tasks`** row already exists for that `task_id`; otherwise only logs/JSONL apply. Hints are **not** a separate state machine — they are optional payload metadata to stabilize the read model.

| `signal` | Typical sources (non-exhaustive) |
|----------|----------------------------------|
| `failed` | `event_type == error`, `phase == failed`, or payload/summary wording |
| `classification_conflict` | e.g. `governance_classification_conflict` in payload |
| `drift` | e.g. `bundle_drift`, `governance_bundle_drift` (non-`error` events can still be `drift`) |
| `blocked` | e.g. `governance_execution_blocked`, `prod_mutation_blocked`, or `blocked` as a word |

### `coverage`

| Field | Meaning |
|--------|---------|
| `governance_task_present` | Always `true` when the response is returned (404 otherwise). |
| `agent_bundle_present` | `true` if an `agent_approval_states` row exists for the extracted Notion page id. |
| `notion_linked` | `true` if `notion_page_id` is non-null (`gov-notion-` prefix). |
| `has_manifests` | Any manifests for this task. |
| `has_events` | Any `governance_events` rows. |
| `timeline_scope` | `full` — Notion-linked **and** agent bundle row present; `partial` — Notion-linked but no agent row; `governed_only` — manual / non–`gov-notion-` task id. |

Legacy or partially governed work may show `timeline_scope: partial` or empty `timeline` even when manifests exist.

### `manifests[]` items

| Field | Description |
|--------|-------------|
| `manifest_id`, `digest`, `digest_prefix` | Full digest and shortened display prefix. |
| `approval_status`, `scope_summary`, `risk_level` | From manifest row. |
| `approved_by`, `approved_at`, `expires_at`, `created_at` | When present. |
| `bundle_fingerprint_prefix` | From first command’s `audit.bundle_fingerprint` when JSON parses, else `null`. |

### `agent_bundle` (when present)

| Field | Description |
|--------|-------------|
| `notion_task_id` | Matches Notion page id (`agent_approval_states.task_id`). |
| `approval_row_status`, `execution_status` | From approval row. |
| `bundle_fingerprint`, `bundle_fingerprint_prefix` | From prepared JSON. |
| `governance_action_class`, `selection_reason` | From bundle / `bundle_identity` when present. |

### `timeline[]` items

| Field | Description |
|--------|-------------|
| `ts` | Event time (ISO8601). |
| `phase` | Derived UI phase from `event_type` + payload (e.g. `awaiting_approval`, `applying`, `investigating`). |
| `event_type` | DB `governance_events.type` (`plan`, `action`, `finding`, `decision`, `result`, `error`). |
| `source` | Always `governance_events` for this phase. |
| `actor` | `{ "type", "id" }` from row. |
| `environment` | `lab` / `prod`. |
| `summary` | One-line text derived from payload. |
| `signal` | `failed` \| `drift` \| `classification_conflict` \| `blocked` \| `null` — backend read-model tag for this row. |
| `links` | `governance_task_id`, optional `notion_page_id`, `manifest_id`, `manifest_digest_prefix`, `bundle_fingerprint_prefix` when inferable. |
| `payload_ref` | `governance_events:{event_id}` (lookup via existing events API or SQL). |
| `compact_payload` | Small subset of `payload_json` for quick scanning (truncated). May include `signal_hint` when present. |

## Operator UI (read-only)

- **Route:** `/governance/task` (Next.js app).
- **Flow:** operator enters a single lookup string and a **Bearer token** (same as `GOVERNANCE_API_TOKEN` / `OPENCLAW_API_TOKEN` used for curl). The browser calls **`GET /api/governance/resolve`** with `task_id`, then `notion_page_id`, then `manifest_id` until one returns **200** (404 tries the next). It then loads **`GET /api/governance/tasks/{governance_task_id}/timeline`** and renders header, **coverage** flags, **manifests**, **agent_bundle**, and **timeline** (read-only; no mutations).
- **Usability:** **Copy** buttons for governance task id, Notion page id, manifest ids, digest / bundle fingerprint prefixes, and timeline URL; **quick links** for `source_ref` when it is already `https://…`, else an **inferred Notion URL** from the page id; **timeline JSON** link + copy (new tab usually **401** without Bearer—use **Copy** + curl). Timeline table includes **actor** (`type · id`), **signal** column and row tint driven by API **`signal`** / **`signal_counts`** (not client-side string matching on summaries). Each row has **+** / **−** to **expand read-only details**: **`payload_ref`**, **`links`** (manifest id, digest prefix, bundle fingerprint prefix when present), **`environment`**, **`actor`**, and pretty-printed **`compact_payload`** (includes **`signal_hint`** when the backend included it). **Copy** on `payload_ref` and full JSON. Multiple rows may stay open; collapsed rows still show **`payload_ref`** as a single line under **links / ids** when the row is collapsed. Clearer **empty** and **error** states (401 / 404 hints). **Enter** submits lookup.
- **Timeline filtering (client-only):** operators can restrict rows by API **`signal`**: **All**, **Failed**, **Drift**, **Class conflict**, **Blocked**. Filters apply only in the browser; the timeline API response is unchanged. **Important only** shows rows where **`signal`** is non-null. **Summary chips** (from **`signal_counts`**) are clickable: click applies that signal filter; click again clears back to **All**. When no rows match, the UI shows a short message (e.g. “No drift events in this task”). Coverage / manifests / agent bundle sections are **not** hidden by filters.
- **Quick navigation:** after load, a **Quick navigation** strip provides anchor links to **Task**, **Manifests**, **Agent bundle**, and **Timeline**, plus **Jump to latest** buttons for the newest manifest row (by **`created_at`**, lexicographic ISO) and the **most recent** timeline row per signal (**last row** in the API order — ascending time — is treated as latest). **Signal jump** actions (**Failed**, **Blocked**, **Drift**, **Class conflict**) first set the timeline **Signal** filter to that signal and turn **Important only** **on**, so the target row is **visible**, then **scroll** and briefly **highlight** it. **Manifest** jump does not change timeline filters (the manifests table is never hidden by those filters). Buttons are **disabled** when there is nothing to jump to (e.g. no manifests, no failed events).
- **Token storage:** `sessionStorage` for the tab only (`atp_governance_task_view_bearer`); not a server-side secret.
- **Entry:** link from **Monitoring** (`/monitoring`) or open `/governance/task` directly.
- **Limitations:** requires browser access to the same API base as the rest of the dashboard (`getApiUrl()`); CORS/network must allow `Authorization` to the backend. Does not replace curl for automation. **`signal`** values are backend read-model summaries (pattern-matched on existing payloads), not persisted state. **Jump-to-latest manifest** assumes ISO8601 **`created_at`** strings sort correctly; if all are missing, the **last table row** is used. Rows hidden only by **manual** filter choice (without using signal jump) are still omitted from the table until you switch back to **All** or clear **Important only**. **No automated frontend tests** for this page — use **Manual verification (governance task UI)** below.

### Manual verification (governance task UI)

1. Open `/governance/task`, set Bearer, load a task with a non-empty timeline.
2. Use **Signal** buttons to show only **Blocked** (or another signal); confirm counts match visible rows and the “Showing *x* of *y*” line.
3. Enable **Important only** with **All** signals; confirm only rows with a non-null **signal** column appear.
4. Click a **signal_counts** chip twice: first applies filter, second returns to **All**.
5. Set timeline filters to something that would hide failed rows (e.g. **Drift** only), then use **Jump to latest → Failed**: confirm **Signal** switches to **Failed**, **Important only** is on, the row scrolls into view, and the highlight appears.
6. With multiple manifests, confirm **Jump to latest → Manifest** targets the row with the latest **`created_at`** when set.
7. Confirm **coverage** and empty sections still render when timeline is empty or filters exclude every row.
8. Expand a timeline row (**+**): confirm **compact_payload**, **links**, and **payload_ref** appear; **Copy** on JSON; collapse (**−**) and confirm filters/jumps still work.

### What to inspect first (operators)

1. **Coverage** strip — scope (`full` / `partial` / `governed_only`) and `has_events` / `has_manifests`.
2. **signal_counts** chips — quick density of **failed** / **blocked** / **drift** / **classification_conflict**.
3. **Expanded row** — **`signal_hint`** inside **compact_payload** when present; **links.manifest_id** / **manifest_digest_prefix** for manifest correlation.
4. **Manifests** table vs **timeline** decisions — approval status and digest prefix alignment.

### Smoke test checklist (backend + frontend)

**Backend (after deploy)** — from an environment with DB + token:

- `GET /api/health` (or host health per [deploy runbook](../runbooks/deploy.md)).
- `GET /api/governance/resolve?notion_page_id=<known_page_or_skip>` with `Authorization: Bearer …` — expect **200** or **404** (not **5xx**).
- `GET /api/governance/tasks/<gov-notion-…>/timeline` with Bearer — expect **200** JSON with `timeline`, `signal_counts`, `coverage`; spot-check `timeline[].signal` and `compact_payload` on at least one event.

**Frontend (after deploy)**

- Open `/governance/task`, paste Bearer, load a known task — resolve + timeline render without console errors.
- Toggle **Signal** filter and **Important only**; use **Jump to latest → Failed** (if events exist); expand one row and verify details.

**Limits:** expand shows only fields returned by the timeline API (truncated **compact_payload** per backend); full raw `payload_json` is not loaded on this page — use SQL or a future events API if needed.

## Implementation

- Builder: `backend/app/services/governance_timeline.py` — `build_governance_timeline`, `build_governance_timeline_for_notion`, `resolve_timeline_event_signal`, `derive_timeline_event_signal` (fallback).
- Routes: `backend/app/api/routes_governance.py`.
- Resolver: `backend/app/services/governance_resolve.py`.
- Frontend: `frontend/src/app/governance/task/page.tsx`, `frontend/src/lib/governanceTaskView.ts`.
- Tests: `backend/tests/test_governance_timeline.py`, `backend/tests/test_governance_resolve.py`.

## Related docs

- [IMPLEMENTATION_NOTES.md](./IMPLEMENTATION_NOTES.md) — governance stack overview.
- [../runbooks/trace_task_end_to_end.md](../runbooks/trace_task_end_to_end.md) — operator tracing steps.
- [../runbooks/governance_approval_flow.md](../runbooks/governance_approval_flow.md) — approve / execute flow.
