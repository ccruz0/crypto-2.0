# Phase 6 — `ENVIRONMENT=lab` Import-Time Blocker (source-first)

> **Status:** Read-only investigation product. No code/config changed, no fix applied.
> **Scope of this doc:** document the blocker, its root cause, why the live server survives it, who
> it actually affects, and the fix options — leaving the decision to the human.
> **Evidence basis:** repo working tree on branch `cursor/phase-6.1-cursor-auth-contract`; live LAB
> container `automated-trading-platform-backend-lab`. All code claims carry `file:line`. Host/container
> observations are marked **[verify on LAB host — do not assume]**.

---

## 0. Central finding

The live LAB server answers **HTTP 200** on `/api/health`, **but** a *cold* Python process inside the
same container —

```sh
docker exec automated-trading-platform-backend-lab \
  python -c "from app.services.cursor_execution_bridge import _cursor_cli_path"
```

— raises:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for EnvironmentSettings
ENVIRONMENT
  Input should be 'local' or 'aws' [type=literal_error, input_value='lab', input_type=str]
  (raised at app/core/environment.py:233)
```

**That contradiction is the finding:** the same image, same container, same `ENVIRONMENT=lab` — yet the
server boots and a cold `from app.services …` does not. [verify on LAB host — do not assume]

---

## 1. Root cause — two environment detectors that disagree

The codebase has **two** notions of "what environment am I in," and they handle `'lab'` differently:

- **Strict pydantic global (crashes on `'lab'`):**
  ```python
  # backend/app/core/environment.py:10-13
  class EnvironmentSettings(BaseSettings):
      """Environment-specific settings"""
      ENVIRONMENT: Literal["local", "aws"] = "local"
  ```
  ```python
  # backend/app/core/environment.py:233
  settings = EnvironmentSettings()
  ```
  This module-level instantiation runs on **any import** of `app.core.environment`. With env
  `ENVIRONMENT=lab`, pydantic validates `'lab'` against `Literal["local","aws"]` → `ValidationError`.

- **Lenient functional detector (tolerates `'lab'`):**
  ```python
  # backend/app/core/environment.py:41-45
  env = (os.getenv("ENVIRONMENT") or "local").strip().lower()
  if env == "aws":
      return "aws"
  else:
      return "local"  # Default to local for safety
  ```
  `getRuntimeEnv()` maps anything-not-`aws` (including `'lab'`) to `'local'`. So the *functional* logic
  treats lab as local without error — it is only the strict global that rejects it.

(There is also a separate, lenient settings class — `backend/app/core/config.py:30` declares
`ENVIRONMENT: str = "local"` (not a `Literal`) — confirming the strictness is specific to
`EnvironmentSettings`, not project-wide.)

The transitive import chain that triggers the crash for `app.services`:
`app/services/__init__.py:24` → `telegram_notifier.py:35` → `from app.core.environment import getRuntimeEnv`
→ runs `environment.py:233` → boom.

---

## 2. Why the server survives but a cold subprocess does not

The LAB container env (compose) sets the strict value:

```yaml
# docker-compose.lab.yml (backend-lab environment:)
- ENVIRONMENT=lab
- APP_ENV=lab
- EXECUTION_CONTEXT=LAB
```

But the container **entrypoint** re-sources a runtime env file *after* compose env is applied, and
exports it into the main process:

```sh
# backend/entrypoint.sh:14-18
if [ -f /app/secrets/runtime.env ]; then
  set -a
  . /app/secrets/runtime.env
  set +a
