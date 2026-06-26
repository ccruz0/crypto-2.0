# Jarvis Phase 5 — Safety Flag Verification (durable)

**Status:** Active
**Scope:** Verify the four Phase 5 write-gate flags are in their *documented safe
state*, durably (not just "right now in this process"). Complements
`jarvis-phase4b-readonly-launch.md` (launch) — this doc is the *verification*.

Read-only. No flag changes without explicit human approval (see `CLAUDE.md` §5).

---

## 1. The safe state is NOT "four falses"

The four flags split into two semantics. Anchoring an assertion to the literal
`false` is a trap: for the `*_ENABLED` flags `false` means a write *capability* is
off (safe), but for `REQUIRE_DOUBLE_APPROVAL` `false` turns off a *requirement*
(unsafe — it would let Phase 5 run on a single approval instead of Gate 1 **and**
Gate 2). Anchor assertions to the **documented safe value**, never to `false`.

| Variable | Gates | Safe value | When unsafe-present |
|---|---|---|---|
| `JARVIS_PATCH_APPLY_ENABLED` | Gate 1: sandbox patch apply. `approve-apply` raises / 403 when off (`change_execution/service.py`) | **`false`** | parses truthy |
| `JARVIS_PR_CREATION_ENABLED` | Gate 2: GitHub PR creation; blocked in `check_pr_creation_allowed()` (`github/pr_service.py`) | **`false`** | parses truthy |
| `JARVIS_GITHUB_WRITE_ENABLED` | write-capable git/gh (`git push`); blocks PR service | **`false`** | parses truthy |
| `JARVIS_REQUIRE_DOUBLE_APPROVAL` | requires **both** Gate 1 + Gate 2 for Phase 5 | **`true`** | present and parses falsey |

Source of truth: `backend/app/jarvis/change_execution/config.py` (defaults:
three `*_ENABLED` → `False`, `REQUIRE_DOUBLE_APPROVAL` → `True`).

---

## 2. Two independent axes — both must hold

These are complementary, not redundant:

- **In-process (gate == endpoint).** Always true *by construction*: the gate and
  the `safety-status` endpoint both call the same four functions in the same
  module via `_bool_env`, in the same process. `phase5_safety_status()` is the
  single reader; nothing else does `os.environ.get` on these four keys.
- **Disk vs memory (TOCTOU).** *Not* guaranteed. The backend loads these vars at
  process start only: `backend/entrypoint.sh` runs `set -a; . /app/secrets/runtime.env`
  on every container start (this is the authoritative loader — it runs *after*
  compose's `env_file` injection and `exec`s the app, so the sourced values win
  and are read fresh from disk each start). A manual edit to `runtime.env` that
  does **not** go through `persist_env_var_value()` (which mirrors the value into
  the *running* `os.environ`) is invisible to the live process — and to the
  endpoint — until the next container start. So a disk override sits armed and
  silently activates on the next routine redeploy.

The endpoint answers "armed in memory now". The disk grep answers "armed on disk,
will activate at next restart". You need both.

**Durable verification = endpoint (memory) + grep (disk) + post-restart assert in
the deploy pipeline.** Any one alone leaves a gap.

---

## 3. Checks

### 3.1 Memory (endpoint)

```bash
curl -s http://127.0.0.1:8002/api/jarvis/safety-status | python3 -m json.tool
```

Expected (safe):

```json
{
  "patch_apply_enabled": false,
  "pr_creation_enabled": false,
  "github_write_enabled": false,
  "double_approval_required": true
}
```

### 3.2 Disk (grep `runtime.env`)

Booleans, not secrets — grepping only these four lines exposes nothing.

```bash
grep -E 'JARVIS_(PATCH_APPLY_ENABLED|PR_CREATION_ENABLED|GITHUB_WRITE_ENABLED|REQUIRE_DOUBLE_APPROVAL)' \
  /path/to/runtime.env
```

Expected (safe):

```text
JARVIS_PATCH_APPLY_ENABLED=false
JARVIS_PR_CREATION_ENABLED=false
JARVIS_GITHUB_WRITE_ENABLED=false
JARVIS_REQUIRE_DOUBLE_APPROVAL=true
```

**Absence = default = safe.** `_bool_env` falls back to the default when a key is
empty/missing, and all four defaults already equal the safe value. A missing line
is therefore **not** a finding. Memory (endpoint) and disk (grep) are "in
agreement" when, for each key, the disk value (or its absence → default) resolves
to the same boolean the endpoint reports. This premise is coupled to the defaults
in `change_execution/config.py`; it is guarded against silent drift by
`test_phase5_env_defaults` (pins the four to `False/False/False/True`). If that
test is ever changed, revisit this doc.

