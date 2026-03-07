# OpenClaw Final Security Checklist

Use this checklist to validate the OpenClaw Lab deployment: token scope, label protection, branch protection, path-guard, secrets exposure, Docker isolation, and API permissions. **Do not modify production or branch rules.**

---

## 1. Token Scope Validation

| Check | Expected | How to verify |
|-------|----------|----------------|
| **Contents** | Read and write | Create branch, push commit; must succeed. |
| **Pull requests** | Read and write | Open PR via API; must return 201 and create PR. |
| **Metadata** | Read | Repo clone/fetch works. |
| **Issues** | No access | Apply label to issue/PR via API; must return **403**. |
| **Admin** | None | Cannot change repo settings, branch protection, or secrets. |

**Test commands (Lab instance — manual only; do not log stdout or commands):**

```bash
TOKEN=$(cat ~/secrets/openclaw_token)
# Create PR (expect 201)
curl -s -w "\n%{http_code}" -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/ccruz0/crypto-2.0/pulls" \
  -d '{"title":"Scope test","head":"<branch>","base":"main"}' | tail -1
# Apply label (expect 403)
curl -s -w "\n%{http_code}" -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/ccruz0/crypto-2.0/issues/1/labels" -d '["documentation"]' | tail -1
unset TOKEN
```

**Pass criteria:** Push and create PR succeed; add label returns 403.

---

## 2. Label Protection Validation

| Check | Expected | How to verify |
|-------|----------|----------------|
| OpenClaw PAT cannot add/remove labels | 403 Forbidden | `POST /repos/:owner/:repo/issues/:issue_number/labels` with PAT. |
| Label bypass removed | N/A | Path-guard no longer allows bypass via label; protected path changes always fail the check. |

**Test:** Run the “Apply label via API” command in **Phase 2** of LAB_SETUP_AND_VALIDATION.md. Expect **403**.

**Pass criteria:** Label API returns 403 for the fine-grained PAT.

---

## 3. Branch Protection Validation

| Check | Expected | How to verify |
|-------|----------|----------------|
| **main** is protected | Yes | GitHub → Settings → Branches → rule for `main`. |
| Required status checks include | path-guard, no-inline-secrets, nightly-trivy, audit-pairs | Shown in branch protection rule. |
| PR required before merge | Yes | Direct push to main blocked (except allowed bypass list if any). |
| No modification from Lab | N/A | Do not run any API or Git commands that change branch protection. |

**Verification:** Manual check in GitHub UI. Do **not** change branch rules from automation or Lab.

**Pass criteria:** main has protection enabled with the required checks listed; no changes made from Lab.

---

## 4. Path-Guard Validation

| Check | Expected | How to verify |
|-------|----------|----------------|
| Path-guard workflow runs on PRs to main | Yes | Open a PR that touches a protected path; path-guard job runs. |
| PR touching protected path | Fails | Path-guard always fails (no label bypass). |
| Protected paths include | routes_control, routes_manual_trade, routes_orders, crypto_com_trade, runtime, trading_guardrails, telegram_secrets, secrets/, .env.aws, nginx/dashboard.conf, docker-compose.yml, Dockerfile.aws, deploy.yml | See `.github/workflows/path-guard.yml` and `scripts/openclaw/path_guard_protected.txt`. |

**Test:** Create a PR that only changes a comment in `backend/app/api/routes_control.py`. Path-guard should fail (no label bypass).

**Pass criteria:** Path-guard fails for protected path changes without label; passes with label (or for non-protected changes).

---

## 5. Secrets Exposure Check

| Check | Expected | How to verify |
|-------|----------|----------------|
| Token not in repository | Yes | No file under version control contains the PAT. |
| Token not in .env.lab | Yes | `.env.lab` has no line like `OPENCLAW_GITHUB_TOKEN=ghp_...`. |
| Token only in ~/secrets/openclaw_token on Lab | Yes | Single host file; permissions 600; owner ubuntu. |
| Token not in container env | Yes | `docker exec openclaw env` shows no variable whose value is the token. |
| Token not in logs | Yes | Application must never log the token or the file content; review code/logs. |

**Commands (Lab):**

