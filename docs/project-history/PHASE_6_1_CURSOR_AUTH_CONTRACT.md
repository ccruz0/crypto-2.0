# Phase 6.1 — Cursor-Auth Implementation Contract

> **Purpose:** Fix the incomplete merge that leaves the ACW path unable to import.
> Live application code (`coding_workflow/service.py`, `patch_bridge.py`) imports
> cursor-auth symbols from `app.services.cursor_execution_bridge` that **are not
> defined anywhere** — so the module raises `ImportError` at load and the whole ACW
> path is dead. This contract specifies the exact symbols to implement, against the
> live consumers and tests (not against reverted artifacts).
>
> **Status:** Implementation contract (read-only investigation product). No code changed.
>
> **Evidence basis:** repo `main` @ `a0eb7878480774226003f99b372a03826ca0935a`;
> `cursor-agent` CLI build `2026.06.16-20-30-07-a07d3ac` on this host.

---

## 0. Source-of-truth rule (read this first)

**Caches and logs are residue, not the tree's source of truth.** A symbol, flag, or
test that lives *only* in a cache or log file is evidence of something that was
**removed**, not of a current contract. This bit us three times in this investigation:

1. **`--trust`** — exists only in historical `.jsonl` agent-activity logs from a
   `t-trust` task; **zero** live `.py` files. Orphan of a reverted experiment.
2. **`TestCursorAuthPreflight::test_require_cursor_auth_raises_structured_error`** —
   exists only in `.pytest_cache/v/cache/nodeids`; the committed
   `backend/tests/test_cursor_execution_bridge.py` contains **no such class**. Stale.
3. The nodeid above was nearly fixed as an acceptance criterion — it would have been a
   ghost contract.

**Therefore:** the authoritative contract sources are the **live consumers**
(`service.py`, `patch_bridge.py`, the diag scripts) and the **live test**
(`test_coding_workflow.py`). Not the cache, not the logs.

---

## 1. The symbol surface (7 symbols + 1 constant)

All to be defined in `backend/app/services/cursor_execution_bridge.py` (the module the
consumers import from). The initial estimate was four symbols; investigating the diag
imports revealed the full surface is larger.

| Symbol | Kind | Evidence (live) |
|--------|------|-----------------|
| `CURSOR_AUTH_MISSING_ERROR` | `dict` constant | `test_coding_workflow.py:173,178`; `service.py:266,270` |
| `CursorAuthMissingError` | `Exception` subclass | `service.py:38,265`; `test_coding_workflow.py:173,176` |
| `require_cursor_auth()` | gate fn → `None` | `service.py:40,71`; `patch_bridge.py:19,221` |
| `is_cursor_agent_logged_in()` | predicate → `bool` | `test_coding_workflow.py:175`; `run_acw_v2_bugfix_validation.py:599,609` |
| `is_cursor_api_key_configured()` | predicate → `bool` | `run_acw_v2_bugfix_validation.py:600,608` |
| `get_cursor_auth_error()` | fn → `dict \| None` | `run_acw_v2_bugfix_validation.py:597,610` |
| `build_cursor_agent_invoke_args(cli, prompt, *, headless)` | argv factory → `list[str]` | `run_acw_v21_cursor_bridge_readiness.py:409,418,433` |

---

## 2. Per-symbol contract

### 2.1 `CURSOR_AUTH_MISSING_ERROR: dict[str, str]`

Canonical error payload. **Required keys: `code`, `cause`** (both consumed in
`service.py:266` `exc.error_info["code"]`, `service.py:270` `exc.error_info["cause"]`).
The test asserts equality against the raised exception's `.error_info`
(`test_coding_workflow.py:178`).

```python
CURSOR_AUTH_MISSING_ERROR: dict[str, str] = {
    "code": "cursor_auth_missing",
    "cause": "Cursor agent is not logged in (run `cursor-agent login` on the LAB host).",
}
```

### 2.2 `class CursorAuthMissingError(Exception)`

Carries `.error_info: dict`. When raised by the preflight, `.error_info ==
CURSOR_AUTH_MISSING_ERROR` (`test_coding_workflow.py:178`).

```python
class CursorAuthMissingError(Exception):
    def __init__(self, error_info: dict[str, str] | None = None):
        self.error_info = error_info or CURSOR_AUTH_MISSING_ERROR
        super().__init__(self.error_info.get("cause", "cursor auth missing"))
```

### 2.3 `is_cursor_api_key_configured() -> bool`

