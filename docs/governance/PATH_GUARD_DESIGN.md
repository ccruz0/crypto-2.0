# LAB path guard — design

Defense-in-depth for **OpenClaw and other LAB-side agents**: even if classification, prompts, or workflow logic mis-route work, normal code paths should **not** be able to persist files under `backend/`, `frontend/`, or other runtime areas using the guarded APIs.

**Implementation:** `backend/app/services/path_guard.py`  
**Operations:** [path_guard_operations.md](../runbooks/path_guard_operations.md)

---

## 1. Purpose

- **Single policy** for “where may LAB write?”
- **Fail closed** on disallowed targets (`PathGuardViolation`, subclass of `PermissionError`)
- **Structured logs** for allow (optional INFO) and deny (ERROR): `path_guard_write_allowed`, `path_guard_write_blocked`, `path_guard_patch_blocked`

This layer is **not** a substitute for governance manifests and `governance_executor` for **PROD mutations**.

---

## 2. Threat model

| Risk | Mitigation |
|------|------------|
| Prompt / logic asks to write a patch into `backend/` from a “LAB” callback | Guarded writers reject paths outside policy before `write_text` |
| Path traversal (`docs/../backend/foo`) | Paths are **resolved**; must sit under allowed roots |
| Misconfigured relative path | Resolution is relative to **workspace root** from `app.services._paths.workspace_root()` |

**Out of scope for this module:**

- Processes that **bypass** Python helpers (shell `echo > backend/foo.py`, direct DB writes, etc.) — controlled by OS IAM, deployment layout, and review.
- **Symlink escape** if `docs/` or a fallback dir contains a symlink pointing outside the allowed tree: `Path.resolve()` follows symlinks; operators should not point artifact trees at sensitive locations. Prefer real directories under `docs/` or dedicated `/tmp/agent-*` dirs.
- Code that uses **raw** `Path.write_text` / `open(..., "w")` without going through `path_guard` — see inventory and audit in [IMPLEMENTATION_NOTES.md](./IMPLEMENTATION_NOTES.md); run `backend/scripts/path_guard_audit.py`.

---

## 3. Why governance alone is not enough

Governance enforces **which execute path** runs after approval (manifest digest, classification, Telegram gate). If a bug marks a writer as “safe LAB” or a callback writes to disk **before** execution gates, policy at the executor would be too late. Path guard limits **filesystem effects** of LAB-oriented modules regardless of higher-level labels.

---

## 4. Allowed LAB write roots

| Root | Notes |
|------|--------|
| `<workspace_root>/docs/` | All subpaths (analysis, agents, runbooks, releases, etc.) |
| `AGENT_ARTIFACTS_DIR` | If set — resolved absolute path |
| `AGENT_BUG_INVESTIGATIONS_DIR` | If set |
| `AGENT_CURSOR_HANDOFFS_DIR` | If set |
| `/tmp/agent-artifacts`, `/tmp/agent-bug-investigations`, `/tmp/agent-cursor-handoffs` | Default fallbacks when repo `docs/` is read-only (e.g. Docker bind mounts) |
| `ATP_PATH_GUARD_EXTRA_ALLOWED_PREFIXES` | Comma-separated extra roots; relative entries are resolved under workspace root |

---

## 5. Blocked / non-LAB paths

Any path that, after resolution, is:

- Under the **workspace** but **not** under `docs/`, or  
- **Outside** the workspace **and** outside the configured fallback roots  

→ **denied** for guarded operations.

Examples of blocked targets:

- `backend/**`, `frontend/**`, `scripts/**`, repository `config/**`, `.env*`, compose files at repo root (when addressed as workspace-relative paths outside `docs/`).

**PROD code and patch application** (e.g. `agent_strategy_patch.py`, governed executor steps) **do not** use this guard; they remain behind manifests and human approval.

---

## 6. Normalization and traversal

1. `coerce_resolved_path(path)`: absolute paths → `resolve()`; relative paths → `(workspace_root() / path).resolve()`.
2. `classify_lab_write_target(resolved)`: `resolved.relative_to(docs_root)` or `relative_to(each fallback)` must succeed.
3. Parent directories of a file write are also checked (`assert_writable_lab_path` on parent) so creating `docs/../../backend/x` via parent creation is still rejected once the final resolved path is evaluated.

---

## 7. Relation to governance manifests

| Concern | Mechanism |
|---------|-----------|
| **LAB notes, analysis markdown, handoffs, changelog under `docs/`** | `path_guard` on guarded APIs |
| **Applying patches to application code, deploy, restart, migrations** | `governance_manifests` + `governance_executor` + classification in `agent_execution_policy` |

