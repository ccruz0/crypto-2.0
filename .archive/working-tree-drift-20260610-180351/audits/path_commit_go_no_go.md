# Path Commit Go / No-Go

**Date:** 2026-06-09  
**Assumption:** Only the path-only commit set is merged; GitHub App transition commit is **not** included.

**Verified PROD fact:** Containers run from `/home/ubuntu/crypto-2.0`; legacy path does not exist as primary clone.

---

## Question 1: Will `deploy_session_manager.yml` work?

**YES.**

All three SSM command blocks now use:

```bash
cd ~/crypto-2.0 || cd /home/ubuntu/crypto-2.0 || { ... exit 1; }
```

(or non-fatal variant for PAT inject step)

This matches PROD layout. Previously the workflow failed at git pull / docker compose when only `crypto-2.0` existed.

---

## Question 2: Will push-to-main deploy work?

**YES** (path alignment).

| Step | Path-only commit |
|------|------------------|
| Checkout + frontend clone (runner) | Unchanged — works |
| SSM PAT inject | `cd crypto-2.0` — works |
| SSM git pull + frontend clone | `cd crypto-2.0` — works |
| SSM render + docker rebuild | `cd crypto-2.0` — works |
| Health wait / nginx restart | Unchanged — works |

**Caveat (auth, not path):** If PR #32 backend is live and `ALLOW_LEGACY_GITHUB_PAT` is not manually set, GitHub API features may fail **after** deploy restart. That is an auth gap, not a path failure. Deploy pipeline itself completes.

---

## Question 3: Will SSM runner work?

**YES.**

`backend/app/services/atp_ssm_runner.py` `_ATP_PROJECT_PATH` becomes `/home/ubuntu/crypto-2.0`. Agent `/api/agent/run-atp-command` sends SSM commands with:

```bash
cd /home/ubuntu/crypto-2.0 && ...
```

Matches PROD. Previously commands targeted non-existent or stale legacy directory.

`scripts/aws/inject_aws_creds_to_prod.sh` test curl also uses correct path.

---

## Question 4: Will docker compose target the correct directory?

**YES.**

| Entry point | cwd after path commit |
|-------------|----------------------|
| CI SSM rebuild step | `/home/ubuntu/crypto-2.0` |
| `deploy_all.sh` rebuild | `/home/ubuntu/crypto-2.0` |
| `deploy_aws.sh` SSH heredoc | `/home/ubuntu/crypto-2.0` |
| `push_runtime_env_to_ec2.sh` restart | `/home/ubuntu/crypto-2.0` |
| `restart_backend_ssm.sh` | `/home/ubuntu/crypto-2.0` |

Docker Compose project name comes from directory name / compose file — running from `crypto-2.0` matches verified PROD container labels.

---

## Question 5: Any remaining blockers?

### Blockers removed by path commit

| Blocker | Status |
|---------|--------|
| Fatal `cd` to missing legacy directory | **Removed** |
| Secrets written to wrong path | **Removed** |
| SSM runner wrong cwd | **Removed** |
| Code pull into wrong/stale tree | **Removed** |

### Remaining blockers (outside path commit scope)

| Blocker | Severity | Mitigation |
|---------|----------|------------|
| `ALLOW_LEGACY_GITHUB_PAT` not auto-set | **Medium** | GitHub App transition commit or manual env var |
| GitHub App SSM keys absent | **Medium** (future) | App provisioning PR |
| Tier-2 ops scripts still use legacy path | **Low** | Follow-up PR; not CI-blocking |
| Frontend version gate `0.46` | **Low** | Pre-existing |
| `deploy_aws.sh` heredoc ignores `REMOTE_DIR` override | **Very low** | Default is correct |

---

## Go / No-Go verdict

| Dimension | Verdict |
|-----------|---------|
| Path commit safe to merge? | **GO** |
| Path commit fixes primary deploy? | **GO** |
| Path commit alone fixes GitHub auth? | **NO-GO** — separate commit needed |
| Path commit alone safe for PROD deploy? | **GO** — deploy pipeline succeeds; auth features may need follow-up |

**Overall path-only commit: GO**