**Don't eyeball the string — evaluate it.** `_bool_env` is
`raw.strip().lower() in {1, true, yes, on}` (everything else, including `false`,
`0`, `no`, `off`, and any garbage, is falsey). So a naïve `=false` / `=true`
matcher is wrong both ways: `JARVIS_PATCH_APPLY_ENABLED=1` (or `yes`/`on`/`True`)
is **enabled = unsafe** but passes a `=false`-only check, and
`JARVIS_REQUIRE_DOUBLE_APPROVAL=0` (or `no`/`off`) turns the requirement **off =
unsafe** but slips past a `=true`/`=false` matcher. Evaluate each value through
the same normalization as `_bool_env` and compare to the safe boolean — see §4.

**Duplicate keys are a finding.** If a key appears twice in `runtime.env`, what
lands in memory depends on the loader's precedence (typically last-wins), and the
endpoint reflects that — but a grep shows both lines and may evaluate the one that
doesn't win. Treat a duplicated key as a finding rather than guessing.

### 3.3 Post-restart assert (pipeline)

Have the deploy pipeline re-assert `safety-status` (§3.1) **after** the restart.
That is the step that actually catches a disk↔memory divergence, and it is the
*authoritative* disk→memory check: only the running process applies the loader's
real parsing of `runtime.env`.

What counts as "restart" here depends on the loader. In this repo the loader is
`backend/entrypoint.sh` (`set -a; . /app/secrets/runtime.env`), which **re-runs on
every container start**. So a container restart *does* re-read these flags:

```bash
docker compose --profile aws restart backend-aws   # re-runs entrypoint -> re-sources runtime.env
# (docker compose --profile aws up -d backend-aws also works, and recreates if config changed)
```

Note the subtlety: `restart` does **not** re-apply compose's `env_file` (that is
resolved at container *create*); it works here only because the entrypoint
re-sources the file itself. A pure hot reload that does **not** re-exec the
entrypoint — gunicorn/uvicorn `--reload`, `kill -HUP`, in-place worker recycle —
would re-assert against the *old* environment and prove nothing. Confirm your
pipeline step re-runs the entrypoint (restart/up), not a hot reload.

**Load-bearing precondition: the file must be bind-mounted, not baked.** The whole
re-source-on-restart mechanism only sees *disk* edits if `/app/secrets/runtime.env`
is a host bind mount, not a copy baked into the image. In this repo it is —
`backend-aws` mounts the directory `./secrets:/app/secrets` (so the entrypoint
reads the live host file). Verify it before trusting §3.3:

```bash
grep -nE '^\s*-\s*\./secrets:/app/secrets' docker-compose.yml
docker inspect backend-aws --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' | grep secrets
```

If `./secrets` is **not** mounted into `/app/secrets`, `restart` re-sources a stale
baked copy and §3.3 gives a false "memory == disk". A directory mount (not a
file-only mount) is also required so `persist_env_var_value()`'s `mkstemp`-beside
works.

**Confirm empirically before trusting this** (state-changing — run on the host
with approval, not from the agent): flip one key in `runtime.env`, restart, and
check the endpoint moved.

```bash
# 1) baseline
curl -s http://127.0.0.1:8002/api/jarvis/safety-status
# 2) toggle a low-risk key on disk (e.g. set JARVIS_REQUIRE_DOUBLE_APPROVAL=false), then:
docker compose --profile aws restart backend-aws
# 3) endpoint must now reflect the change; revert the key and restart again
curl -s http://127.0.0.1:8002/api/jarvis/safety-status
```

If the endpoint does **not** move after `restart`, the entrypoint is not
re-sourcing in your environment — switch the pipeline step to
`docker compose --profile aws up -d --force-recreate backend-aws`.

---

## 4. Automating the disk check

Don't re-implement a parser — **use the loader the backend uses.**
`backend/entrypoint.sh` does `set -a; . runtime.env`, so the faithful way to learn
what the four vars *will* resolve to in memory is to source the file the same way
in an isolated subshell and read them back. This makes quote/comment stripping,
`export ` lines, and duplicate precedence (last-wins) all resolve exactly as they
will at container start — no string-level guessing, no "ambiguous" bucket. The
only step left is the boolean comparison, which mirrors `_bool_env`.

Exit codes are three-valued so a broken mount can't masquerade as safe:
**0 = safe, 1 = unsafe, 2 = cannot verify.**

