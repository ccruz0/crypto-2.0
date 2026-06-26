# Path Canonicalization Go / No-Go

**Date:** 2026-06-09  
**Reviewer:** Automated audit (working tree inspection)

---

## Decision matrix

| # | Question | Answer |
|---|----------|--------|
| 1 | Is the path migration safe? | **Yes** — aligns deploy tooling with verified PROD (`crypto-2.0`); Tier-1 changes are mechanical path swaps with no business logic |
| 2 | Is it ready for commit? | **Partial** — path-only subset is ready; **current working tree mixes auth changes** — split before commit |
| 3 | Is it ready for PR? | **Yes**, after path-only commit on a clean branch |
| 4 | Is it ready for merge? | **Yes**, after PR review confirms no auth/trading/schema diffs |
| 5 | Is it ready for deployment? | **Yes for path** — merge to `main` triggers SSM deploy to correct directory |
| 6 | What blockers remain? | (a) Uncommitted tree bundles auth + path — must split; (b) Tier-2 scripts still legacy; (c) PAT-only prod needs `ALLOW_LEGACY_GITHUB_PAT` via auth patch or manual env until GitHub App SSM exists |
| 7 | GitHub App work — before or after path PR? | **Path PR first, then GitHub App** — path fix unblocks render/inject on correct tree; App SSM provisioning and auth cutover are independent follow-on |

---

## Rationale

### Safe because

- PROD verified running from `/home/ubuntu/crypto-2.0`
- Tier-1 deploy files were deploying/writing to non-existent or stale legacy path
- Changes are string substitutions in deploy/SSM shell — no trading, OpenClaw, Jarvis, schema, or Docker image changes
- SSM **parameter names** correctly left unchanged

### Not ready as-is because

- Branch `fix/github-app-legacy-transition-render` combines:
  - 11 path-safe files
  - 4 auth-related files (`render_runtime_env.sh`, `GITHUB_APP_AUTH.md`, partial `verify_deploy_secrets.sh`, partial `runtime.env.example`)
- Operator rules specified path canonicalization PR — auth render logic is a **different concern**
- ~30+ Tier-2 files still reference legacy path (ops/diag/docs) — non-blocking for CI deploy but creates doc/ops drift

---

## Recommended sequence

```
1. Path-only PR  → merge  → deploy (fixes cwd/secrets path)
2. Auth transition PR (render_runtime_env ALLOW_LEGACY auto-write)  → merge  → deploy
3. GitHub App SSM provisioning + cutover PR  → merge  → deploy
4. Tier-2 path cleanup PR (optional, lower priority)
```

---

## Go / No-Go

| Scope | Decision |
|-------|----------|
| Path canonicalization (11 files) | **GO** |
| Combined working tree (15 files) | **NO-GO** — split required |
| Deploy after path merge only | **GO** (path alignment) |
| Deploy assuming full GitHub App auth | **NO-GO** until App SSM + cutover |
