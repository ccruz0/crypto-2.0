# GitHub Auth Transition Gap Analysis

**Date:** 2026-06-09  
**Scope:** `scripts/aws/render_runtime_env.sh`, documentation, and stated production state  
**Method:** Compare docs vs code vs production context (repository evidence only)

---

## 1. Is `ALLOW_LEGACY_GITHUB_PAT` automatically set?

### Code answer: **YES** (on current PR #32 branch)

Source: `scripts/aws/render_runtime_env.sh` lines 254–279

```bash
# Logic summary (after all env merges):
if all three GITHUB_APP_* present in runtime.env:
    GITHUB_AUTH_MODE=github_app
    remove ALLOW_LEGACY_GITHUB_PAT if present
elif GITHUB_TOKEN present in runtime.env:
    GITHUB_AUTH_MODE=legacy_transition
    set or append ALLOW_LEGACY_GITHUB_PAT=true
else:
    GITHUB_AUTH_MODE=none
    remove ALLOW_LEGACY_GITHUB_PAT if present
```

**Trigger conditions:**

| Input | `ALLOW_LEGACY_GITHUB_PAT` written? |
|-------|-----------------------------------|
| SSM PAT (`/prod/github_token`) fetched, App keys empty | **YES → `true`** |
| `.env.aws` fallback with `GITHUB_TOKEN`, App keys empty | **YES → `true`** |
| All three App keys from SSM or `.env.aws` | **NO** — flag removed |
| No PAT and no App | **NO** — flag removed |

**Important:** Auto-set runs **only when `render_runtime_env.sh` completes successfully**. It does not run when:

- Deploy workflow PAT inject writes `GITHUB_TOKEN` directly (step runs **before** render).
- `render_runtime_env.sh` fails and workflow continues with stale `runtime.env`.
- Operator manually appends `GITHUB_TOKEN` without re-running render.

### Main branch (pre-PR #32)

`render_runtime_env.sh` on `main` has **no** `ALLOW_LEGACY_GITHUB_PAT` logic — only writes `GITHUB_TOKEN` when present. Production today (pre-deploy) relies on direct `GITHUB_TOKEN` reads in `deploy_trigger.py`.

---

## 2. Documentation vs implementation mismatches

| # | Document | Says | Code says | Severity |
|---|----------|------|-----------|----------|
| 1 | `docs/runbooks/secrets_runtime_env.md` L31–39 | *"GitHub App — **not written by** `render_runtime_env.sh` today"* | Script **does** fetch SSM `github_app/*` and write `GITHUB_APP_*` (lines 85–90, 186–188) | **High** — operator may skip SSM App setup thinking render ignores it |
| 2 | `docs/runbooks/secrets_runtime_env.md` L39 | *"render currently writes legacy `GITHUB_TOKEN` only when present in SSM"* | Also writes App keys, sets `ALLOW_LEGACY_GITHUB_PAT`, prints `GITHUB_AUTH_MODE` | **Medium** |
| 3 | `docs/audits/deploy_session_manager_review.md` L110 | *"Workflow uses `automated-trading-platform` — **consistent with production layout**"* | `docs/operations/BACKEND_AWS_CANONICAL_REPO.md` declares **`/home/ubuntu/crypto-2.0`** canonical | **High** — contradictory path guidance |
| 4 | `backend/docs/GITHUB_APP_AUTH.md` L62–66 | Transition auto-set documented | Matches PR #32 `render_runtime_env.sh` | **Aligned** ✓ |
| 5 | `secrets/runtime.env.example` L94–101 | Documents auto-set when PAT without App | Matches PR #32 render logic | **Aligned** ✓ |
| 6 | `secrets/runtime.env.example` L112 | `ATP_PROJECT_PATH=/home/ubuntu/automated-trading-platform` | `BACKEND_AWS_CANONICAL_REPO.md` says use `crypto-2.0` | **Medium** |
| 7 | PR #32 body | *"Until deploy + SSM App credentials, production continues using existing runtime env (legacy PAT if configured)"* | Post-deploy without render, PAT alone is **insufficient** — needs `ALLOW_LEGACY_GITHUB_PAT` | **Medium** — accurate only after render runs |
| 8 | `scripts/verify_deploy_secrets.sh` L9 | SSM example uses `cd ~/automated-trading-platform` | Runbooks use `crypto-2.0` | **Low** |
| 9 | `backend/entrypoint.sh` L3–4 comment | *"authoritative for GITHUB_TOKEN"* | Still true; does not mention `ALLOW_LEGACY_GITHUB_PAT` | **Low** |

---

## 3. `runtime.env.example` accuracy

| Field / section | Accurate? | Notes |
|-----------------|-----------|-------|
| `GITHUB_APP_*` commented placeholders | **Yes** | Matches render output keys |
| `ALLOW_LEGACY_GITHUB_PAT` auto-set comment (L98–99) | **Yes** on PR #32 branch | **Not true on main** until PR merged |
| `GITHUB_TOKEN` legacy comment | **Yes** | SSM path documented correctly |
| `GITHUB_REPOSITORY=ccruz0/crypto-2.0` | **Yes** | Matches `deploy_trigger.py` default |
| `ATP_PROJECT_PATH` | **Stale** | Points to legacy path; canonical doc says `crypto-2.0` |
| `OPENCLAW_API_URL` LAB IP | **Informational** | Unrelated to GitHub auth |
| Missing: `GITHUB_AUTH_MODE` | **Gap** | Render prints it but example does not document the variable |

