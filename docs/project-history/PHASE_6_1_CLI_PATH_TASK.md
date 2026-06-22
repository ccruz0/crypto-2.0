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
3. **Bare `"cursor"` resolves via PATH to `/usr/local/bin/cursor`**, which is the bind-mount
   target:
   ```yaml
   # docker-compose.lab.yml:59
   - ${CURSOR_CLI_HOST_PATH:-/home/ubuntu/.local/bin/cursor}:/usr/local/bin/cursor:ro
   ```
   The default host source `/home/ubuntu/.local/bin/cursor` is the **editor remote-cli**
   (`--diff`/`--merge`/`--install-extension`, no `agent`/`status`) — *not* the agent CLI, which
   lives at `/home/ubuntu/.local/bin/cursor-agent` (per symbol-contract §3).

**Two decoupled variables.** The function reads `CURSOR_CLI_PATH` (in-container); the compose
only defines `CURSOR_CLI_HOST_PATH` (host side of the mount). Fixing one does not touch the other.
This is why the fix is **config + (maybe) function**, not "one function."

**Net:** with current defaults, the LAB container wires the *editor* binary to the path the bridge
calls. The probe fails 100% of the time. The symbol contract is blind to this by design.

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

- **(A) Config-only.** Set `CURSOR_CLI_HOST_PATH=/home/ubuntu/.local/bin/cursor-agent` so the mount
  carries the *agent* binary into the container at `/usr/local/bin/cursor`; bare `"cursor"` then
  resolves to the agent CLI. Smallest diff, but semantically misleading (a binary named `cursor`
  that is actually `cursor-agent`).
- **(B) Explicit and self-documenting.** Mount to `/usr/local/bin/cursor-agent` (target rename) and
  set `CURSOR_CLI_PATH=cursor-agent` in the LAB compose (and/or change `_DEFAULT_CURSOR_CLI` to
  `"cursor-agent"`). Touches compose env + mount + optionally the Python default; the resulting
  config says what it means.

Recommendation to put to the human: **(B)** — the extra lines buy a config that cannot be silently
misread as the editor again. But this is a config change on LAB enablement and is the human's call.

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

## 7. Relationship to the symbol contract

This task and `PHASE_6_1_CURSOR_AUTH_CONTRACT.md` are the **two prerequisites of 6.1**: the symbol
merge (that contract) and correct CLI path resolution (this file). Neither alone makes 6.1
end-to-end functional. The symbol contract's §6 already reclassifies CLI path resolution as the
"second blocking prerequisite of 6.1 (alongside the merge)"; this file is that blocker specified.
(A cross-reference by filename can be added to §6 in a later pass — deliberately omitted now to keep
the contract at its sealed 261-line `--stat`.)