```bash
# Token file exists and is not in repo
ls -la ~/secrets/openclaw_token
grep -r "ghp_\|github_pat_" ~/automated-trading-platform --include="*.yml" --include="*.yaml" --include="*.env*" 2>/dev/null || true
# Expected: no matches in repo

# .env.lab must not contain token value (path is hardcoded in docker-compose, not in .env)
grep -E "TOKEN|token" ~/automated-trading-platform/.env.lab 2>/dev/null || true
# Expected: no line with token value; OPENCLAW_TOKEN_PATH is not used (path is in compose).

# Container env has path only
docker exec openclaw env | grep -i token
# Expected: OPENCLAW_TOKEN_FILE=/run/secrets/openclaw_token
```

**Pass criteria:** Token only in `~/secrets/openclaw_token`; container env has path only; no token in repo or logs.

---

## 6. Docker Isolation Verification

| Check | Expected | How to verify |
|-------|----------|----------------|
| **Non-root** | Container runs as uid 1000 (or configured user) | `docker exec openclaw id` → uid=1000 gid=1000. |
| **read_only** | Root filesystem read-only | `docker exec openclaw touch /x` → Read-only file system. |
| **cap_drop: ALL** | No capabilities | `docker exec openclaw cat /proc/self/status` (CapEff 0). |
| **no-new-privileges** | Set | `docker inspect openclaw` → SecurityOpt includes no-new-privileges. |
| **pids_limit** | Set (e.g. 256) | `docker inspect openclaw` → PidsLimit 256. |
| **mem_limit** | 2G | `docker inspect openclaw` → Memory 2147483648. |
| **cpus** | 1.0 | `docker inspect openclaw` → NanoCpus 1e9. |
| **No docker socket** | Not mounted | `docker exec openclaw ls /var/run/docker.sock` → No such file. |
| **Token mount** | Read-only secret at /run/secrets/openclaw_token | `docker exec openclaw ls -la /run/secrets/openclaw_token` → exists, readable. |

**Commands:**

```bash
docker exec openclaw id
docker exec openclaw touch /x 2>&1
docker exec openclaw ls /var/run/docker.sock 2>&1
docker inspect openclaw --format '{{.HostConfig.SecurityOpt}}'
docker inspect openclaw --format '{{.HostConfig.PidsLimit}}'
docker inspect openclaw --format '{{.HostConfig.Memory}}'
docker inspect openclaw --format '{{.HostConfig.NanoCpus}}'
docker exec openclaw ls -la /run/secrets/openclaw_token
```

**Pass criteria:** All items match expected; no docker socket; token file present and read-only.

---

## 7. API Permission Test

| Action | Method | Expected HTTP | Notes |
|--------|--------|---------------|--------|
| Create branch (push) | Git over HTTPS | Success | Contents R/W. |
| Create PR | POST /repos/:owner/:repo/pulls | 201 | Pull requests R/W. |
| List PRs | GET /repos/:owner/:repo/pulls | 200 | Pull requests R. |
| Add label to issue/PR | POST .../issues/:num/labels | **403** | No Issues access. |
| Modify branch protection | PATCH /repos/.../branches/main/protection | 403 | No admin. |
| Read repo | GET /repos/:owner/:repo | 200 | Metadata/Contents. |

**One-shot test script (Lab; token in env briefly):**

```bash
export TOKEN=$(cat ~/secrets/openclaw_token)
echo "Create PR: $(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" 'https://api.github.com/repos/ccruz0/crypto-2.0/pulls' -d '{"title":"API test","head":"<branch>","base":"main"}')"
echo "Add label: $(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github+json" 'https://api.github.com/repos/ccruz0/crypto-2.0/issues/1/labels' -d '["documentation"]')"
unset TOKEN
```

**Pass criteria:** Create PR 201; Add label 403; no token logged.

---

## Summary Table

| # | Area | Pass criteria |
|---|------|----------------|
| 1 | Token scope | Contents + PR R/W; Metadata R; Issues 403. |
| 2 | Label protection | PAT gets 403 when adding label. |
| 3 | Branch protection | main protected; required checks set; no changes from Lab. |
| 4 | Path-guard | Fails on protected path without label; passes with label. |
| 5 | Secrets exposure | Token only in ~/secrets/openclaw_token; not in repo or .env. |
| 6 | Docker isolation | Non-root, read_only, cap_drop, pids_limit, limits, no docker socket, token ro. |
| 7 | API permission | Create PR 201; add label 403. |

---

## References

- **Lab setup and validation commands:** docs/openclaw/LAB_SETUP_AND_VALIDATION.md  
- **Architecture and hardening:** docs/openclaw/ARCHITECTURE.md  
- **Deployment blueprint:** docs/openclaw/DEPLOYMENT.md  
- **Cost model:** docs/openclaw/COST_MODEL.md  