fi
```

**Evidence (no secret values read):**
- `/app/secrets/runtime.env` **defines an `ENVIRONMENT=` key** (`grep -c "^ENVIRONMENT="` → `1`; value
  intentionally not read). [verify on LAB host — do not assume]
- The server returns HTTP 200, i.e. PID 1's `EnvironmentSettings()` did **not** crash → its effective
  `ENVIRONMENT` is a valid `local`/`aws`, supplied by the sourced `runtime.env` overriding the compose
  `lab`.
- `docker exec` does **not** run `entrypoint.sh`, so it does **not** source `runtime.env`; it sees only
  the compose `ENVIRONMENT=lab` (`docker exec … echo $ENVIRONMENT` → `lab`). That is exactly why the
  cold import crashes while the server does not. [verify on LAB host — do not assume]
- `/proc/1/environ` was **permission-denied** from the exec shell, so PID 1's value was confirmed
  *indirectly* (runtime.env key + HTTP 200), not by reading the process env directly. **Open, verify:**
  read PID 1's effective `ENVIRONMENT` with appropriate privileges to confirm the exact normalized value.

**This is the source-located normalization the fix decision hinges on:** the server is normalized by
`entrypoint.sh` sourcing `runtime.env`. Anything that does **not** go through that entrypoint, and does
**not** itself set `ENVIRONMENT=local`, runs against the raw `lab`.

---

## 3. Scope — who actually hits this

Single strict instantiation: **`environment.py:233`** (triggered by any import of `app.core.environment`,
hence transitively by `app.services`).

- **Live server / in-process ACW code — NOT affected.** Runs inside PID 1, normalized by the entrypoint.
- **The two ACW diag scripts — self-mitigated.** They force the valid value before importing:
  ```python
  # backend/scripts/diag/run_acw_v2_bugfix_validation.py:30,41
  os.environ.setdefault("ENVIRONMENT", "local")
  os.environ["ENVIRONMENT"] = "local"
  # backend/scripts/diag/run_acw_v21_cursor_bridge_readiness.py:32,44  (same pattern)
  ```
  (The very existence of this workaround is evidence the crash was hit before and patched locally,
  not globally — i.e. the root cause was never fixed, only sidestepped per-script.)
- **Open scope question — the candidate that would make this a real ACW blocker:** any **cold
  subprocess** the bridge spawns that imports `app.services`/`app.core.environment` **without** the
  entrypoint and **without** pre-setting `ENVIRONMENT=local`. Prime suspect: a **staging pytest phase**
  (the bridge clones the repo and runs tests; `backend/tests/conftest.py` does **not** normalize
  `ENVIRONMENT`). Other importers of `app.services` to check: `app/jarvis/change_execution/test_runner.py`,
  `app/jarvis/change_execution/sandbox.py`. **Verify how each is launched (entrypoint? env passed?
  `ENVIRONMENT` pre-set?) before asserting impact — do not assume.**

**Honest correction to the going-in assumption:** this was framed as the *unconditional* most-upstream
blocker ("the ACW subprocess doesn't load `app.services` at all"). Source shows it is **conditional**:
upstream *for any cold-subprocess path that imports `app.services` under raw `lab`*, but the in-process
server path is insulated. Whether it blocks ACW end-to-end depends on the §3 open question above.

---

## 4. Fix options (listed, NOT chosen, NOT applied)

Decision is the human's. Each needs the §3 scope answer first.

- **(A) Accept `lab` in the strict model.** `ENVIRONMENT: Literal["local","aws","lab"]` (or relax to
  `str` like `config.py:30`). *Trade-off:* must audit every reader of `settings.ENVIRONMENT` to ensure
  `'lab'` behaves like `'local'` downstream (the functional `getRuntimeEnv()` already maps it, but the
  strict `settings.ENVIRONMENT` attribute would now expose raw `'lab'`).
- **(B) Normalize `lab → local` before the global builds**, replicating what the server's entrypoint
  effectively does — e.g. normalize at the top of `environment.py` before line 233, or guarantee every
  cold entry path sets `ENVIRONMENT=local` (generalize the per-diag workaround into one shared place).
  *Trade-off:* a single normalization point is cleanest but changes import-time behavior for all
  consumers; the per-path approach is narrower but easy to forget (which is how we got here).
- **(C) Make cold subprocesses go through the same normalization** (entrypoint or a shared bootstrap),
  rather than touching the model at all. *Trade-off:* fixes the launch path, not the latent strict/lenient
  divergence, which would remain a trap for the next cold importer.

No recommendation is locked here; (B) and (C) address the root divergence, (A) addresses the symptom.

---

## 5. Phase 6 blocker ranking

Within the three stacked blockers (see `PHASE_6_1_CLI_PATH_TASK.md` §7):

- This (`ENVIRONMENT=lab`) is the **most upstream** *for any cold-subprocess code path that imports
  `app.services` under raw `lab`* — it kills the import before CLI-path (blocker 2) or the cursor-auth
  symbols (blocker 3) are reached.
- It is **not** upstream for the in-process server path, which is insulated by the entrypoint.
- **Therefore:** resolve the §3 open question first. If an ACW-critical path runs as such a cold
  subprocess (e.g. staging pytest), this is the first blocker to fix; if not, it is a latent fragility
  to fix on its own merit but not a hard gate for in-process ACW. Verify on the LAB execution host
  before treating either conclusion as settled.
