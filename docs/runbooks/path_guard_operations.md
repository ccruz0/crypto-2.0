# Path guard — operations runbook

How to operate and troubleshoot LAB filesystem policy enforced by `app.services.path_guard`.

---

## 1. Verify path guard is active

1. Confirm `ATP_PATH_GUARD_DISABLE` is **unset** or not `true` / `1` / `yes` / `on`.
2. Trigger a LAB flow that writes under `docs/` (e.g. OpenClaw note apply, strategy analysis callback in a dev environment). The write should succeed.
3. Optional: set `PATH_GUARD_LOG_ALLOWED=true` to emit **INFO** lines with JSON payload `path_guard_write_allowed` for every guarded write (verbose).

---

## 2. Logs to check

| Log fragment | Meaning |
|--------------|---------|
| `path_guard_write_allowed` | Guard accepted a write (DEBUG by default; INFO if `PATH_GUARD_LOG_ALLOWED` set) |
| `path_guard_write_blocked` | Write rejected; JSON includes `normalized_path`, `zone` (`workspace_non_docs` / `outside_workspace`), `context` |
| `path_guard_patch_blocked` | `assert_lab_patch_target` rejected a path |
| `path_guard_disabled` | Guard bypassed (`ATP_PATH_GUARD_DISABLE`); LAB writes are not policy-checked |

Search examples:

```bash
grep path_guard_write_blocked /var/log/atp/backend.log
grep path_guard_patch_blocked /var/log/atp/backend.log
```

---

## 3. Troubleshooting blocked writes

1. Read the **ERROR** line JSON: `normalized_path`, `attempted_path`, `context` (caller hint).
2. If the path **should** be LAB-safe documentation output:
   - Prefer moving the feature to write under `docs/...`.
   - If the process **must** use a writable directory outside `docs/` (e.g. read-only mount), set one of:
     - `AGENT_ARTIFACTS_DIR`
     - `AGENT_BUG_INVESTIGATIONS_DIR`
     - `AGENT_CURSOR_HANDOFFS_DIR`
     - or `ATP_PATH_GUARD_EXTRA_ALLOWED_PREFIXES` (comma-separated; absolute or workspace-relative)
3. If the write is **intended to change application code or runtime config**, it must **not** use path guard as the primary gate — route through **governance manifest + executor** after approval.

**Operator-facing error text:** `PathGuardViolation` message includes the resolved path and a short rule name (`workspace_non_docs`, `outside_workspace`, etc.).

---

## 4. How to add a new safe writable path

1. **Default choice:** place outputs under `docs/<your-area>/` — no config change.
2. **New top-level outside `docs/`:** requires a deliberate product/security decision. Then either:
   - Add a dedicated env var in `path_guard._configured_fallback_roots()` (code change + review), or
   - Use `ATP_PATH_GUARD_EXTRA_ALLOWED_PREFIXES` for environment-specific roots.

Avoid widening policy to entire workspace or `$HOME`.

---

## 5. LAB-safe vs governed PROD mutation

| Question | If “yes” → |
|----------|------------|
| Is the output **documentation, analysis, handoff text, or release notes** under `docs/`? | **LAB path guard** is appropriate. |
| Does it change **Python/TS/services**, **migrations**, **compose**, **secrets**, or **runtime flags** on PROD? | **Governance manifest + executor**, not path guard as the sole control. |

---

## 6. Recovery when a workflow fails on a blocked write

1. Capture `path_guard_write_blocked` JSON from logs.
2. Fix **configuration** (artifact dir env vars) or **code** to target `docs/` or an allowed fallback.
3. **Do not** leave `ATP_PATH_GUARD_DISABLE=true` in steady state; use only to unblock an incident, then revert.
4. Re-run the task or callback; confirm allow logs (with `PATH_GUARD_LOG_ALLOWED` if needed).

---

## 7. Static audit script (`path_guard_audit.py`)

Run from the **backend** directory (or pass paths relative to repo layout as you normally do for scripts):

```bash
cd backend
python scripts/path_guard_audit.py
python scripts/path_guard_audit.py -v
python scripts/path_guard_audit.py --fail-on-lab-bypass
python scripts/path_guard_audit.py --fail-on-lab-bypass --ci
python scripts/path_guard_audit.py --include-scripts -v
```

