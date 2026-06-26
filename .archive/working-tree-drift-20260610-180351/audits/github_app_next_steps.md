# GitHub App Migration — Next Steps

**Date:** 2026-06-09  
**Prerequisite completed:** Path canonicalization commit `cb175c2` on `fix/path-canonicalization-prod`  
**Code changes for auth phase:** Uncommitted in working tree (4 files)

---

## Current state

| Item | Status |
|------|--------|
| PROD repo path | `/home/ubuntu/crypto-2.0` (verified; path commit aligns CI) |
| GitHub App installed on `ccruz0/crypto-2.0` | **No** |
| SSM `/automated-trading-platform/prod/github_app/*` | **Missing** |
| SSM `/automated-trading-platform/prod/github_token` (PAT) | **Present** |
| PR #32 backend auth gate | **Merged** (blocks PAT-only without `ALLOW_LEGACY_GITHUB_PAT`) |
| `render_runtime_env.sh` auto-ALLOW_LEGACY patch | **Uncommitted** (working tree) |
| Path commit | **Committed locally**, not pushed |

---

## Uncommitted auth changes (ready for next commit)

| File | Purpose |
|------|---------|
| `scripts/aws/render_runtime_env.sh` | Auto `ALLOW_LEGACY_GITHUB_PAT=true` when PAT-only |
| `backend/docs/GITHUB_APP_AUTH.md` | Operator transition docs |
| `scripts/verify_deploy_secrets.sh` | `auth_mode:` diagnostic output |
| `secrets/runtime.env.example` | GitHub App / PAT documentation |

**Suggested branch:** `fix/github-app-legacy-transition-render` from `cb175c2`  
**Suggested title:** `fix(auth): auto-set ALLOW_LEGACY_GITHUB_PAT during GitHub App transition`

---

## Required next actions (ordered)

### Phase A — Immediate (after path PR merge)

1. **Commit and PR auth transition patch** (4 files above)
   - Enables PAT fallback until App SSM exists
   - Depends on path commit so render runs in correct directory

2. **Merge auth transition PR** → deploy via CI

3. **Verify on EC2:**
   ```bash
   cd /home/ubuntu/crypto-2.0
   bash scripts/aws/render_runtime_env.sh
   grep ALLOW_LEGACY secrets/runtime.env
   ./scripts/verify_deploy_secrets.sh
   # Expect: auth_mode: legacy_transition
   ```

### Phase B — GitHub App provisioning

4. **Create GitHub App** (see `docs/runbooks/GITHUB_APP_CREATION_AND_CUTOVER.md`)
   - Permissions: contents, pull requests, workflows (as needed)
   - Generate private key

5. **Install App on `ccruz0/crypto-2.0`**
   - Record App ID and Installation ID

6. **Store SSM parameters** (operator; no code change):
   ```
   /automated-trading-platform/prod/github_app/app_id
   /automated-trading-platform/prod/github_app/installation_id
   /automated-trading-platform/prod/github_app/private_key_b64
   ```

### Phase C — Cutover

7. **Render runtime.env on EC2**
   ```bash
   bash scripts/aws/render_runtime_env.sh
   docker compose --profile aws up -d --build backend-aws
   ```

8. **Verify auth_method=github_app**
   ```bash
   ./scripts/verify_deploy_secrets.sh
   # Expect: auth_mode: github_app, ALLOW_LEGACY_GITHUB_PAT: no
   ```

9. **Test deploy dispatch / Cursor bridge** with App token

### Phase D — PAT removal (after verification)

10. **Revoke personal PAT** in GitHub settings
11. **Delete SSM** `/automated-trading-platform/prod/github_token` (operator)
12. **Re-render** and verify `auth_mode: github_app` still holds

---

## Dependencies

| Step | Depends on |
|------|------------|
| Auth transition commit | Path commit merged |
| App SSM store | App created + installed |
| Cutover verify | App SSM + deploy |
| PAT removal | Successful App verification (7+ days recommended) |

---

## Risk notes

- Deploy PAT-only **without** auth transition commit → GitHub API features fail after backend restart
- Deploy auth transition **before** path commit → render may run on wrong directory
- **Recommended order:** Path PR → Auth transition PR → App provisioning → Cutover → PAT removal

---

## Do NOT (operator constraints)

- Do not delete PAT until App verified in production
- Do not rename SSM parameter prefixes (AWS resource names)
- Do not modify trading logic, OpenClaw, or Jarvis as part of auth migration