```bash
#!/usr/bin/env bash
# Verify Phase 5 write-gate flags resolve to the documented safe state, using the
# SAME loader as backend/entrypoint.sh (`set -a; . runtime.env`).
# Run ONLY against the real runtime.env — sourcing executes the file (see caveats).
# Exit: 0 = safe | 1 = unsafe | 2 = cannot verify (unreadable / unsourceable / partial).
set -u
ENV="${1:?usage: check.sh /path/to/runtime.env}"
[ -r "$ENV" ] || { echo "cannot read $ENV" >&2; exit 2; }

KEYS="JARVIS_PATCH_APPLY_ENABLED JARVIS_PR_CREATION_ENABLED JARVIS_GITHUB_WRITE_ENABLED JARVIS_REQUIRE_DOUBLE_APPROVAL"

# Source like the entrypoint, in a subshell; emit "KEY<TAB>set|unset<TAB>value" for the 4 keys only
# (never secrets). set-vs-unset is tracked separately from value, so set-but-empty != unset and no
# in-band sentinel can be spoofed by a literal value.
snapshot=$(
  set -a
  # shellcheck disable=SC1090
  . "$ENV" >/dev/null 2>&1 || exit 9
  set +a
  for k in $KEYS; do
    eval "st=\${$k+set}; v=\${$k-}"
    printf '%s\t%s\t%s\n' "$k" "${st:-unset}" "$v"
  done
) || { echo "cannot source $ENV (shell parse error)" >&2; exit 2; }

# Guard against a partial snapshot (file `exit`s mid-source): demand all 4 keys, else unverifiable.
[ "$(printf '%s\n' "$snapshot" | awk -F'\t' '$1 ~ /^JARVIS_/ {c++} END{print c+0}')" -eq 4 ] \
  || { echo "incomplete snapshot from $ENV (sourced file aborted early?)" >&2; exit 2; }

# Mirror _bool_env: raw.strip().lower() in {1,true,yes,on}. sed [[:space:]] also trims a trailing CR.
is_true() { case "$(printf '%s' "$1" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | tr 'A-Z' 'a-z')" in
  1|true|yes|on) return 0;; *) return 1;; esac; }

rc=0
field() { printf '%s\n' "$snapshot" | awk -F'\t' -v k="$1" -v n="$2" '$1==k{print $n}'; }
# $2: 1 = safe value is truthy (REQUIRE_DOUBLE_APPROVAL); 0 = safe value is falsey (the *_ENABLED gates)
check() {
  local key="$1" want_true="$2" st v; st=$(field "$key" 2); v=$(field "$key" 3)
  if [ "$st" != set ]; then echo "ok      $key unset -> default (safe)"; return; fi
  if [ "$want_true" -eq 1 ]; then
    if is_true "$v"; then echo "ok      $key=$v (safe)"; else echo "UNSAFE  $key='$v' (set; expected truthy)"; rc=1; fi
  else
    if is_true "$v"; then echo "UNSAFE  $key=$v (set; expected falsey)"; rc=1; else echo "ok      $key=$v (safe)"; fi
  fi
}

check JARVIS_PATCH_APPLY_ENABLED     0
check JARVIS_PR_CREATION_ENABLED     0
check JARVIS_GITHUB_WRITE_ENABLED    0
check JARVIS_REQUIRE_DOUBLE_APPROVAL 1

[ "$rc" -eq 0 ] && echo "RESULT: disk flags resolve to the documented safe state"
exit "$rc"
```

**Two caveats, by design:**

- **It sources the file**, i.e. executes it — same trust boundary as the entrypoint
  (anyone who can edit `runtime.env` already controls the entrypoint). It only
  prints the four booleans, never secrets. **Run it ONLY against the real
  `runtime.env`** (`./secrets/runtime.env` ↔ `/app/secrets/runtime.env`), never
  against an arbitrary file passed as `$1` from an untrusted source — that would
  widen the trust boundary to whoever produced that file.
- **For true loader parity, run it under the entrypoint's interpreter.** The
  entrypoint is `#!/bin/sh` (dash in the container image); for plain `KEY=value`
  lines dash and bash source identically, so in practice it doesn't matter — but if
  you want byte parity, invoke the checker with the *same* binary the entrypoint
  uses, not a generic `sh`.
- **It still isn't the final word** — it reads disk, not the live process. The
  running process may hold a different value (e.g. set via `persist_env_var_value()`
  without a restart, or a disk edit not yet loaded). §3.1 (endpoint) covers "now",
  §3.3 (post-restart endpoint) is the authoritative disk→memory confirmation. This
  script's job is to catch a disk value that *will* become live at next start.

---

## 5. Notes

- `_bool_env` is defined per config module; the one governing these four keys is
  in `change_execution/config.py`. Do not add a second reader for these keys —
  the single-reader property is what makes gate == endpoint hold by construction.
- **Two loaders, one authoritative.** Compose lists `./secrets/runtime.env` under
  `env_file:` for `backend-aws` (resolved at container *create*), **and**
  `backend/entrypoint.sh` does `set -a; . /app/secrets/runtime.env` on every start.
  The entrypoint runs after compose and `exec`s the app, so for these four keys the
  sourced (fresh-from-disk, shell-parsed: quotes/inline-comments stripped,
  last-wins on duplicates) values are what the process sees. That is why §4 sources
  the file rather than string-matching it, and why `restart` (which re-runs the
  entrypoint) suffices in §3.3. If the entrypoint source is ever removed, the
  env_file-only path is baked at create and §3.3 must switch to `up -d
  --force-recreate`.
- **Source of truth for the safe values** is `change_execution/config.py` (the
  `default=` on each function), not this doc. `test_phase5_env_defaults` pins them
  to `False/False/False/True`; if a default ever changes, that test fails and the
  "absence = safe" premise (§3.2) must be re-derived here.
- Hard floor regardless of flags: merge, deploy, and `push_to_main` remain
  **forbidden** in `execution/safety.py` (see `jarvis-phase4b-readonly-launch.md`).
