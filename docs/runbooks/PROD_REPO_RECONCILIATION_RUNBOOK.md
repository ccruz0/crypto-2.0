# PROD Repo Reconciliation Runbook

## 1. Purpose

PROD runtime is healthy (API, nginx, docker, SSM, swap). The working tree on the PROD instance is **not aligned with Git**: local changes and untracked files prevented `git pull` from succeeding. That drift creates future deployment risk — updates and runbooks that assume a clean pull may fail or overwrite unknown local state. This runbook helps an operator **inspect, classify, and safely reconcile** the PROD repo with Git without risking the running system.

---

## 2. Current Known State

- **Swap:** Already enabled and verified on PROD. `/swapfile` exists; `swapon --show` confirms 2G swap active; `/etc/fstab` contains the swap entry. Swap was deployed via equivalent inline commands through SSM, not by pulling repo changes.
- **Runtime:** Healthy. nginx active, SSM (snap unit) active, API health returns 200.
- **Git:** `git pull` failed on PROD because of **local changes** (modified tracked files) and **untracked files** that would be overwritten by merge. The folder `infra/aws/prod_swap` does not yet exist in the PROD working tree.
- **Repo drift:** The repo on PROD is out of sync with the remote; future deploys that assume a clean tree may conflict or lose local state if not handled carefully.

If you connect via **SSM Session Manager** as `ssm-user`, the repo is under ubuntu’s home: use **`/home/ubuntu/crypto-2.0`** instead of `~/crypto-2.0` in the commands below.

---

## 3. Safety Rules

- **Do not run a hard reset blindly** — you may lose uncommitted work or operational tweaks.
- **Do not remove files without reviewing them** — untracked or modified files may be intentional hotfixes or config.
- **Do not interrupt running services** — reconciliation is a filesystem/Git operation; do not restart docker, nginx, or timers as part of this.
- **First inspect, then classify, then reconcile** — understand what is different before changing anything.

---

## 4. Inspection Commands

Run these on the PROD instance (e.g. via SSM or SSH as the user that owns the repo). If `~/crypto-2.0` does not exist (e.g. you are `ssm-user`), use `cd /home/ubuntu/crypto-2.0` instead.

```bash
cd ~/crypto-2.0
git status
git branch --show-current
git remote -v
git rev-parse HEAD
git stash list
find . -maxdepth 3 -type f | sort | tail -200
```

Use the output to see modified/untracked paths, current branch, remote, and a sample of files under the repo.

---

## 5. Classification Workflow

Classify each relevant path so you can decide how to reconcile:

- **Tracked modified files:** Files Git knows about that have local changes. Decide: keep (stash or commit), discard (reset), or merge manually.
- **Untracked files:** Not in Git. Decide: add to repo (if intentional), copy elsewhere as backup, or remove only if clearly disposable.
- **Generated/runtime artifacts:** Build outputs, logs, or env files that should not be in Git. Optionally add to `.gitignore` and exclude from reconciliation.
- **Intentional hotfixes:** Local changes that were applied on PROD for a reason. Preserve (backup, commit to a branch, or document) before overwriting.
- **Unknown/manual changes:** When in doubt, treat as “preserve until reviewed.” Copy to a backup location outside the repo before any destructive Git action.

---

## 6. Safe Reconciliation Options

Documented options only; choose after inspection and classification.

### Option A: Stash local tracked changes

Stash modified tracked files (no untracked), then pull. Restore stash and resolve conflicts if needed. Does not remove untracked files; those must be handled separately (backup, then `git clean` or manual remove only after review).

### Option B: Commit local operational changes to a temporary branch

Create a branch (e.g. `prod-local-YYYYMMDD`), commit all local changes there, then switch back to main (or your deploy branch) and pull. Preserves a record of what was on PROD; you can diff or cherry-pick later.

### Option C: Copy unknown files out of the repo before cleanup

Copy untracked and important modified files to a backup directory outside the repo (e.g. `~/prod-repo-backup-YYYYMMDD` or `/home/ubuntu/prod-repo-backup-$(date +%Y%m%d)`). Then you can safely run stash, pull, or clean without losing unknown state. Compare backup to repo after pull to decide what to re-apply.

### Option D: Fresh clone to a parallel directory for comparison

Clone the same repo to a new directory (e.g. `~/crypto-2.0-fresh` or `/home/ubuntu/crypto-2.0-fresh`). Diff against the current working tree to see exactly what is different. No changes to the live repo until you decide; use the fresh clone as reference for a clean state.

**Recommendation:** Prefer the **lowest-risk path**: inspect first, create a backup of unknown/untracked files (Option C), use a parallel fresh clone for diff (Option D), then decide whether to stash (A), commit to a temp branch (B), or manually merge — without running `git reset --hard` or `git clean -fd` blindly.

---

## 7. Recommended Path

1. **Inspect:** Run the inspection commands (§4) and capture `git status` and any `git diff` summaries.
2. **Backup:** Copy unknown or important untracked/modified files to a backup directory outside the repo before any destructive step.
3. **Compare:** Optionally clone the repo to a parallel directory and diff to see exactly what differs from a clean tree.
4. **Decide:** Only then choose whether to stash (A), commit to a temporary branch (B), or manually merge specific changes. Do not run destructive Git commands until backup and classification are done.
5. **Verify:** After reconciliation, ensure `git status` is clean or understood, and that runtime (nginx, docker, API) is unaffected.

---

## 8. What Not To Do

- **No `git reset --hard` without a backup** — you will lose all local changes.
- **No `git clean -fd` blindly** — untracked files may be operational or intentional.
- **No deploy while repo drift is unresolved** — deploy scripts may assume a clean pull or overwrite local state.
- **No assumption that local changes are irrelevant** — they may be hotfixes or config; inspect and classify first.

---

## 9. Exit Criteria

Reconciliation is **complete** only when:

- **Git status is understood** — every modified or untracked path is classified and either preserved, committed, or intentionally discarded.
- **Important local files are preserved** — backup or commit so nothing critical is lost.
- **Repo can pull cleanly or is intentionally re-based** — either `git pull` succeeds or you have a documented reason (e.g. temporary branch with local commits) and a plan to sync later.
- **Runtime remains unaffected** — no service restarts or config changes were required for the reconciliation itself; nginx, docker, SSM, and API are still healthy.