Pure env-var check — **distinct** from login state. This is *why* the test both deletes
`CURSOR_API_KEY` (`test_coding_workflow.py:171`) **and** mocks `is_cursor_agent_logged_in`
(:175): they are two independent predicates.

```python
def is_cursor_api_key_configured() -> bool:
    return bool((os.getenv("CURSOR_API_KEY") or "").strip())
```

(CLI confirms `--api-key` "can also use CURSOR_API_KEY env var" — see §3.)

> **Not an authentication gate.** This predicate is a *presence* check, not a
> *validity* check: `bool(CURSOR_API_KEY)` says "a non-empty variable exists," never
> "the key is valid or authenticates." It must **not** be used to gate preflight — that
> role is **exclusive to `is_cursor_agent_logged_in()` (§2.4)**, the live probe. `require_cursor_auth`
> (§2.6) correctly gates on login, never on this env-var check; this note exists so a
> future implementer seeing two auth-ish predicates does not wire the gate to the wrong one.

### 2.4 `is_cursor_agent_logged_in() -> bool` — **detection mechanism fixed (see §3)**

Probes the Cursor Agent CLI's authentication status via a **read-only status command**.
Returns `True` iff the CLI reports an authenticated session. Fail-closed: any error,
non-zero exit, timeout, or unparseable output → `False`.

```python
def is_cursor_agent_logged_in() -> bool:
    cli = _cursor_cli_path()
    try:
        r = subprocess.run(
            [cli, "status", "--format", "json"],   # read-only; NO `-p`, NO `--trust`, no prompt
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            return False
        data = json.loads(r.stdout or "{}")
        return bool(data.get("isAuthenticated") is True)  # do NOT log/persist userInfo (PII)
    except Exception:
        return False  # fail-closed
```

> **Security constraint (ratified):** the probe is `status`/`whoami` only — a pure
> auth-status read. It must never be a path that starts an agent session, and must never
> carry `-p`/`--print` or `--trust`. The detection mechanism must not widen what the
> bridge can do. (CLI evidence in §3.)

> **Timeout is a load-bearing false negative (by design, but know it).** Probe latency is
> ~15 s (§3) against a 30 s timeout, and fail-closed on timeout returns `False` — the safe
> direction (better abort than assume auth). The operational consequence: `require_cursor_auth()`
> runs in both `check_acw_submit_allowed` (`service.py:71`) and `patch_bridge.py:221`, so a
> single ACW flow can pay the probe cost twice, and a latency spike yields a false "not logged
> in" that aborts a legitimately-authenticated ACW. This is **not** a contract bug — the
> fail-closed behavior is correct. But if such aborts prove frequent in LAB, cache the probe
> result with a short TTL rather than raising the timeout. Do not solve it here; just don't be surprised.

### 2.5 `get_cursor_auth_error() -> dict | None`

Returns the error payload when auth is missing, else `None`. Used by the diag for a
non-raising preflight view (`run_acw_v2_bugfix_validation.py:610`).

```python
def get_cursor_auth_error() -> dict | None:
    if is_cursor_agent_logged_in():
        return None
    return CURSOR_AUTH_MISSING_ERROR
```

### 2.6 `require_cursor_auth() -> None`

The gate. Called with no args in `service.py:71` (`check_acw_submit_allowed`) and
`patch_bridge.py:221` (before provisioning staging / invoking the CLI).

```python
def require_cursor_auth() -> None:
    if not is_cursor_agent_logged_in():
        raise CursorAuthMissingError(CURSOR_AUTH_MISSING_ERROR)
```

### 2.7 `build_cursor_agent_invoke_args(cli, prompt, *, headless: bool = False) -> list[str]`

The **single argv producer**. Preserves the committed invoke shape — **without
`--trust`** (`cursor_execution_bridge.py:446-455`). Sole caller today is the readiness
diag (`run_acw_v21_cursor_bridge_readiness.py:418,433`, `headless=True`); no production
consumer constrains it, so this signature is frozen from the diag.

```python
def build_cursor_agent_invoke_args(cli: str, prompt: str, *, headless: bool = False) -> list[str]:
    # headless=True → current non-interactive prod shape: agent -p --output-format json <prompt>
    # NO --trust (closed by default — see §4).
    return [cli, "agent", "-p", "--output-format", "json", prompt]
```

**Required refactor:** `invoke_cursor_cli` must **use** this factory instead of building
argv inline, so there is exactly **one** place that produces the argv — making "no
`--trust`" a structurally verifiable property rather than an intention.

---

## 3. CLI evidence (same `file:line` standard, for the parts that are CLI behavior)

The detection mechanism rests on `cursor-agent` CLI behavior, which is host evidence, not
repo evidence — so it is cited here at the same standard, with the exact commands and
outputs observed.

