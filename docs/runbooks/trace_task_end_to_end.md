# Runbook: trace one governed task end-to-end

Use this when you need to answer: *which manifest was approved, which bundle fingerprint was bound, and what happened in order?*

## 1. Pick an identifier

You need at least one of:

| You have | Use |
|----------|-----|
| Any one of Notion page id, governance `task_id`, or `manifest_id` | **Resolver (start here):** `GET /api/governance/resolve?notion_page_id=…` or `?task_id=…` or `?manifest_id=…` — returns normalized ids, status, manifest hints, and **timeline path(s)** / URLs when `API_BASE_URL` or `PUBLIC_BASE_URL` is set. |
| Notion page id (task page UUID) | Timeline: `GET /api/governance/by-notion/{page_id}/timeline` |
| Governance task id (e.g. `gov-notion-<page_id>` or manual `gov-deploy-…`) | Timeline: `GET /api/governance/tasks/{task_id}/timeline` |
| `manifest_id` from Telegram | Resolver with `manifest_id=…`, or SQL: `SELECT task_id FROM governance_manifests WHERE manifest_id = '…'` then timeline for that `task_id` |
| `bundle_fingerprint` from logs | SQL / grep: correlate to `agent_approval_states.prepared_bundle_json` and manifest `commands_json` audit |

**Auth:** `Authorization: Bearer $GOVERNANCE_API_TOKEN` (or `OPENCLAW_API_TOKEN` if configured as fallback).

### Dashboard (read-only)

Open **`/governance/task`** on the trading frontend (also linked from **Monitoring**). Paste the same Bearer token once per tab (stored in `sessionStorage`). Enter any of governance `task_id`, Notion `page_id`, or `manifest_id`; the UI resolves then loads the unified timeline. **Read-only** — no approve/execute controls. Use **Copy** on ids and the timeline URL for curl; use **quick links** for `source_ref` or an inferred Notion URL; timeline **signals** and badges come from the API (`timeline[].signal`, `signal_counts`), not browser-side string matching.

**Narrow the timeline in the UI:** use **Signal** filters (**All** / **Failed** / **Drift** / **Class conflict** / **Blocked**) and **Important only** (non-null `signal`) — client-side only; the API payload is unchanged. Click **signal_counts** chips to apply the same filter (click again to clear). **Quick navigation** jumps to sections or to the **latest** manifest row (by `created_at`) / latest row per signal (last in time order). **Jump to latest** for a **signal** auto-sets that signal filter and **Important only** so the scrolled row is visible; **Manifest** jump leaves timeline filters unchanged. Disabled jump buttons mean nothing matched. Use **+** on a timeline row to expand read-only **compact_payload**, **links**, and **payload_ref** (same response as the timeline GET; no second request). If the API is unreachable from the browser (CORS, wrong `NEXT_PUBLIC_API_URL`), use curl below.

Example (resolve then open timeline path from JSON):

```bash
curl -sS -H "Authorization: Bearer $GOVERNANCE_API_TOKEN" \
  "https://<host>/api/governance/resolve?notion_page_id=<NOTION_PAGE_ID>" | jq .

curl -sS -H "Authorization: Bearer $GOVERNANCE_API_TOKEN" \
  "https://<host>/api/governance/by-notion/<NOTION_PAGE_ID>/timeline" | jq .
```

## 2. Read the timeline response

1. Check **`coverage.timeline_scope`**: `full` vs `partial` vs `governed_only` explains how much is linked.
2. Inspect **`manifests`**: `digest`, `approval_status`, `bundle_fingerprint_prefix` (from manifest command audit when present).
3. Inspect **`agent_bundle`**: prepared-work fingerprint and `governance_action_class` when the Notion-linked approval row exists.
4. Walk **`timeline`** in order: `decision` events tie to **`links.manifest_id`** and digest prefixes. Row **`signal`** uses **`signal_hint`** from the stored payload when present; otherwise backend pattern derivation. **Agent pipeline:** classification conflicts, manifest gate blocks, and bundle drift (when enforce blocks) can appear as **`error`** rows with hints **`classification_conflict`**, **`blocked`**, and **`drift`** respectively — **only if** a **`governance_tasks`** row exists for `gov-notion-<page_id>` at the time of the signal. Timeline completeness still depends on that correlation; logs/JSONL remain the full audit when no task row is present.

## 3. SQL fallbacks (read-only)

```sql
SELECT task_id, status, current_manifest_id, updated_at
FROM governance_tasks
WHERE task_id = 'gov-notion-<page_id>' OR task_id = '<manual_id>';

SELECT manifest_id, digest, approval_status, approved_by, expires_at
FROM governance_manifests
WHERE task_id = 'gov-notion-<page_id>'
ORDER BY created_at DESC;

SELECT type, ts, payload_json
FROM governance_events
WHERE task_id = 'gov-notion-<page_id>'
ORDER BY ts ASC;

SELECT task_id, status, execution_status, LEFT(prepared_bundle_json, 200)
FROM agent_approval_states
WHERE task_id = '<notion_page_id>';
```

## 4. Logs / JSONL

- Grep backend log or `logs/agent_activity.jsonl` for `governance_`, `governance_bundle_fingerprint`, `governance_bundle_drift`, `classification_conflict`, `governance_execution_blocked`.
- The timeline surfaces the same high-signal agent cases as **`governance_events`** when a **`governance_tasks`** row exists; **logs/JSONL remain the secondary, authoritative audit** for everything else (including paths where no governance task row was ever created).

## 5. Common gaps

- **404 on by-notion timeline:** No `governance_tasks` row yet for `gov-notion-<page_id>` (e.g. enforce off, prepare/approval never ran, or failure before stub). When **`ATP_GOVERNANCE_AGENT_ENFORCE`** is on and prepare/approval ran on AWS, a row is usually created early for correlation — **still** not a substitute for checking manifests for authorization.
- **Empty `timeline`:** No `governance_events` written yet (or task created outside normal emit paths).
- **Agent signal missing from timeline:** Operator-visible classification conflict / drift / execution-blocked may exist only in logs if there was **no** resolvable `governance_tasks` row at emit time (by design — no synthetic task rows).
- **`partial` scope:** Notion-linked governance task exists but no `agent_approval_states` row for that page id (e.g. deploy-only manifest without prepared bundle).

See [CONTROL_PLANE_TASK_VIEW.md](../governance/CONTROL_PLANE_TASK_VIEW.md) for the full response model.
