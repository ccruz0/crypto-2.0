# GitHub App Migration — Executive Status Report

**Date:** 2026-06-09  
**Repository:** `ccruz0/crypto-2.0`  
**Open PR:** [#32 Complete GitHub App runtime authentication](https://github.com/ccruz0/crypto-2.0/pull/32) (`fix/github-app-runtime-completion`)

---

## 1. Current production state

| Item | Status |
|------|--------|
| EC2 instance | `i-087953603011543c5` (atp-rebuild-2026) |
| GitHub auth in SSM | PAT at `/automated-trading-platform/prod/github_token` **only** |
| GitHub App SSM parameters | **Do not exist** |
| GitHub App in GitHub org/repo | **Not created** |
| `ATP_TRADING_ONLY` | **`1`** — deploy/agent/GitHub startup checks **disabled** |
| `ALLOW_LEGACY_GITHUB_PAT` | **Absent** in prod (pre-PR #32 deploy) |
| Deploy on push | `deploy_session_manager.yml` — **still injects PAT** via SSM before render |
| PR #32 code on EC2 | **Not deployed** (open PR, not merged) |
| Trading | **Unaffected** — no trading logic changes in scope |

**Implication:** Production continues on legacy PAT infrastructure. Backend GitHub API paths on deployed code (pre-PR #32) may still read `GITHUB_TOKEN` directly; after merge+deploy, centralized auth applies with transition escape hatch.

---

## 2. Current repository state

| Area | Status |
|------|--------|
| Runtime auth module | `backend/app/services/github_app_auth.py` — complete in PR #32 |
| API consumers migrated | `deploy_trigger.py`, `cursor_execution_bridge.py`, `routes_monitoring.py` |
| Secret render | `scripts/aws/render_runtime_env.sh` — App SSM paths + `GITHUB_AUTH_MODE` + auto `ALLOW_LEGACY_GITHUB_PAT` |
| Verification | `scripts/verify_deploy_secrets.sh` — App vs legacy readiness |
| Tests | 9 passing per PR #32 (`test_github_app_auth`, `test_deploy_trigger_auth`) |
| Deploy workflow | **Unchanged** — PAT inject remains |
| Operator PAT scripts | Still present (`set_github_token_*`, `deploy_github_token_ssm.sh`) |
| Documentation | `backend/docs/GITHUB_APP_AUTH.md` + audit docs (this set) |

---

## 3. What PR #32 solved

- **Centralized GitHub API authentication** via `get_github_api_token()` with installation token minting and cache.
- **Removed direct `GITHUB_TOKEN` reads** from deploy trigger, Cursor bridge, and monitoring workflow dispatch.
- **Transition-safe render logic:** auto `ALLOW_LEGACY_GITHUB_PAT=true` when PAT present without App keys.
- **Startup validation** (`factory.py`) distinguishes App vs legacy (when not trading-only).
- **Operator verification script** reports `auth_mode: github_app | legacy_transition | none`.
- **Tests** for App preference, legacy fallback, and deploy trigger auth wiring.

---

## 4. What remains unsolved

| Item | Owner |
|------|-------|
| Create GitHub App + install on repository | Operator / GitHub admin |
| Populate SSM `github_app/*` parameters | Operator / AWS |
| Merge PR #32 | Code review |
| Deploy merged code to EC2 | CI or manual |
| Remove redundant PAT inject from `deploy_session_manager.yml` | Future PR |
| Deprecate operator PAT scripts | Future cleanup |
| Delete SSM `github_token` + revoke PAT | Post-verification operator step |
| Enable full automation (`ATP_TRADING_ONLY=0`) | Product/ops decision |
| Add `verify_deploy_secrets.sh` to deploy workflow | Future PR |
| Update stale docs referencing direct `GITHUB_TOKEN` | Documentation pass |

---

## 5. Production blockers

| Blocker | Blocks what |
|---------|-------------|
| GitHub App not created | Cannot populate App SSM; cannot reach `auth_mode: github_app` |
| SSM App parameters absent | Installation token minting fails |
| PR #32 not merged/deployed | EC2 still on pre-migration code paths |
| `ALLOW_LEGACY_GITHUB_PAT` absent (today) | After PR #32 deploy, **render fixes this** if PAT in SSM; until render runs, legacy API calls fail |
| `ATP_TRADING_ONLY=1` | Masks startup misconfiguration; deploy automation untested at startup level |

**Not a blocker for trading:** All above affect deploy/automation/GitHub API only.

---

## 6. Recommended next actions

1. **Review and merge PR #32** — code migration complete; low risk with `ATP_TRADING_ONLY=1`.
2. **Create GitHub App** with Actions/Contents/PR permissions; install on `ccruz0/crypto-2.0`.
3. **Write SSM parameters** (`app_id`, `installation_id`, `private_key_b64`) per `backend/docs/GITHUB_APP_AUTH.md`.
4. **Deploy to EC2** (push to main or manual workflow_dispatch).
5. **On EC2:** run `bash scripts/aws/render_runtime_env.sh` and `./scripts/verify_deploy_secrets.sh`.
6. **Smoke test** (with automation enabled or manual API): deploy dispatch, Cursor bridge PR, dashboard integrity workflow — confirm logs show `auth_method=github_app`.
7. **Set `ATP_TRADING_ONLY=0`** only after smoke tests pass.
8. **Remove PAT** from SSM and workflow inject; revoke personal PAT in GitHub.

---

## 7. Merge recommendation

| Decision | **Merge PR #32** |
|----------|------------------|
| Rationale | Runtime migration complete; tests pass; transition logic preserves prod PAT path via render script; `ATP_TRADING_ONLY=1` prevents startup regression |
| Conditions | Standard code review; no workflow changes required for merge |
| Risk if merged but not deployed | None to production |
| Risk if deployed before App SSM | Low with `ATP_TRADING_ONLY=1`; render sets legacy transition mode |

---

## 8. Deployment recommendation

| Phase | Action | Go? |
|-------|--------|-----|
| A | Merge PR #32, deploy to EC2 | **Go** — enables transition render logic |
| B | Create App + SSM before disabling legacy | **Go** — required for target state |
| C | Set `ATP_TRADING_ONLY=0` | **Wait** — until verify + smoke tests |
| D | Remove PAT from SSM/workflow | **No-Go** — until `auth_mode: github_app` confirmed |

Deploy **does not** need to happen before merge review. Deploy **should** happen after merge to pick up render + auth code. **Do not** delete PAT until Phase D.

---

## 9. Estimated time to complete migration

| Milestone | Duration |
|-----------|----------|
| PR #32 merge + review | 0.5 day |
| GitHub App creation + SSM | 0.5 day |
| Deploy + verify on EC2 | 0.5 day |
| Smoke tests + enable automation | 0.5 day |
| PAT removal + workflow cleanup | 0.5 day |
| **Total** | **~2–3 business days** (calendar); **~1 focused day** engineering/operator time |

---

## 10. Go / No-Go assessment

| Gate | Assessment |
|------|------------|
| **Merge PR #32** | **GO** |
| **Deploy PR #32 to production** | **GO** (trading-only mode contains risk) |
| **Create GitHub App + SSM now** | **GO** (no prod behaviour change until render) |
| **Remove legacy PAT now** | **NO-GO** |
| **Enable `ATP_TRADING_ONLY=0` now** | **NO-GO** (App SSM + verification required) |
| **Full migration complete** | **NO-GO** — operator steps outstanding |

### Overall migration status

```
[████████████████░░░░]  ~80% repository code complete
[████░░░░░░░░░░░░░░░░]  ~20% production infrastructure complete
```

**Summary:** The repository is **ready for safe cutover preparation**. Production remains on **legacy PAT** until GitHub App exists in SSM, PR #32 is deployed, and verification passes. No code changes beyond merge/deploy are required before operator infrastructure work.

---

## Related audit documents

| Document | Purpose |
|----------|---------|
| [github_app_remaining_dependencies.md](./github_app_remaining_dependencies.md) | Full PAT dependency inventory |
| [github_app_cutover_plan.md](./github_app_cutover_plan.md) | Cutover sequence, risks, rollback |
| [github_app_runtime_dependency_graph.md](./github_app_runtime_dependency_graph.md) | App env var flow and Mermaid diagrams |
| [deploy_session_manager_review.md](./deploy_session_manager_review.md) | Deploy workflow vs PR #32 analysis |