- **Binary:** `/home/ubuntu/.local/bin/cursor-agent` → `…/versions/2026.06.16-20-30-07-a07d3ac/cursor-agent`.
  (Note: the `cursor` on `PATH` is the **editor remote-cli** — `--diff`/`--merge`/
  `--install-extension`, no `agent`/`status` — and is *not* the agent CLI. The bridge's
  `_cursor_cli_path()` must resolve to `cursor-agent`.)
- **`cursor-agent --help`** (verbatim, relevant lines):
  - `-p, --print` → *"Print responses to console … Has access to all tools, including write and shell."*
  - `--trust` → *"Trust the current workspace without prompting (only works with --print/headless mode)."*
  - `--api-key <key>` → *"API key for authentication (can also use CURSOR_API_KEY env var)."*
  - Commands include `login`, `logout`, and **`status|whoami` → "View authentication status."**
- **`cursor-agent status --help`:** options `--format <text|json>`. Read-only by description.
- **`cursor-agent status --format json`** (observed output shape; `userInfo` values redacted here):
  ```json
  {
    "status": "authenticated",
    "isAuthenticated": true,
    "hasAccessToken": true,
    "hasRefreshToken": true,
    "userInfo": { "email": "<redacted>", "userId": <redacted>, "createdAt": "<redacted>" }
  }
  ```
  → `is_cursor_agent_logged_in()` parses `isAuthenticated`. (Probe latency observed ~15 s,
  likely a token check — hence the 30 s timeout and fail-closed.)

---

## 4. The `--trust` decision (closed by default)

`--trust` is **not** emitted. Rationale, now backed by the CLI's own help (§3): `--trust`
"trust[s] the current workspace without prompting" in headless mode — i.e. it changes the
agent's **execution consent model** inside staging. It exists in zero live `.py` files and
in no design doc; it is an orphan of a reverted experiment (§0). The committed
`invoke_cursor_cli` already builds argv without it. The single-argv-producer refactor
(§2.7) makes this auditable in one place. **Adding `--trust` later is a security change
requiring its own human approval — never a line slipped into the argv factory.**

This does not widen the filesystem boundary (staging stays cwd-scoped and ephemeral), but
it does change the in-staging consent model — which is exactly why it is ratified
separately rather than assumed.

---

## 5. Acceptance criteria

1. **Import-time:** `from app.jarvis.coding_workflow import service, patch_bridge` imports
   with **no `ImportError`** (today it fails: `service.py:38,40` import undefined symbols at
   module level → the entire ACW path is dead).
2. **Live test passes:** `backend/tests/test_coding_workflow.py::test_acw_blocks_when_cursor_auth_missing`
   — and **NOT** `TestCursorAuthPreflight`, which is **stale** `.pytest_cache` residue from
   the reverted implementation (same pattern as `--trust`; see §0). Do not resurrect it as
   a criterion.
3. **All 7 symbols** in §1 are importable (the diag `run_acw_v2_bugfix_validation.py:595-601`
   imports `CursorAuthMissingError`, `get_cursor_auth_error`, `is_cursor_agent_logged_in`,
   `is_cursor_api_key_configured`; `run_acw_v21:409` imports `build_cursor_agent_invoke_args`).
4. **Single argv producer:** `invoke_cursor_cli` uses `build_cursor_agent_invoke_args`;
   `grep -rn "--trust" backend --include=*.py` returns **zero**.
5. **Probe is read-only:** `is_cursor_agent_logged_in` shells only `status`/`whoami`, never
   `-p`/`--print`, never `--trust`, never a prompt; returns only a bool and does not log/persist
   `userInfo`.

---

## 6. Open items explicitly NOT closed here

- **CLI path resolution — second blocking prerequisite of 6.1 (alongside the merge), not mere
  environment config.** `_cursor_cli_path()` must resolve to `cursor-agent`, not the editor
  `cursor`. If it resolves to the editor remote-cli (no `agent`/`status`), the §2.4 probe fails
  *every* time → `is_cursor_agent_logged_in()` is always `False` → every ACW is aborted on a
  false "no auth," even with the symbols compiling and the merge perfect. It is outside the
  *symbol* contract, but 6.1 is not end-to-end functional until it is verified on the LAB
  execution host. Treat "symbols compile" as necessary, not sufficient: the binary must be the
  right one.
- The detection-mechanism evidence in §3 is **CLI/host evidence** that should be
  re-confirmed on the actual LAB execution host before relying on it there (the build and
  output shape may differ by version).
