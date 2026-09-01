---
name: prod-deploy
description: Review and deploy ATP to production AWS. Use when the operator says deploy, review and deploy, ship to prod, or asks whether a merge reached dashboard.hilovivo.com.
---

# Production deploy (ATP)

Production is `https://dashboard.hilovivo.com`. Health: `https://dashboard.hilovivo.com/api/health`. Header badge `v{n}` is the operator changelog (from `VERSION_HISTORY` in `frontend/src/app/page.tsx`).

Human saying **deploy** / **review and deploy** is approval to ship. Do not invent extra production writes (SSH, compose, DB).

## 1. Review before deploy

Compare `origin/main` to what is live:

- Latest successful **Deploy frontend** and **Deploy backend** runs (`gh run list --workflow=deploy-frontend.yml` / `deploy-backend.yml`).
- Prod badge: fetch `/` and read `v0.xx`. Last known gap pattern: bot-merged PRs sit on `main` while prod stays on an older `v`.

Ship only when review is clean (tests already green on the merge, version history bumped, no protected-path surprises).

## 2. Why merge ≠ deploy

`deploy-frontend.yml` and `deploy-backend.yml` trigger on `push` to `main` **or** `workflow_dispatch`.

Squash-merge via `GITHUB_TOKEN` (Cloud Agent auto-merge) **does not** start those workflows. After a bot merge, prod stays on the previous deploy until someone runs **Run workflow**.

Cloud Agents **cannot** `workflow_dispatch` (`gh workflow run` → HTTP 403). The operator must click.

## 3. Operator clicks (required)

Use branch **`main`** (the SHA already on `main`, e.g. the merge commit):

1. [Deploy frontend](https://github.com/ccruz0/crypto-2.0/actions/workflows/deploy-frontend.yml) → Run workflow
2. [Deploy backend](https://github.com/ccruz0/crypto-2.0/actions/workflows/deploy-backend.yml) → Run workflow

They share concurrency group `atp-prod-ec2-deploy` (`cancel-in-progress: false`). Queue both; they serialize. Backend is ~7 min, frontend ~2 min.

Do not use `deploy_session_manager.yml` for a normal FE/BE ship (it skips `frontend-aws` / `backend-aws`).

## 4. Verify

- Both runs **success** on the intended SHA.
- `GET /api/health` → `{"ok":true}`.
- Dashboard header shows the new `v{n}` (hard-refresh if the old badge is cached).

If a run fails, read the job log; do not retry blindly in parallel with an in-flight compose deploy.

## 5. Do not

- Force-push or amend to “trigger” deploy.
- Kill host processes by name.
- Deploy from a feature branch unless the operator names that ref.
- Treat Rahyang Admin (`dashboard.rahyang.com`) as this repo — that is a different Cloud Agent / workspace.
