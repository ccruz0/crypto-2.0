# Jarvis Phase 4B-5 Production Read-Only Launch

**Status:** Active (2026-06-13)  
**Scope:** Enable Phase 4B proposal generation in production; keep all Phase 5 write gates disabled.

## Safety gate matrix

| Gate | Variable | Production value | Effect when false |
|------|----------|------------------|-------------------|
| Phase 4B proposals | `JARVIS_4B_PROPOSALS_ENABLED` | **true** | Blocks `POST .../propose-patch`; eligibility adds `phase4b_proposals_disabled` |
| Min confidence | `JARVIS_4B_MIN_CONFIDENCE` | **50** | Eligibility reason `confidence_below_threshold` |
| Patch apply (Gate 1) | `JARVIS_PATCH_APPLY_ENABLED` | **false** | `approve-apply` returns 403 |
| PR creation (Gate 2) | `JARVIS_PR_CREATION_ENABLED` | **false** | `approve-pr` blocked in `check_pr_creation_allowed()` |
| GitHub write | `JARVIS_GITHUB_WRITE_ENABLED` | **false** | No `git push`; PR service blocked |
| Double approval | `JARVIS_REQUIRE_DOUBLE_APPROVAL` | **true** | Phase 5 requires Gate 1 + Gate 2 |

Configuration location: `secrets/runtime.env` (loaded by `backend-aws` via `docker-compose.yml`).

## Enable (read-only launch)

```bash
# Append to secrets/runtime.env (sudo on EC2)
JARVIS_4B_PROPOSALS_ENABLED=true
JARVIS_4B_MIN_CONFIDENCE=50
JARVIS_PATCH_APPLY_ENABLED=false
JARVIS_PR_CREATION_ENABLED=false
JARVIS_GITHUB_WRITE_ENABLED=false
JARVIS_REQUIRE_DOUBLE_APPROVAL=true

cd /home/ubuntu/crypto-2.0
docker compose --profile aws restart backend-aws
```

Verify:

```bash
curl -s http://127.0.0.1:8002/api/jarvis/safety-status | python3 -m json.tool
```

Expected: `phase4b_proposals_enabled: true`; all Phase 5 flags `false`.

## Phase 4B workflow (read-only)

```
Investigation (completed)
  → Eligibility (GET /api/jarvis/proposals/eligibility/{id})
  → Template matching (8 templates)
  → Proposal generation (POST .../propose-patch)
  → Sandbox validation (/tmp/jarvis-proposal-sandbox/{task_id})
  → Artifact persistence (investigation_context.json, patch.diff, tests.json, review.md)
  → Approval queue (only if patch required; no_fix_required auto-completes)
```

Phase 4B modules (`proposal_service`, `patch_generator`, `sandbox_validation`) have **no imports** of Phase 5 (`change_execution`, `pr_service`). Enforced by `test_no_phase5_imports_in_proposal_modules`.

## Verification checklist

### APIs

- `GET /api/jarvis/templates` — 8 templates
- `GET /api/jarvis/proposals/eligibility/{id}` — `eligible`, template match
- `POST /api/jarvis/investigations/{id}/propose-patch` — creates proposal task + artifacts
- `GET /api/jarvis/safety-status` — gate matrix

### Canonical production investigation

ID: `6014c7ef-836a-46f1-8988-7758797b02ac`

Expected eligibility:
- `eligible: true`
- `primary_template: orders.trigger_50001_cache_independent`
- `no_fix_required_reason` present (fix already in repo)

Expected proposal outcome:
- `proposal_status: no_fix_required`
- `status: completed`
- `approval_required: false`
- All four artifacts present

### Approval behavior

| Action | Endpoint | With Phase 5 disabled |
|--------|----------|----------------------|
| Record approval only | `POST .../approve` | Completes task; patch NOT applied |
| Sandbox apply | `POST .../approve-apply` | **403** |
| PR creation | `POST .../approve-pr` | **403** or blocked by gate checks |

`no_fix_required` proposals do **not** enter the approval queue (by design).

### System integrity

After proposal generation, confirm unchanged:
- Open orders count (Crypto.com API)
- No new GitHub PRs from Jarvis
- No deploy workflow dispatches
- No repo working-tree mutations from Jarvis

## Rollback

```bash
# In secrets/runtime.env
JARVIS_4B_PROPOSALS_ENABLED=false

docker compose --profile aws restart backend-aws
```

## Phase 5 enablement (separate, higher-risk)

Do **not** enable Phase 5 as part of read-only launch. When ready (separate change control):

1. `JARVIS_PATCH_APPLY_ENABLED=true` — Gate 1 sandbox apply
2. `JARVIS_PR_CREATION_ENABLED=true` + `JARVIS_GITHUB_WRITE_ENABLED=true` — Gate 2 PR creation

Merge, deploy, and `push_to_main` remain **forbidden** in `execution/safety.py` regardless of flags.