| Flag | Effect |
|------|--------|
| *(default)* | Scan `app/services/*.py` only |
| `-v` / `--verbose` | Print **info**-severity hits (exempt files, probes, PROD modules) |
| `--fail-on-lab-bypass` | Exit **1** if any **error** hit in LAB-enforced service files: raw `write_text` / `open(w|a|…)` **or** `shell=True`, `os.system(`, string-form `subprocess.run("`/`Popen("`, `asyncio.create_subprocess_shell(` |
| `--ci` | CI-oriented banner + GitHub Actions `::error file=…,line=…` annotations for each **error** finding (use with `--fail-on-lab-bypass` in CI) |
| `--include-scripts` | Also scan `backend/scripts` (mostly informational unless you extend policy) |

### CI (GitHub Actions)

- Workflow: **LAB path guard audit** — `.github/workflows/lab-path-guard-audit.yml`.
- Command: `cd backend && python scripts/path_guard_audit.py --fail-on-lab-bypass --ci`
- **Fails the job only** when the scanner reports **error**-severity matches in `LAB_ENFORCED` files under `backend/app/services` (see `LAB_ENFORCED` and `SUBPROCESS_LAB_PATTERNS` in `path_guard_audit.py`). PROD/operational modules are in `EXEMPT_BASENAMES` and do not produce errors. **List-argv** `subprocess.run([...])` without `shell=True` does not fail CI (used for git/cursor/tests in `cursor_execution_bridge`).
- **Does not** run with `--include-scripts` — script findings stay **advisory** (run locally if needed).

**Fixing a red CI**

1. Open the annotated file/line in the PR checks (or read the log `=== error ===` block).
2. **Write-pattern errors:** replace raw `Path.write_text` / `open(..., "w")` with `path_guard.safe_write_text`, `safe_open_text`, etc., for LAB outputs under `docs/` or artifact dirs.
3. **Subprocess-pattern errors:** remove `shell=True` and string-shell `subprocess.run("...")`; use an argument list. For file output to `docs/`, build content in Python and call `path_guard.safe_*` — do not use `echo … >`, `tee`, or shell redirection from LAB-enforced code.
4. If the line is an intentional non-artifact probe (e.g. staging writability), add an end-of-line `pg-audit-ignore` and a short comment **why** — do not use this for real OpenClaw/doc writes or to hide `shell=True`.

**Note:** The workflow named **Path Guard** (`path-guard.yml`) only blocks PRs that modify a fixed list of high-risk paths; it is not this audit.

**Interpreting findings**

- **error** in a LAB-enforced file: refactor to `path_guard.safe_*` or add a rare `pg-audit-ignore` with a one-line justification (staging probes only).
- **warn** in other `agent_*` / `governance_*` files: review manually — may be PROD or operational.
- **info** on exempt files (`agent_strategy_patch.py`, `config_loader.py`, …): expected; confirms the scanner saw a write pattern.

**When to refactor to path_guard**

- Output is **documentation, analysis, handoffs, recovery artifacts**, or other **LAB-safe** material under `docs/` or configured artifact dirs.

**When to leave a write outside path_guard**

- **Governed PROD mutation** (patches, deploy-related file writes after approval).
- **Operational storage** (logs, caches, fallback JSON, trigger files, exchange export logs).
- **Staging / tmp** probes that only test writability of non-repo directories.

**Subprocess in LAB-enforced modules**

- **OK (not flagged):** `subprocess.run([executable, ...], cwd=staging, …)` with **no** `shell=True` — typical for git, Cursor CLI, pytest, npm in `cursor_execution_bridge`.
- **CI failure:** `shell=True`, `os.system`, `create_subprocess_shell`, or `subprocess.run("one big shell string", …)`.
- **Advisory:** the audit does **not** parse list elements for embedded `>` / `tee`; rely on code review for exotic argv.

---

## Related docs

- [PATH_GUARD_DESIGN.md](../governance/PATH_GUARD_DESIGN.md)
- [IMPLEMENTATION_NOTES.md](../governance/IMPLEMENTATION_NOTES.md) (covered write surfaces)
- [ATP_OPENCLAW_GOVERNANCE.md](../governance/ATP_OPENCLAW_GOVERNANCE.md)
