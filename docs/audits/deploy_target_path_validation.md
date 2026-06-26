# Deploy Target Path Validation

**Date:** 2026-06-09  
**Question:** Does `deploy_session_manager.yml` deploy `/home/ubuntu/crypto-2.0` or `/home/ubuntu/automated-trading-platform`?  
**Method:** Repository file analysis only

---

## 1. Verdict

**The workflow deploys `/home/ubuntu/automated-trading-platform` (legacy path), not the documented canonical `/home/ubuntu/crypto-2.0`.**

It never references `crypto-2.0` in any SSM command.

---

## 2. Workflow references (exact)

Source: `.github/workflows/deploy_session_manager.yml`

| Line | Command fragment | Path targeted |
|------|------------------|---------------|
| 68 | `cd /home/ubuntu/automated-trading-platform \|\| cd ~/automated-trading-platform \|\| true` | Legacy (PAT inject — non-fatal if missing) |
| 88 | `cd ~/automated-trading-platform \|\| cd /home/ubuntu/automated-trading-platform \|\| { echo "❌ Cannot find project directory" && exit 1; }` | Legacy (**fatal**) |
| 146 | Same as 88 | Legacy (**fatal**) |

**Not present in workflow:** `/home/ubuntu/crypto-2.0`, `~/crypto-2.0`, or any fallback to canonical path.

### Instance comment (line 55)

```yaml
INSTANCE_ID: i-087953603011543c5  # atp-rebuild-2026 (PROD). Do not use crypto 2.0.
```

This comment refers to the **EC2 instance identity**, not the filesystem path — but creates naming confusion with the `crypto-2.0` repository.

---

## 3. Documented production path (contradictory sources)

| Document | Declared canonical PROD path |
|----------|------------------------------|
| `docs/operations/BACKEND_AWS_CANONICAL_REPO.md` | **`/home/ubuntu/crypto-2.0`** — *"Use for all new deploys"* |
| `docs/runbooks/deploy.md` § Manual deploy | **`/home/ubuntu/crypto-2.0`** |
| `docs/runbooks/secrets_runtime_env.md` § EC2 deploy order | **`/home/ubuntu/crypto-2.0`** (legacy fallback: `automated-trading-platform`) |
| `docs/status/PROD_STATUS_UPDATE.md` | **`/home/ubuntu/crypto-2.0`** |
| `.github/workflows/deploy_session_manager.yml` | **`/home/ubuntu/automated-trading-platform`** only |
| `deploy_all.sh` | **`/home/ubuntu/automated-trading-platform`** only |
| `scripts/aws/push_runtime_env_to_ec2.sh` | **`/home/ubuntu/automated-trading-platform`** |
| `backend/app/services/atp_ssm_runner.py` | **`/home/ubuntu/automated-trading-platform`** (hardcoded) |
| `secrets/runtime.env.example` | `ATP_PROJECT_PATH=/home/ubuntu/automated-trading-platform` |
| `scripts/verify_deploy_secrets.sh` comment | `~/automated-trading-platform` |

**Repository contains conflicting guidance.** Operators following runbooks use `crypto-2.0`; CI deploy uses `automated-trading-platform`.

---

## 4. Related workflow: `deploy.yml` (legacy SSH)

Source: `.github/workflows/deploy.yml`

All SSH/rsync targets use `~/automated-trading-platform` — same legacy path. Marked as manual/legacy in `deploy_session_manager_review.md`.

---

## 5. Risk assessment

| Risk | Likelihood | Impact | Description |
|------|------------|--------|-------------|
| **Deploy to wrong/stale directory** | **High** if EC2 migrated to `crypto-2.0` only | **Critical** | Workflow pulls `main` into `automated-trading-platform`; running stack may be `crypto-2.0` — **code divergence** |
| **Deploy hard-fail** | **High** if legacy dir removed | **High** | `Cannot find project directory` → no rebuild; prod stays on old containers |
| **Partial legacy directory** | **Medium** | **High** | Legacy dir without `docker-compose.yml` cannot run compose steps — deploy fails mid-workflow |
| **render_runtime_env.sh on wrong tree** | **Medium** | **Medium** | Secrets rendered to wrong `secrets/runtime.env`; active containers unaffected |
| **git pull wrong repo** | **High** if only `crypto-2.0` is a git clone | **Critical** | Automation deploys outdated or empty tree |
| **Trading outage** | **Low** | **Critical** | Failed deploy leaves old containers running — trading may continue on stale code |
| **GitHub auth transition failure** | **Medium** | **Medium** | Render runs on inactive path; active `crypto-2.0` backend never gets `ALLOW_LEGACY` or App keys |

### Scenario matrix

