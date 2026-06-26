# Path Commit Final Validation

**Date:** 2026-06-09  
**Commit:** `cb175c23f44a8a3c2389ba9f9af84cf46a119877`  
**Assumption:** Only path commit merged; GitHub App changes not yet committed.

---

## 1. Will `deploy_session_manager.yml` work?

**YES.**

All SSM `cd` commands target `~/crypto-2.0 || /home/ubuntu/crypto-2.0`. Matches verified PROD layout. Previously failed when legacy directory absent.

---

## 2. Will `deploy.yml` work?

**YES** (manual SSH deploy).

All rsync/ssh targets use `~/crypto-2.0`. Triggered only via `workflow_dispatch`. Not used on push to main.

---

## 3. Will `deploy_all.sh` work?

**YES.**

Mirrors CI workflow with `crypto-2.0` paths in all three SSM command blocks.

---

## 4. Will `deploy_aws.sh` work?

**YES.**

`REMOTE_DIR` default and SSH heredocs use `/home/ubuntu/crypto-2.0`. Minor note: heredocs hardcode path (ignore `REMOTE_DIR` override) — acceptable since default is correct.

---

## 5. Will `push_runtime_env_to_ec2.sh` work?

**YES.**

Writes `secrets/runtime.env` to `/home/ubuntu/crypto-2.0/secrets/runtime.env` and restarts compose from that directory.

---

## 6. Will `atp_ssm_runner.py` use the correct directory?

**YES.**

`_ATP_PROJECT_PATH = "/home/ubuntu/crypto-2.0"`. Agent SSM commands prepend correct `cd`.

---

## 7. Will docker compose run in the correct location?

**YES.**

| Entry point | cwd |
|-------------|-----|
| CI SSM rebuild | `/home/ubuntu/crypto-2.0` |
| `deploy_all.sh` | `/home/ubuntu/crypto-2.0` |
| `deploy_aws.sh` | `/home/ubuntu/crypto-2.0` |
| `push_runtime_env_to_ec2.sh` | `/home/ubuntu/crypto-2.0` |
| `restart_backend_ssm.sh` | `/home/ubuntu/crypto-2.0` |

---

## 8. Remaining blockers?

| Blocker | Severity | Notes |
|---------|----------|-------|
| GitHub App transition not committed | Medium | PAT-only may need manual `ALLOW_LEGACY_GITHUB_PAT` until auth commit |
| Tier-2 ops scripts still legacy path | Low | Not CI-blocking |
| `lab_ssm_runner.py`, `routes_admin.py` legacy cwd | Low–Medium | LAB/admin only |
| Docs drift | Low | Non-blocking |

---

## GO / NO-GO

| Question | Verdict |
|----------|---------|
| Path commit safe? | **GO** |
| Ready for PR review? | **GO** |
| Ready for merge (operator decision)? | **GO** |
| Ready for deployment after merge? | **GO** (path alignment) |
| Fixes all legacy path issues repo-wide? | **NO-GO** — Tier-2+ remain |

**Overall path commit: GO**
