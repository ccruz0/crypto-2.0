# ALLOW_LEGACY_GITHUB_PAT Flag Verification

**Date:** 2026-06-09  
**Script inspected:** `scripts/aws/render_runtime_env.sh` (working tree version)  
**Question:** Does the render script automatically write `ALLOW_LEGACY_GITHUB_PAT=true` when `GITHUB_TOKEN` exists and `GITHUB_APP_*` is incomplete?

## Answer

**YES.**

The working-tree version of `render_runtime_env.sh` automatically writes `ALLOW_LEGACY_GITHUB_PAT=true` into `secrets/runtime.env` when:

1. The rendered file contains a `GITHUB_TOKEN=` line (non-empty PAT was sourced from SSM or `.env.aws`), **and**
2. The rendered file does **not** contain all three of:
   - `GITHUB_APP_ID=`
   - `GITHUB_APP_INSTALLATION_ID=`
   - `GITHUB_APP_PRIVATE_KEY_B64=`

---

## Exact lines and logic

### Preconditions (earlier in script)

| Lines | Behavior |
|-------|----------|
| 84–90 | Fetch `GITHUB_TOKEN` and three `GITHUB_APP_*` values from SSM (with LAB fallbacks for App keys) |
| 185 | `[[ -n "$GITHUB_TOKEN" ]] && printf "GITHUB_TOKEN=%s\n" "$GITHUB_TOKEN"` → writes PAT to runtime.env when present |
| 186–188 | Write each non-empty App key to runtime.env |
| 191–216 | When `source=primary`, `.env.aws` may override/append App keys |

Auth-mode block runs **after** all merges (line 254 comment).

### Detection (lines 255–261)

```bash
GITHUB_APP_ALL=no
grep -q '^GITHUB_APP_ID=' "$RUNTIME_ENV" \
  && grep -q '^GITHUB_APP_INSTALLATION_ID=' "$RUNTIME_ENV" \
  && grep -q '^GITHUB_APP_PRIVATE_KEY_B64=' "$RUNTIME_ENV" \
  && GITHUB_APP_ALL=YES
HAS_GITHUB_PAT=no
grep -q '^GITHUB_TOKEN=' "$RUNTIME_ENV" && HAS_GITHUB_PAT=YES
```

**Note:** Detection uses **presence of keys in the file**, not non-empty values. Empty App keys still count as "present" if written.

### Write / remove (lines 262–279)

| Condition | Action |
|-----------|--------|
| `GITHUB_APP_ALL == YES` | Set `GITHUB_AUTH_MODE=github_app`; **delete** any `ALLOW_LEGACY_GITHUB_PAT=` line |
| `HAS_GITHUB_PAT == YES` (and App incomplete) | Set `GITHUB_AUTH_MODE=legacy_transition`; **set or append** `ALLOW_LEGACY_GITHUB_PAT=true` |
| Neither | Set `GITHUB_AUTH_MODE=none`; **delete** any `ALLOW_LEGACY_GITHUB_PAT=` line |

Exact write when PAT-only (lines 268–274):

```bash
elif [[ "$HAS_GITHUB_PAT" == "YES" ]]; then
  GITHUB_AUTH_MODE=legacy_transition
  if grep -q '^ALLOW_LEGACY_GITHUB_PAT=' "$RUNTIME_ENV" 2>/dev/null; then
    sed -i 's|^ALLOW_LEGACY_GITHUB_PAT=.*|ALLOW_LEGACY_GITHUB_PAT=true|' "$RUNTIME_ENV"
  else
    printf "ALLOW_LEGACY_GITHUB_PAT=true\n" >> "$RUNTIME_ENV"
  fi
```

### Status output (line 282)

Prints summary including:

```
GITHUB_AUTH_MODE=legacy_transition ALLOW_LEGACY_GITHUB_PAT=YES
```

when PAT-only mode applies.

---

## Example runtime.env output (PAT present, App absent)

Given PROD SSM state (verified elsewhere):

- `/automated-trading-platform/prod/github_token` — **present**
- `/automated-trading-platform/prod/github_app/*` — **absent**

After `bash scripts/aws/render_runtime_env.sh`:

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
...
GITHUB_TOKEN=ghp_...
# (no GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, GITHUB_APP_PRIVATE_KEY_B64)
...
ALLOW_LEGACY_GITHUB_PAT=true
```

Console:

```
Rendered (source=primary)
Present: ... GITHUB_TOKEN=YES GITHUB_APP=no GITHUB_AUTH_MODE=legacy_transition ALLOW_LEGACY_GITHUB_PAT=YES ...
```

---

## Example runtime.env output (App complete)

When all three App keys are non-empty in SSM and written:

```env
GITHUB_APP_ID=...
GITHUB_APP_INSTALLATION_ID=...
GITHUB_APP_PRIVATE_KEY_B64=...
# ALLOW_LEGACY_GITHUB_PAT line removed if it existed
```

Console:

```
GITHUB_AUTH_MODE=github_app ALLOW_LEGACY_GITHUB_PAT=NO
```

---

## Prior audit discrepancy — why some audits said NO

**Committed HEAD (before working-tree patch)** ended at:

```bash
GITHUB_APP_ALL=no
[[ -n "$GITHUB_APP_ID_VAL" && -n "$GITHUB_APP_INSTALLATION_ID_VAL" && -n "$GITHUB_APP_PRIVATE_KEY_B64_VAL" ]] && GITHUB_APP_ALL=YES
echo "Present: ... GITHUB_APP=$GITHUB_APP_ALL ..."
```

That version:

- Did **not** write `ALLOW_LEGACY_GITHUB_PAT`
- Only reported whether App vars were loaded from SSM into shell variables
- Relied on operators to set `ALLOW_LEGACY_GITHUB_PAT=true` manually

**Audits that inspected committed/main or pre-patch code were correct for that revision.**

**Audits that assumed PR #32 + uncommitted render patch behavior were correct for the working tree.**

The behavior is **new in the current uncommitted diff** (lines 254–282), not in committed `main`.

---

## Operational implication

Once this render patch is deployed **and** runs from `/home/ubuntu/crypto-2.0` (path fix required), every CI deploy that calls `render_runtime_env.sh` will keep legacy PAT workflows working until GitHub App SSM parameters exist — without manual `ALLOW_LEGACY_GITHUB_PAT` injection.
