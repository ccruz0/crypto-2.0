# PR #32 Go-Live Decision Report

**Date:** 2026-06-09  
**PR:** [#32 Complete GitHub App runtime authentication](https://github.com/ccruz0/crypto-2.0/pull/32)  
**Evidence source:** Repository files only (code, workflows, docs, tests)  
**Constraints honored:** No deploy, push, merge, schema, compose, or trading-logic changes in this audit.

---

## 1. Current production state

| Item | State (from repo docs + user context) |
|------|---------------------------------------|
| EC2 instance | `i-087953603011543c5` (atp-rebuild-2026) |
| Canonical repo path (documented) | `/home/ubuntu/crypto-2.0` per `BACKEND_AWS_CANONICAL_REPO.md` |
| Deploy workflow target path | `/home/ubuntu/automated-trading-platform` only |
| SSM GitHub PAT | `/automated-trading-platform/prod/github_token` — **present** |
| SSM GitHub App | `/automated-trading-platform/prod/github_app/*` — **absent** |
| GitHub App entity | **Not created** |
| `ATP_TRADING_ONLY` | **`1`** (`docker-compose.yml` default `:-1`) |
| `ALLOW_LEGACY_GITHUB_PAT` | **Absent** in prod runtime (pre-PR #32 deploy) |
| PR #32 on EC2 | **Not deployed** (open PR) |
| Pre-PR #32 auth | `deploy_trigger.py` reads `GITHUB_TOKEN` directly |
| Trading | **Independent** of GitHub auth changes |

---

## 2. Current repository state

| Area | Status |
|------|--------|
| Branch | `fix/github-app-runtime-completion` (PR #32) |
| Central auth | `backend/app/services/github_app_auth.py` — installation token minting + legacy fallback |
| Migrated consumers | `deploy_trigger.py`, `cursor_execution_bridge.py`, `routes_monitoring.py` |
| Render script | `render_runtime_env.sh` — SSM App paths, auto `ALLOW_LEGACY_GITHUB_PAT`, `GITHUB_AUTH_MODE` |
| Verification | `verify_deploy_secrets.sh` — App vs legacy readiness |
| Tests | 9 passing per PR description (`test_github_app_auth`, `test_deploy_trigger_auth`) |
| Startup gates | `factory.py` — strict when `ATP_TRADING_ONLY=0`; skipped when `=1` |
| Deploy workflow | **Unchanged** — still injects PAT; no `verify_deploy_secrets.sh` step |
| Documentation | Mixed — `GITHUB_APP_AUTH.md` accurate; `secrets_runtime_env.md` stale |

---

## 3. GitHub App readiness

| Requirement | Ready? |
|-------------|--------|
| Runtime code for App tokens | **Yes** — PR #32 complete |
| GitHub App created in GitHub | **No** |
| App installed on `ccruz0/crypto-2.0` | **No** |
| App permissions documented | **Yes** — runbook + cutover plan |
| Operator runbook | **Yes** — `docs/runbooks/GITHUB_APP_CREATION_AND_CUTOVER.md` |

**Assessment:** Code ready; **infrastructure not started**.

---

## 4. SSM readiness

| Parameter | Prod state | Render support |
|-----------|------------|----------------|
| `/prod/github_token` | Present | Yes — writes `GITHUB_TOKEN` |
| `/prod/github_app/app_id` | Absent | Yes — writes when present |
| `/prod/github_app/installation_id` | Absent | Yes |
| `/prod/github_app/private_key_b64` | Absent | Yes |
| `/lab/github_app/*` | Unknown | Fallback in render |

**Assessment:** Legacy PAT path **ready**; App path **not populated**.

---

## 5. Deploy workflow readiness

| Check | Result |
|-------|--------|
| Coexists with PR #32 code | **Yes** — invokes `render_runtime_env.sh` |
| PAT inject redundant post-PR #32 | **Yes** — render is authoritative for auth flags |
| Calls `verify_deploy_secrets.sh` | **No** |
| Targets canonical `crypto-2.0` path | **No** — legacy path only |
| Fails if EC2 uses `crypto-2.0` exclusively | **Likely yes** |
| Blocks on missing App SSM | **No** — continues with PAT transition |

**Assessment:** Workflow **compatible** with PR #32 auth logic but has **path mismatch risk** and **no automated auth verification**.

---

## 6. Runtime readiness

### With `ATP_TRADING_ONLY=1` (production today)

| Capability | Ready after PR #32 deploy + render? |
|------------|-------------------------------------|
| Backend startup | **Yes** — GitHub checks skipped |
| Trading | **Yes** — unchanged |
| Telegram poller | **Yes** — independent of GitHub auth at startup |
| Deploy trigger (if invoked) | **Yes** after render sets `ALLOW_LEGACY` + PAT |
| Cursor bridge PR create | **Same** as deploy trigger |
| Governance HTTP API | **No** — disabled by trading-only flag |
| Agent scheduler | **No** — intentionally disabled |

### With `ATP_TRADING_ONLY=0` (future)

| Capability | Ready without App SSM? |
|------------|------------------------|
| Backend startup | **Only with** `ALLOW_LEGACY_GITHUB_PAT` + PAT |
| Backend startup with App SSM | **Yes** |
| Full automation | **Requires** App SSM or legacy escape hatch |

---

## 7. Remaining blockers

| # | Blocker | Blocks |
|---|---------|--------|
| 1 | GitHub App not created | Target-state `auth_mode: github_app` |
| 2 | SSM `github_app/*` absent | Installation token minting |
| 3 | EC2 path mismatch (workflow vs canonical doc) | Reliable PR #32 deploy to live stack |
| 4 | `secrets_runtime_env.md` stale | Operator confusion about render capabilities |
| 5 | No post-deploy `verify_deploy_secrets.sh` in workflow | Silent auth misconfiguration |
| 6 | `ATP_TRADING_ONLY=0` not validated | Full automation enablement |
| 7 | PAT still in workflow inject + SSM | Security / dual-path complexity (not functional blocker) |

**Not blockers for merge or trading-safe deploy:**

- PR #32 code completeness
- Test passage
- Render auto-set of `ALLOW_LEGACY_GITHUB_PAT`

---

## 8. Exact next actions

| Order | Action | Owner | Est. time |
|-------|--------|-------|-----------|
| 1 | **Verify EC2 active path** (canonical vs legacy) using commands in `deploy_target_path_validation.md` | Operator | 15 min |
| 2 | **Review and merge PR #32** | Engineering | 30 min |
| 3 | **Deploy merged code** — workflow or manual on **correct EC2 path** | Operator | 30–60 min |
| 4 | **Run `render_runtime_env.sh`** on active path; confirm `GITHUB_AUTH_MODE=legacy_transition` | Operator | 5 min |
| 5 | **`./scripts/verify_deploy_secrets.sh`** — expect `legacy_transition` | Operator | 5 min |
| 6 | **Create GitHub App** per `GITHUB_APP_CREATION_AND_CUTOVER.md` | Operator | 1–2 hr |
| 7 | **Write SSM `github_app/*`** parameters | Operator | 15 min |
| 8 | **Re-render + recreate backend**; verify `auth_mode: github_app` | Operator | 15 min |
| 9 | **Smoke test** deploy dispatch (maintenance window) | Operator | 30 min |
| 10 | **Set `ATP_TRADING_ONLY=0`** only after steps 8–9 pass | Product/Ops | 15 min |
| 11 | **Remove PAT** from SSM + workflow inject (future PR) | Engineering | 2 hr |
| 12 | **Fix workflow path** to prefer `crypto-2.0` (future PR) | Engineering | 1 hr |

---

## 9. Go / No-Go for merge

| Decision | **GO** |
|----------|--------|
| Rationale | Runtime migration complete; 9 tests pass; `ATP_TRADING_ONLY=1` prevents startup regression; render script provides transition-safe `ALLOW_LEGACY_GITHUB_PAT` auto-set; no trading-logic changes |
| Conditions | Standard code review; acknowledge path mismatch and doc gaps as follow-up |
| Risk if merged but not deployed | **None** to production |
| Risk if merged | **Low** |

---

## 10. Go / No-Go for deployment

| Decision | **CONDITIONAL GO** |
|----------|-------------------|
| Safe for trading? | **Yes** — `ATP_TRADING_ONLY=1` contains auth startup risk |
| Safe for automation? | **Only after** `render_runtime_env.sh` on **active EC2 path** |
| Blockers before deploy | Confirm EC2 path alignment (blocker if workflow path ≠ active stack) |
| Deploy without GitHub App SSM? | **Yes** — legacy transition mode via PAT + auto `ALLOW_LEGACY` |
| Deploy without running render? | **No-Go** for any GitHub API use — `auth_method=none` |

### Deployment decision matrix

| Scenario | Go? |
|----------|-----|
| Merge only (no deploy) | **GO** |
| Deploy with `ATP_TRADING_ONLY=1` + PAT in SSM + render on active path | **GO** |
| Deploy without confirming EC2 path | **NO-GO** |
| Deploy then immediately set `ATP_TRADING_ONLY=0` without App SSM | **NO-GO** |
| Remove PAT before App verified | **NO-GO** |

---

## Summary scorecard

| Dimension | Score | Notes |
|-----------|-------|-------|
| Code readiness | 95% | PR #32 complete |
| SSM readiness | 20% | PAT only |
| Workflow readiness | 60% | Works but wrong path + no verify step |
| Documentation readiness | 70% | GITHUB_APP_AUTH good; secrets runbook stale |
| Production cutover readiness | 25% | App not created; path unverified |

**Overall:** Repository is **ready for safe transition preparation**. Production cutover to GitHub App is **not ready** until operator steps 6–9 complete. Trading remains safe throughout if `ATP_TRADING_ONLY=1` is maintained.

---

## Audit artifacts produced (this package)

| Document | Purpose |
|----------|---------|
| [pr32_deployment_readiness.md](./pr32_deployment_readiness.md) | Runtime/deploy/startup behaviour analysis |
| [github_auth_transition_gap.md](./github_auth_transition_gap.md) | Docs/code/production mismatches |
| [GITHUB_APP_CREATION_AND_CUTOVER.md](../runbooks/GITHUB_APP_CREATION_AND_CUTOVER.md) | Operator runbook |
| [deploy_target_path_validation.md](./deploy_target_path_validation.md) | Workflow path audit |
| [pr32_go_live_decision.md](./pr32_go_live_decision.md) | This decision report |