---

## 4. Operator instructions accuracy

| Instruction source | Accurate for PR #32? | Gap |
|--------------------|---------------------|-----|
| `backend/docs/GITHUB_APP_AUTH.md` § Operator flow | **Mostly yes** | Step 2 (`ATP_TRADING_ONLY=0`) correctly warns compose interpolation — good |
| `backend/docs/GITHUB_APP_AUTH.md` § Transition period | **Yes** | Matches render auto-set |
| `docs/runbooks/secrets_runtime_env.md` § EC2 deploy order | **Yes** for path (`crypto-2.0`) | GitHub App section contradicts render capabilities |
| `docs/runbooks/deploy.md` § Manual deploy | **Yes** | Uses `crypto-2.0` |
| `deploy_all.sh` / workflow | **Path mismatch** | Target `automated-trading-platform` not `crypto-2.0` |
| `scripts/set_github_token_for_deploy.sh` | **Incomplete** | Writes PAT only; does not set `ALLOW_LEGACY_GITHUB_PAT` (pre-PR #32 harmless; post-PR #32 needs render) |

---

## 5. Production vs code mismatches

Stated production state (from audit docs and user context):

| Production fact | Code expectation post-PR #32 | Mismatch |
|-----------------|-------------------------------|----------|
| SSM `github_app/*` absent | App path unavailable; legacy transition expected | **Expected** — not a bug |
| SSM `github_token` present | Render writes PAT + `ALLOW_LEGACY_GITHUB_PAT=true` | **Aligned after render** |
| `ALLOW_LEGACY_GITHUB_PAT` absent in prod today | Required for `get_github_api_token()` after PR #32 | **Gap until deploy+render** |
| `ATP_TRADING_ONLY=1` | Startup checks skipped | **Aligned** — masks auth misconfiguration |
| PR #32 not deployed | `deploy_trigger` still reads `GITHUB_TOKEN` directly | **Pre-deploy: works without flag** |
| GitHub App not created | Cannot reach `auth_mode: github_app` | **Expected blocker** |
| Deploy workflow injects PAT without flag | Render must run afterward to fix | **Ordering dependency** |

---

## 6. Complete mismatch inventory

### Docs ↔ Code

1. `secrets_runtime_env.md` denies render writes `GITHUB_APP_*` — **false** on PR #32 branch.
2. `deploy_session_manager_review.md` claims ATP path is production-canonical — **contradicts** `BACKEND_AWS_CANONICAL_REPO.md`.
3. `runtime.env.example` `ATP_PROJECT_PATH` — **legacy path** vs canonical doc.
4. `verify_deploy_secrets.sh` inline SSM example path — **legacy**.

### Code ↔ Production (stated)

5. Post-PR #32 runtime requires `ALLOW_LEGACY_GITHUB_PAT` for PAT — prod lacks flag **until render**.
6. `deploy_session_manager.yml` PAT inject creates **flagless** PAT window before render.
7. `atp_ssm_runner.py` hardcodes `/home/ubuntu/automated-trading-platform` — may not match canonical `crypto-2.0` on EC2.

### Deploy ↔ Runtime

8. Workflow never calls `verify_deploy_secrets.sh` — auth misconfiguration undetected in CI.
9. Render failure is non-fatal in workflow (`|| true`) — may leave flagless PAT env.

---

## 7. Remediation priority (documentation / operator only — no code changes in this task)

| Priority | Action |
|----------|--------|
| P0 | After PR #32 deploy, **always** run `render_runtime_env.sh` before trusting GitHub automation |
| P1 | Update `secrets_runtime_env.md` GitHub App section to reflect render behaviour (future doc PR) |
| P2 | Resolve path canonicalization: workflow vs `BACKEND_AWS_CANONICAL_REPO.md` (see deploy_target_path_validation.md) |
| P3 | Add `GITHUB_AUTH_MODE` to `runtime.env.example` comments |
| P4 | Align `ATP_PROJECT_PATH` default in example with canonical path |

---

## 8. Verification commands (copy-paste, EC2)

Run from the active repo root (adjust `cd` if needed):

```bash
cd /home/ubuntu/crypto-2.0 || cd /home/ubuntu/automated-trading-platform

# Render and inspect auth mode (no secret values printed)
bash scripts/aws/render_runtime_env.sh
grep -E '^(GITHUB_AUTH_MODE|ALLOW_LEGACY_GITHUB_PAT|GITHUB_APP_ID|GITHUB_TOKEN)=' secrets/runtime.env \
  | sed 's/=.*/=<present>/'

# Container verification
./scripts/verify_deploy_secrets.sh
```

**Expected after PR #32 deploy with PAT-only SSM:**

```
GITHUB_AUTH_MODE=<present>          # legacy_transition
ALLOW_LEGACY_GITHUB_PAT=<present>   # true
GITHUB_TOKEN=<present>
GITHUB_APP_ID=                      # absent
auth_mode: legacy_transition
Deploy automation ready? YES
```