| EC2 layout | Workflow outcome |
|------------|------------------|
| Only `crypto-2.0` (full repo) | **FAIL** at git pull step |
| Only `automated-trading-platform` (full repo) | **PASS** (legacy layout) |
| Both directories, compose on `crypto-2.0` only | **FAIL** or deploys **stale/wrong** code to legacy path |
| Symlink `automated-trading-platform` → `crypto-2.0` | **PASS** (if symlink exists on EC2 — not documented in repo) |

---

## 6. Mismatch inventory

| # | Component | Path used | Expected (canonical doc) |
|---|-----------|-----------|--------------------------|
| 1 | `deploy_session_manager.yml` PAT inject | `automated-trading-platform` | `crypto-2.0` |
| 2 | `deploy_session_manager.yml` git pull | `automated-trading-platform` | `crypto-2.0` |
| 3 | `deploy_session_manager.yml` docker compose | `automated-trading-platform` | `crypto-2.0` |
| 4 | `deploy_all.sh` | `automated-trading-platform` | `crypto-2.0` |
| 5 | `push_runtime_env_to_ec2.sh` | `automated-trading-platform` | `crypto-2.0` |
| 6 | `atp_ssm_runner.py` | `automated-trading-platform` | `crypto-2.0` |
| 7 | `verify_deploy_secrets.sh` comment | `automated-trading-platform` | `crypto-2.0` |
| 8 | `BACKEND_AWS_CANONICAL_REPO.md` | `crypto-2.0` | — (canonical) |
| 9 | `deploy.md` manual procedure | `crypto-2.0` | — (canonical) |

---

## 7. Recommended fix (future — not applied in this audit)

**Do not modify workflow in this task.** Recommended operator/engineering fix:

### Option A — Workflow path update (preferred)

Update all SSM `cd` commands in `deploy_session_manager.yml` and `deploy_all.sh` to:

```bash
cd /home/ubuntu/crypto-2.0 || cd ~/crypto-2.0 || cd /home/ubuntu/automated-trading-platform || cd ~/automated-trading-platform
```

Canonical first, legacy fallback.

### Option B — EC2 symlink (interim operator workaround)

On EC2 only (if `crypto-2.0` is canonical):

```bash
# Only if automated-trading-platform is not already a full separate clone
ln -sfn /home/ubuntu/crypto-2.0 /home/ubuntu/automated-trading-platform
```

**Risk:** Hides the problem; two paths alias same repo — acceptable short-term.

### Option C — Align documentation to legacy path

Revert canonical doc to `automated-trading-platform` — **not recommended** given multiple docs already declare `crypto-2.0`.

### Additional alignment

| File | Change |
|------|--------|
| `atp_ssm_runner.py` | Read `ATP_PROJECT_PATH` env with fallback chain |
| `push_runtime_env_to_ec2.sh` | Use canonical path |
| `verify_deploy_secrets.sh` comment | Update example `cd` |
| `secrets/runtime.env.example` | `ATP_PROJECT_PATH=/home/ubuntu/crypto-2.0` |

---

## 8. Pre-deploy verification command (operator, EC2)

Run on PROD to determine active layout before PR #32 deploy:

```bash
for d in /home/ubuntu/crypto-2.0 /home/ubuntu/automated-trading-platform; do
  echo "=== $d ==="
  if [ -d "$d" ]; then
    ls -la "$d/docker-compose.yml" 2>/dev/null || echo "NO docker-compose.yml"
    git -C "$d" rev-parse --short HEAD 2>/dev/null || echo "NOT a git repo"
    docker compose -f "$d/docker-compose.yml" --profile aws ps 2>/dev/null | head -5 || echo "compose failed"
  else
    echo "MISSING"
  fi
done
```

**Decision rule:**

- If only `crypto-2.0` has `docker-compose.yml` and running containers → **workflow path mismatch is a deploy blocker**.
- If only `automated-trading-platform` is active → workflow aligned but **contradicts canonical docs**.

---

## 9. Impact on PR #32 transition

| Concern | Path mismatch effect |
|---------|---------------------|
| `render_runtime_env.sh` auto-set `ALLOW_LEGACY` | Runs on **workflow target path**, not necessarily active backend |
| `verify_deploy_secrets.sh` | Must run from **same path as running compose** |
| GitHub App SSM → runtime | Render must execute where `secrets/runtime.env` is mounted into containers |
| Trading safety | Unaffected if deploy fails (old containers keep running) |

**PR #32 merge is not blocked by path mismatch, but PR #32 deploy may not update the live stack if paths diverge.**

---

## Related files

- `.github/workflows/deploy_session_manager.yml`
- `deploy_all.sh`
- `docs/operations/BACKEND_AWS_CANONICAL_REPO.md`
- `docs/runbooks/deploy.md`
- `backend/app/services/atp_ssm_runner.py`
