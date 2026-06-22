# Phase 6.1 — CLI Path Resolution Task (`_cursor_cli_path() → cursor-agent`)

> **Purpose:** Close the **second blocking prerequisite of 6.1** — the one the symbol
> contract (`PHASE_6_1_CURSOR_AUTH_CONTRACT.md`) does **not** capture. The seven symbols can
> be implemented perfectly and ACW still dies if the bridge resolves the Cursor CLI to the
> editor `cursor` instead of `cursor-agent`: the §2.4 read-only probe (`status --format json`)
> fails on the editor binary → `is_cursor_agent_logged_in()` is always `False` → every ACW is
> aborted on a false "no auth."
>
> **Status:** Implementation task (read-only investigation product). No code/config changed.
>
> **Evidence basis:** repo `main`; `cursor_execution_bridge.py` and `docker-compose.lab.yml`
> read verbatim (see §2). All host validation below is **proposed for the human to run on the
> LAB host** — not executed here.

---

## 1. Why this is its own artifact (not an appendix to the symbol contract)

It is a discrete unit of work with its own root-cause, scope, validation, and rollback, and —
decisively — it is a **6.1 blocker that the symbol contract cannot express**. "Symbols compile"
is necessary, not sufficient; this is the layer where a perfect merge still fails to execute.
Burying it as a footnote to the symbol contract would hide an independent blocker. Same reasoning
that moved the staging/`--trust` appendix out of the taxonomy doc.

---

## 2. Root cause — verified in source (the fix is config-dominant, not "one function")

The resolution chain, traced verbatim, with **defaults as they stand today**:

1. **The function** returns an env var or a default:
   ```python
   # backend/app/services/cursor_execution_bridge.py:64
   _DEFAULT_CURSOR_CLI = "cursor"
   # backend/app/services/cursor_execution_bridge.py:142-143
   def _cursor_cli_path() -> str:
       return (os.environ.get("CURSOR_CLI_PATH") or "").strip() or _DEFAULT_CURSOR_CLI
   ```
2. **The LAB compose does not set `CURSOR_CLI_PATH`** (`docker-compose.lab.yml:39-43` sets
   `JARVIS_*`, `CURSOR_BRIDGE_*`, `ATP_STAGING_ROOT` — not `CURSOR_CLI_PATH`). So in-container,
   `_cursor_cli_path()` returns the bare default `"cursor"`.
3. **Bare `"cursor"` resolves to nothing executable — because the mount source is an empty
   directory, not a binary.** The bind-mount:
   ```yaml
   # docker-compose.lab.yml:59
   - ${CURSOR_CLI_HOST_PATH:-/home/ubuntu/.local/bin/cursor}:/usr/local/bin/cursor:ro
   ```
   The default host source `/home/ubuntu/.local/bin/cursor` is **an empty, root-owned directory**
   (`drwxr-xr-x root root`, created `Jun 18 22:31` — the signature of Docker auto-creating a
   bind-mount source that did not exist on the host). There is **no `cursor` binary there at all**;
   the host has only `agent` and `cursor-agent` symlinks → the real agent CLI
   (`…/versions/2026.06.16-20-30-07-a07d3ac/cursor-agent`). So inside the container
   `/usr/local/bin/cursor` is an empty directory; `command -v cursor` finds nothing.

**Two decoupled variables.** The function reads `CURSOR_CLI_PATH` (in-container); the compose
only defines `CURSOR_CLI_HOST_PATH` (host side of the mount). Fixing one does not touch the other.
This is why the fix is **config + (maybe) function**, not "one function."

**Net (verified live in LAB container `automated-trading-platform-backend-lab`):**
`CURSOR_CLI_PATH` is unset → `_cursor_cli_path()` returns `'cursor'` → `shutil.which('cursor')` is
`None` (`/usr/local/bin/cursor` `isdir=True, isfile=False`) → the §2.4 probe
`subprocess.run(["cursor","status",...])` raises `FileNotFoundError` → fail-closed `False` → every
ACW aborted. **The mechanism is *missing binary*, not *wrong binary*; a fix premised on "replace
the editor" would target a binary that isn't there.** The symbol contract is blind to this by design.

---

## 3. The three verification points (verify the real layer before fixing)

Carried from review; all three are "confirm the layer that actually resolves, not the one we
assume." Same discipline that caught this binary mismatch in the first place.

1. **Verify the function's *output*, not just the binary's availability.** `command -v cursor-agent`
   confirms the agent CLI *exists*; it does **not** confirm `_cursor_cli_path()` *returns* it. The
   bug lives in resolution. Acceptance must assert the resolved path, e.g. (in the LAB container
   env): invoke `_cursor_cli_path()` and assert it points at `cursor-agent`, not a PATH `cursor`.
2. **Read how it resolves *today* before deciding code-vs-config.** Already done in §2: it reads
   `CURSOR_CLI_PATH` or defaults to `"cursor"`. The fix is therefore predominantly **config**
   (set the right binary into the container + point the function at it), with an optional code
   change to make the default safer (see §4). Do not assume "edit the function" — the env/compose
   layers dominate.
3. **Confirm what the LAB compose actually mounts.** `docker-compose.lab.yml:59` maps
   `${CURSOR_CLI_HOST_PATH:-/home/ubuntu/.local/bin/cursor}` → `/usr/local/bin/cursor:ro`. With the
   default, the **editor** binary is mounted into the container at the path the bridge calls. The
   fix may have to change the mount (source and/or target), not only the Python — verify on the
   host which binary the running container actually has at `/usr/local/bin/cursor`.

---

## 4. Fix options (decision deferred to human; do not apply)