If a new feature needs to write **both** a doc and **code**, split responsibilities: doc via `path_guard`; code via governed pipeline only.

---

## 8. API summary

| Function | Role |
|----------|------|
| `assert_writable_lab_path` | Validate; raise `PathGuardViolation` if denied |
| `safe_mkdir_lab` | `mkdir` after assert |
| `safe_write_text` / `safe_write_bytes` | Create parent dirs (asserted) then write |
| `safe_append_text` | Append after assert |
| `safe_open_text` | Context manager; assert on `w`/`a` |
| `assert_lab_patch_target` | Same as assert for patch targets; logs `path_guard_patch_blocked` on failure |

---

## 9. Disable switch (emergency only)

`ATP_PATH_GUARD_DISABLE=true` — skips checks (warning logged). Use only for break-glass recovery; not for routine LAB work.

---

## 10. Limitations and remaining risks

- **Uncovered call sites** that still use raw I/O (see implementation notes).
- **Operational scripts** under `backend/scripts/` are not all retrofitted; several doc-oriented scripts now use `path_guard` (see IMPLEMENTATION_NOTES).
- **Runtime logs** (`logs/agent_activity.jsonl`) and **task fallback JSON** (`backend/app/data/`) are intentional non–`docs/` persistence paths for reliability, not OpenClaw artifact generation — they are **not** routed through LAB path guard today.

---

## 11. Bypass risk (what path_guard does **not** catch automatically)

| Bypass | Notes |
|--------|--------|
| **Direct `Path.write_text` / `open(..., "w")`** in services or scripts | No runtime check unless the call site uses `path_guard` helpers. |
| **Shell / subprocess** (`>`, `tee`, `cat >`, `shell=True`) | **Runtime:** `path_guard` never sees these; LAB-safe outputs must not rely on shell redirection into repo paths — build strings in Python and call `path_guard.safe_*`. **Audit:** in `LAB_ENFORCED` files only, `path_guard_audit.py` flags `shell=True`, `os.system(`, string-form `subprocess.run("` / `Popen("`, and `asyncio.create_subprocess_shell(` as **errors** (CI fails). List-argv `subprocess.run([...])` without `shell=True` is **not** flagged (used for git/cursor/tests in staging). |
| **`shutil` / `os.rename` into repo** | Not scanned by `path_guard` at runtime. |
| **Code outside `backend/app/services`** | Frontend, CI, local tools — separate review. |

**Guarded helpers** only enforce policy when invoked. **Static audit** (`backend/scripts/path_guard_audit.py`) is a lightweight second line: it flags (1) common **write** patterns across `app/services`, and (2) **high-risk subprocess** patterns **only inside `LAB_ENFORCED` basenames** — so CI can catch shell-based bypasses in OpenClaw/LAB modules without flagging every `git`/`docker` call elsewhere.

---

## 12. Relationship: guarded helpers ↔ audit script

- **`path_guard`**: runtime enforcement for paths that go through its API.
- **`path_guard_audit.py`**: regex-based scan; **no understanding** of control flow. It may false-positive on docstrings or miss dynamic paths. It does **not** parse shell strings for `>` / `tee` — those remain a **process/code-review** risk if someone introduces them inside LAB-enforced code.
- **`pg-audit-ignore`**: optional end-of-line marker for intentional raw writes or (rarely) audit-exempt lines so the audit stays signal-heavy. Use sparingly and comment *why*. Prefer fixing the code instead of ignoring subprocess rules.

---

## 13. Developer workflow for new LAB-safe writes

1. Prefer writing under `docs/...` or an existing artifact env dir.
2. Use `path_guard.safe_write_text` / `safe_append_text` / `safe_mkdir_lab` (or `assert_writable_lab_path` before your own I/O).
3. Run `python backend/scripts/path_guard_audit.py` locally; match CI with `--fail-on-lab-bypass` (and `--ci` to preview GitHub annotations).
4. **CI:** `.github/workflows/lab-path-guard-audit.yml` runs the same strict scan on every PR/push to `main` (`--fail-on-lab-bypass --ci`). Only **error** hits in **LAB_ENFORCED** service files fail the build; exempt PROD/operational files and `pg-audit-ignore` lines are not errors. Scripts are not scanned in CI (advisory only via local `--include-scripts`).
5. If the change mutates **runtime code or PROD behavior**, use the **governance** path — do not “solve” it with path_guard only.
6. **Do not** use `shell=True`, `os.system`, or string-form `subprocess.run("...")` in **LAB-enforced** modules to create or overwrite files under the repo — use Python + `path_guard` for anything that must land under `docs/` or artifact dirs.

---

*Keep this document aligned with `path_guard.py` and `path_guard_audit.py` when policy changes.*
