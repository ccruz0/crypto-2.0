# Label-Bypass Audit Report — ccruz0/crypto-2.0

**Goal:** Prove whether any automation can add labels (e.g. `security-approved`) and bypass path-guard; lock down so only humans can apply that label or remove the bypass.

---

## 1. Where label-bypass exists

| Location | Behavior |
|----------|----------|
| **`.github/workflows/path-guard.yml`** | **Only bypass in repo.** If the PR has the label `security-approved`, the job allows merge despite protected path changes (lines 52–56, 73–77). The workflow itself does **not** add the label; it only **reads** `github.event.pull_request.labels`. |

**Conclusion:** The bypass is “add label → path-guard passes.” Any actor that can add labels to a PR (fine-grained PAT with Issues/Labels, `GITHUB_TOKEN` with `issues: write`, or GitHub App with same) can add `security-approved` and bypass the gate. You confirmed the fine-grained PAT returns `x-accepted-github-permissions: issues=write; pull_requests=write` and can add labels.

---

## 2. Which workflows can add labels today

**Default `GITHUB_TOKEN`** (when workflow does not set `permissions:`) has `contents: read/write`, **`issues: write`**, **`pull-requests: write`**, so it **can** add labels. Any workflow without an explicit restrictive `permissions:` block gets that default.

| Workflow file | Sets permissions? | Can add labels? | Notes |
|---------------|-------------------|-----------------|--------|
| path-guard.yml | No | **Yes** (default token) | Only reads labels today; no step adds them. |
| dashboard-data-integrity.yml | No | **Yes** (default token) | Uses `github.rest.issues.createComment` (line 569); token has write. |
| no-inline-secrets.yml | No | **Yes** (default token) | No label logic; could add a step. |
| audit-pairs.yml | No | **Yes** (default token) | No label logic. |
| egress-audit.yml | No | **Yes** (default token) | No label logic. |
| aws-runtime-guard.yml | No | **Yes** (default token) | No label logic. |
| aws-runtime-sentinel.yml | No | **Yes** (default token) | No label logic. |
| deploy.yml | Yes (contents: read, id-token: write) | No | No issues/pull-requests. |
| deploy_session_manager.yml | No | **Yes** (default token) | No label logic. |
| restart_nginx.yml | No | **Yes** (default token) | No label logic. |
| disable_all_trades.yml | No | **Yes** (default token) | No label logic. |
| nightly-integrity-audit.yml | Yes (contents: read) | No | No issues/pull-requests. |
| security-scan.yml | Yes (contents, security-events, actions) | No | No issues/pull-requests. |
| security-scan-nightly.yml | Yes (same) | No | No issues/pull-requests. |

**External automation:** Any fine-grained PAT or GitHub App with **Issues: Read and write** (or repo permissions that include it) can add `security-approved` via API; no workflow change in this repo can revoke that. The only way to prevent bypass is to **remove the label-based bypass** in path-guard (Option A) so the label no longer affects the check.

---

## 3. Exact changes to prevent bots from applying security-approved

**Chosen approach: Option A — Remove label-based bypass entirely.**

- **path-guard.yml:** Remove the logic that allows protected path changes when `security-approved` is present. If any protected path is touched, the job **always fails**. Merging then requires either (1) not touching protected paths, or (2) a human temporarily disabling/overriding the required check (e.g. in branch rules), which is an explicit, auditable action.
- **No new workflow** that adds or removes labels; no dependency on who applied the label (GitHub rulesets cannot restrict “only team X can add this label” in a way we can enforce from inside the repo).

**Concrete change:**

- In **`.github/workflows/path-guard.yml`**: Delete the `HAS_APPROVAL` check and the branch that exits 0 when the label is present. When there are violations, always exit 1 and emit the same error message (do not mention the label).

---

## 4. Token/workflow permission reductions

- **path-guard.yml:** Add `permissions: contents: read, pull-requests: read` so it cannot add labels or modify PRs.
- **dashboard-data-integrity.yml:** Add `permissions: contents: read, pull-requests: write` (comment on PRs only; **no** `issues: write` so it cannot add labels).
- **All other workflows** that currently have **no** `permissions:` block: add minimal `permissions: contents: read, pull-requests: read` (and keep deploy.yml / security-scan* / nightly-integrity as they are).

**Files to patch:**

- `.github/workflows/path-guard.yml` — remove bypass; add permissions.
- `.github/workflows/dashboard-data-integrity.yml` — add permissions (contents: read, pull-requests: write).
- `.github/workflows/no-inline-secrets.yml` — add permissions.
- `.github/workflows/audit-pairs.yml` — add permissions.
- `.github/workflows/egress-audit.yml` — add permissions.
- `.github/workflows/aws-runtime-guard.yml` — add permissions.
- `.github/workflows/aws-runtime-sentinel.yml` — add permissions.
- `.github/workflows/deploy_session_manager.yml` — add permissions.
- `.github/workflows/restart_nginx.yml` — add permissions.
- `.github/workflows/disable_all_trades.yml` — add permissions.

---

## 5. Summary

| Item | Result |
|------|--------|
| **Where label-bypass exists** | Only in `path-guard.yml`: presence of `security-approved` allows protected path changes. |
| **Which workflows can label** | Any workflow without restrictive `permissions` (and any PAT/App with issues write). Listed above. |
| **Exact change to prevent bots** | Remove label bypass in path-guard (always fail on protected path changes); add minimal permissions to all workflows. |
| **Patch** | Applied: path-guard bypass removed; minimal permissions added to all workflows. |

---

## 6. Patch summary (exact changes)

### 6.1 `.github/workflows/path-guard.yml`
- **Comment:** Updated to state there is no label bypass.
- **Added:** `permissions: contents: read, pull-requests: read`.
- **Removed:** Entire `HAS_APPROVAL` / `LABELS_JSON` logic; when `VIOLATIONS` is non-empty, job always fails with the same error message (no “security-approved” mention).

### 6.2 `.github/workflows/dashboard-data-integrity.yml`
- **Added:** `permissions: contents: read, pull-requests: write` (comment on PRs only; no `issues: write` so workflow cannot add labels).

### 6.3 Workflows with `permissions: contents: read, pull-requests: read` added
- `no-inline-secrets.yml`
- `audit-pairs.yml`
- `egress-audit.yml`
- `aws-runtime-guard.yml`
- `aws-runtime-sentinel.yml`
- `deploy_session_manager.yml`
- `restart_nginx.yml`
- `disable_all_trades.yml`

### 6.4 Unchanged
- `deploy.yml` (already has `contents: read`, `id-token: write`)
- `nightly-integrity-audit.yml` (already `contents: read`)
- `security-scan.yml`, `security-scan-nightly.yml` (already minimal + `security-events: write`, `actions: read`)
