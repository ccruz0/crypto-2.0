# Path Canonicalization Commit Plan

**Date:** 2026-06-09  
**Status:** Prepared — **do not commit** (per operator instruction)  
**Intended PR scope:** Production deploy path canonicalization only

---

## Commit title

```
fix(deploy): canonicalize production repo path to crypto-2.0
```

---

## Files to include (path-only commit)

| # | File | Reason |
|---|------|--------|
| 1 | `.github/workflows/deploy_session_manager.yml` | Primary CI deploy — fixes fatal `cd` on PROD |
| 2 | `.github/workflows/deploy.yml` | Legacy SSH deploy — align rsync/ssh targets |
| 3 | `deploy_all.sh` | Manual deploy mirror of CI |
| 4 | `deploy_aws.sh` | SSH deploy default path |
| 5 | `deploy_github_token_ssm.sh` | PAT inject project dir |
| 6 | `restart_backend_ssm.sh` | SSM restart cwd |
| 7 | `scripts/aws/push_runtime_env_to_ec2.sh` | Secrets write path on EC2 |
| 8 | `scripts/aws/inject_aws_creds_to_prod.sh` | AWS cred inject cwd |
| 9 | `scripts/aws/deploy_all_manual_commands.sh` | Operator runbook heredoc |
| 10 | `scripts/deploy_production.sh` | Remote project dir default |
| 11 | `backend/app/services/atp_ssm_runner.py` | Agent SSM command cwd |
| 12 | `secrets/runtime.env.example` | **Line 112 only** — `ATP_PROJECT_PATH` example |

### Files to exclude (separate auth PR)

| File | Reason to exclude |
|------|-------------------|
| `scripts/aws/render_runtime_env.sh` | GitHub auth transition — not path canonicalization |
| `backend/docs/GITHUB_APP_AUTH.md` | Auth documentation |
| `scripts/verify_deploy_secrets.sh` | Auth diagnostics (`auth_mode` output) |
| `secrets/runtime.env.example` (lines 94–102) | GitHub App/PAT comments |

---

## Commit body (suggested)

```
Align Tier-1 deploy tooling with verified PROD layout (/home/ubuntu/crypto-2.0).

Production containers run from crypto-2.0; CI SSM workflow, deploy scripts,
runtime.env push, and ATP SSM runner previously targeted the legacy
automated-trading-platform path and could deploy or write secrets to the
wrong tree.

SSM parameter prefixes (/automated-trading-platform/prod/...) unchanged.
No trading, schema, Docker, or GitHub App runtime logic changes.
```

---

## Risk assessment

| Area | Level | Notes |
|------|-------|-------|
| CI deploy (main push) | **Low** | Matches verified PROD; fixes existing mismatch |
| Secrets push | **Low** | Corrects high-severity wrong-path write |
| ATP agent commands | **Low** | cwd alignment |
| Legacy SSH deploy | **Low** | Manual only |
| Regression if EC2 still had legacy-only clone | **Very low** | Verified: crypto-2.0 is canonical on PROD |

**Overall path commit risk: Low**

---

## Rollback plan

1. Revert the commit (or restore path strings to `automated-trading-platform`).
2. No database migration or image rebuild required for rollback.
3. If already deployed via CI: next push re-runs workflow with reverted paths (would break again on crypto-2.0-only PROD — rollback only valid if legacy dir restored on EC2).
4. On EC2 emergency symlink (if ever needed):  
   `ln -sfn /home/ubuntu/crypto-2.0 /home/ubuntu/automated-trading-platform`  
   (not recommended long-term; path patch is preferred.)

---

## Deployment impact

| Impact | Detail |
|--------|--------|
| **When it takes effect** | Next `push` to `main` after merge |
| **Downtime** | None expected — same docker compose flow, correct cwd |
| **Secrets** | No SSM path changes |
| **Running containers** | Rebuilt on deploy (existing behavior) |
| **Operator scripts** | Tier-2 scripts still legacy until follow-up |

---

## Staging steps before merge (operator)

1. Commit path-only file set on a dedicated branch (not mixed with auth patch).
2. Open PR; verify diff contains no auth/render changes.
3. Merge to `main` — triggers `deploy_session_manager.yml`.
4. Post-deploy: confirm SSM output shows `pwd` under crypto-2.0; `docker compose --profile aws ps` healthy.
5. Optional: run `./scripts/verify_deploy_secrets.sh` on EC2.

---

## Audit artifacts (this effort)

Include in PR description or attach:

- `docs/audits/path_patch_validation.md`
- `docs/audits/deployment_path_safety_review.md`
- `docs/audits/path_canonicalization_go_no_go.md`

Do **not** bundle `legacy_pat_flag_verification.md` into path PR unless auth patch is included.
