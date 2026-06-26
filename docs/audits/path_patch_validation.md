# Path Patch Validation

**Date:** 2026-06-09  
**Branch:** `fix/github-app-legacy-transition-render`  
**Scope:** Review every file currently modified in the working tree against path-canonicalization intent (`automated-trading-platform` → `crypto-2.0`).

## Summary

| Category | Count |
|----------|-------|
| Path-only (safe for path PR) | 11 |
| Mixed (path + non-path) | 3 |
| Auth/docs only (not path PR) | 1 |
| **Total modified tracked files** | **15** |

**Verdict:** The working tree bundles **path canonicalization** with **GitHub auth transition** changes. A production-safe **path-only** PR should include the 11 path-only files and exclude the 4 auth-related deltas.

---

## File-by-file review

### 1. `.github/workflows/deploy.yml`

| Field | Value |
|-------|-------|
| **Modified lines** | 19–21 (comments), 166–168, 176, 194, 201, 214, 222 |
| **Change type** | Path only — `~/automated-trading-platform` → `~/crypto-2.0` |
| **Risk** | **Medium** — legacy SSH workflow; not triggered on push |
| **Trading logic** | None |
| **GitHub App / auth** | None |
| **OpenClaw / Jarvis** | None |
| **Verdict** | **Safe** (path PR) |

---

### 2. `.github/workflows/deploy_session_manager.yml`

| Field | Value |
|-------|-------|
| **Modified lines** | 68, 88, 146 |
| **Change type** | Path only — `cd` targets to `crypto-2.0` |
| **Risk** | **High impact / Low regression** — primary CI deploy on `push: main` |
| **Trading logic** | None |
| **GitHub App / auth** | None (SSM param paths unchanged: `/automated-trading-platform/prod/...`) |
| **OpenClaw / Jarvis** | None |
| **Verdict** | **Safe** (path PR) — aligns workflow with verified PROD layout |

---

### 3. `backend/app/services/atp_ssm_runner.py`

| Field | Value |
|-------|-------|
| **Modified lines** | 9 (docstring), 24 (`_ATP_PROJECT_PATH`) |
| **Change type** | Path constant only |
| **Risk** | **High impact** — agent SSM commands run in project cwd |
| **Trading logic** | None — only default cwd for allowed docker/git subcommands |
| **GitHub App / auth** | None |
| **OpenClaw / Jarvis** | None |
| **Verdict** | **Safe** (path PR) |

---

### 4. `backend/docs/GITHUB_APP_AUTH.md`

| Field | Value |
|-------|-------|
| **Modified lines** | 62–68 (new "Transition period" section) |
| **Change type** | **Auth documentation** — describes `ALLOW_LEGACY_GITHUB_PAT` auto-write |
| **Risk** | **Low** — docs only |
| **Trading logic** | None |
| **GitHub App / auth** | **Yes** — documents auth transition behavior |
| **Verdict** | **Not safe for path-only PR** — belongs in GitHub App / auth PR |

---

### 5. `deploy_all.sh`

| Field | Value |
|-------|-------|
| **Modified lines** | 51, 73, 100 |
| **Change type** | Path only — SSM `cd` commands |
| **Risk** | **Medium** — manual full deploy mirror of CI |
| **Verdict** | **Safe** (path PR) |

---

### 6. `deploy_aws.sh`

| Field | Value |
|-------|-------|
| **Modified lines** | 33 (`REMOTE_DIR` default), 161, 180 |
| **Change type** | Path only |
| **Risk** | **Medium** — SSH/rsync deploy; `workflow_dispatch` legacy path |
| **Verdict** | **Safe** (path PR) |

---

### 7. `deploy_github_token_ssm.sh`

| Field | Value |
|-------|-------|
| **Modified lines** | 9 (`PROJECT_DIR`) |
| **Change type** | Path only |
| **Risk** | **Medium** — PAT inject script targets project dir |
| **Verdict** | **Safe** (path PR) |

---

### 8. `restart_backend_ssm.sh`

| Field | Value |
|-------|-------|
| **Modified lines** | 26 |
| **Change type** | Path only |
| **Risk** | **Low** |
| **Verdict** | **Safe** (path PR) |

---