Both make the agent CLI the one the bridge calls; they differ in clarity. Listed, not chosen.

- **(A) Config-only — now insufficient on its own.** Setting `CURSOR_CLI_HOST_PATH` to an agent path
  fixes the mount source, but `CURSOR_CLI_PATH` stays unset so code still calls bare `cursor`, and it
  does **not** touch the third wiring site below. Smallest diff, but leaves the trap decoupled.
- **(B, decided sub-variant) Explicit and self-documenting.** Mount the real `cursor-agent` to
  `/usr/local/bin/cursor-agent` (target rename) **and** set `CURSOR_CLI_PATH=/usr/local/bin/cursor-agent`
  in the LAB compose. Canonical variable confirmed by grep: **`CURSOR_CLI_PATH` is the only variable
  the running code reads** (`cursor_execution_bridge.py:143` + the diag scripts); `CURSOR_CLI_HOST_PATH`
  feeds **only** the bind-mount source (`docker-compose.lab.yml:59`). Naming the agent explicitly in the
  canonical variable means the empty-dir trap cannot silently recur.

**Recommendation to put to the human: (B), the explicit sub-variant above** — not merely flipping
`_DEFAULT_CURSOR_CLI`. The extra lines buy a config that says what it is. This is a config change on
LAB enablement and remains the human's call.

**Third wiring site to clean up (same fix):** `backend/scripts/diag/run_acw_v2_bugfix_validation.py:47`
does `os.environ.setdefault("CURSOR_CLI_PATH", ".../remote-cli/cursor")` — a third place pinning an
**editor** remote-cli path into the canonical variable. Residue of the same reverted experiment;
flag for removal/correction so it cannot override a fixed LAB config.

**Caveat — binary self-containment (verify, don't assume):** `cursor-agent` lives under
`…/versions/<build>/cursor-agent`. Bind-mounting the single file may break it if it depends on sibling
files in its install tree. Before landing the fix, confirm whether to mount the binary alone or the
`versions/<build>/` (or `~/.local/share/cursor-agent`) tree, and point `CURSOR_CLI_PATH` at the binary
within it. Re-confirm on the actual LAB execution host — the build/layout may differ by version.

---

## 5. Validation — proposed for the human to run on the LAB host (not executed here)

1. **Binary identity (host):** `readlink -f /home/ubuntu/.local/bin/cursor-agent`; `cursor-agent --help`
   shows `agent`, `status|whoami`.
2. **What the container actually has:** `docker compose -f docker-compose.lab.yml exec <svc> sh -c
   'readlink -f "$(command -v cursor)"; cursor --help 2>&1 | head'` (or the cursor-agent path under
   option B) — confirm it is the agent CLI, not the editor.
3. **Function output (the actual bug):** in the container env, evaluate `_cursor_cli_path()` and
   assert the resolved binary supports `status`/`agent` (the real predicate the §2.4 probe needs).
4. **End-to-end probe:** `is_cursor_agent_logged_in()` returns `True` against a logged-in session
   in the LAB container (after `cursor-agent login` on the host, per symbol-contract §2.1 cause msg).

---

## 6. Scope / risk / rollback

- **Scope:** LAB enablement config (`docker-compose.lab.yml` env + bind-mount), optionally one
  Python default (`_DEFAULT_CURSOR_CLI`). **No symbol-contract changes.** Does not widen the
  filesystem or consent boundary (still `:ro`, still no `--trust`).
- **Risk:** low — path/binary resolution only; isolated to LAB.
- **Rollback:** revert the compose lines (and the one-line default, if changed). No data, no schema,
  no production surface touched.

---

## 7. Phase 6 blockers — in upstream order

Three blockers are stacked for the ACW path to run end-to-end in LAB. **The symbol contract is
structurally blind to two of them** (it only specifies blocker 3). Ordered most-upstream first,
because an upstream one kills the path before a downstream one is even reached:

1. **`ENVIRONMENT=lab` rejected at import-time — most upstream.** A *cold* Python subprocess that
   imports `app.services` under `ENVIRONMENT=lab` crashes before any cursor-auth code runs:
   `EnvironmentSettings` is a strict `Literal["local","aws"]` (`environment.py:13,233`) and rejects
   `'lab'`, whereas the functional detector `getRuntimeEnv()` (`environment.py:41`) tolerates it
   (non-`aws` → `local`). See `PHASE_6_ENVIRONMENT_LAB_BLOCKER.md`.
   - **Scope caveat (source-corrected, do not overstate):** the **live server** and any **in-process**
     ACW code are *insulated*, because `entrypoint.sh:14-18` sources `secrets/runtime.env` (which
     defines `ENVIRONMENT=`) and overrides the compose `ENVIRONMENT=lab` for PID 1 (server returns
     HTTP 200). The crash reproduces only in **cold subprocesses that skip the entrypoint and do not
     pre-set `ENVIRONMENT=local`**. Whether this actually blocks an ACW-critical path (e.g. a staging
     pytest phase) is the open scope question in the new doc — verify, don't assume.
2. **CLI-path — this document.** Empty-directory mount → `_cursor_cli_path()` → `FileNotFoundError`
   → probe always `False` → ACW aborted (§2).
3. **The 7 cursor-auth symbols — `PHASE_6_1_CURSOR_AUTH_CONTRACT.md`.** Undefined symbols → module
   `ImportError` → ACW path dead.

All three must be resolved for ACW end-to-end. The symbol contract's §6 already reclassifies CLI path
resolution as a blocking prerequisite "alongside the merge"; this file specifies it. (Cross-references
by filename can be added in a later pass.)