### 9. `scripts/aws/deploy_all_manual_commands.sh`

| Field | Value |
|-------|-------|
| **Modified lines** | 14 |
| **Change type** | Path only (heredoc operator instructions) |
| **Risk** | **Low** |
| **Verdict** | **Safe** (path PR) |

---

### 10. `scripts/aws/inject_aws_creds_to_prod.sh`

| Field | Value |
|-------|-------|
| **Modified lines** | 32, 60 |
| **Change type** | Path only |
| **Risk** | **Medium** |
| **Verdict** | **Safe** (path PR) |

---

### 11. `scripts/aws/push_runtime_env_to_ec2.sh`

| Field | Value |
|-------|-------|
| **Modified lines** | 58–59 |
| **Change type** | Path only — runtime.env write + docker restart cwd |
| **Risk** | **High** — wrong path writes secrets to non-running tree |
| **Verdict** | **Safe** (path PR) — critical fix |

---

### 12. `scripts/aws/render_runtime_env.sh`

| Field | Value |
|-------|-------|
| **Modified lines** | 254–282 (new block); replaces lines 254–257 |
| **Change type** | **GitHub auth transition** — auto `ALLOW_LEGACY_GITHUB_PAT=true` when PAT present and App incomplete |
| **Risk** | **Medium** — changes runtime.env auth flags on every deploy render |
| **Trading logic** | None |
| **GitHub App / auth** | **Yes** — modifies auth mode selection in render pipeline |
| **Database / Docker** | None |
| **Verdict** | **Not safe for path-only PR** — separate auth concern |

---

### 13. `scripts/deploy_production.sh`

| Field | Value |
|-------|-------|
| **Modified lines** | 24 (`REMOTE_PROJECT_DIR` default) |
| **Change type** | Path only |
| **Risk** | **Medium** |
| **Verdict** | **Safe** (path PR) |

---

### 14. `scripts/verify_deploy_secrets.sh`

| Field | Value |
|-------|-------|
| **Modified lines** | 9 (comment), 70–74 (`auth_mode` print) |
| **Change type** | **Mixed** — comment is path; Python block is auth diagnostics |
| **Risk** | **Low** |
| **GitHub App / auth** | **Yes** — adds `auth_mode` output |
| **Verdict** | **Partial** — path comment safe; auth block belongs with auth PR |

---

### 15. `secrets/runtime.env.example`

| Field | Value |
|-------|-------|
| **Modified lines** | 94–102 (GitHub auth comments), 112 (`ATP_PROJECT_PATH`) |
| **Change type** | **Mixed** — path example + GitHub App/PAT documentation |
| **Risk** | **Low** |
| **Verdict** | **Partial** — line 112 path change safe; lines 94–102 auth docs not path PR |

---

## Constraint checklist (all 15 files)

| Constraint | Violations |
|------------|------------|
| No trading logic changes | **None** |
| No OpenClaw changes | **None** |
| No Jarvis agent changes | **None** |
| No database schema changes | **None** |
| No Docker image / compose changes | **None** |
| No GitHub App **runtime** logic changes | **None in Python** — auth behavior change is in shell render script only |
| No unrelated changes | **4 files** carry auth/docs deltas beyond path |

---

## Recommended path-only file set (11 files)

1. `.github/workflows/deploy.yml`
2. `.github/workflows/deploy_session_manager.yml`
3. `backend/app/services/atp_ssm_runner.py`
4. `deploy_all.sh`
5. `deploy_aws.sh`
6. `deploy_github_token_ssm.sh`
7. `restart_backend_ssm.sh`
8. `scripts/aws/deploy_all_manual_commands.sh`
9. `scripts/aws/inject_aws_creds_to_prod.sh`
10. `scripts/aws/push_runtime_env_to_ec2.sh`
11. `scripts/deploy_production.sh`

Optional partial includes (path lines only):

- `secrets/runtime.env.example` — line 112 only
- `scripts/verify_deploy_secrets.sh` — line 9 comment only

**Exclude from path PR:**

- `scripts/aws/render_runtime_env.sh`
- `backend/docs/GITHUB_APP_AUTH.md`
- Auth portions of `verify_deploy_secrets.sh` and `runtime.env.example`
