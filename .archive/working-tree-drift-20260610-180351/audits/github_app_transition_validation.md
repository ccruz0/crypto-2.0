# GitHub App Transition Logic Validation

**Date:** 2026-06-09  
**Script:** `scripts/aws/render_runtime_env.sh` (uncommitted working tree)  
**Question:** When `GITHUB_TOKEN` exists and `GITHUB_APP_*` is missing, is `ALLOW_LEGACY_GITHUB_PAT=true` written?

---

## Answer: YES

Under production-like conditions (PAT in SSM, no App SSM parameters), the render script writes `ALLOW_LEGACY_GITHUB_PAT=true` to `secrets/runtime.env`.

---

## Exact conditions

### Preconditions (earlier in script)

| Step | Lines | Behavior |
|------|-------|----------|
| Fetch SSM | 84–90 | `GITHUB_TOKEN` from `/automated-trading-platform/prod/github_token`; App keys empty if absent in SSM |
| Write initial block | 185–188 | `GITHUB_TOKEN` written if non-empty; App keys written only if non-empty |
| `.env.aws` override | 191–216 | May append/override App keys when `source=primary` |

### Detection block (lines 254–261)

Runs **after** all merges to `$RUNTIME_ENV`:

```bash
GITHUB_APP_ALL=no
grep -q '^GITHUB_APP_ID=' "$RUNTIME_ENV" \
  && grep -q '^GITHUB_APP_INSTALLATION_ID=' "$RUNTIME_ENV" \
  && grep -q '^GITHUB_APP_PRIVATE_KEY_B64=' "$RUNTIME_ENV" \
  && GITHUB_APP_ALL=YES

HAS_GITHUB_PAT=no
grep -q '^GITHUB_TOKEN=' "$RUNTIME_ENV" && HAS_GITHUB_PAT=YES
```

**Important:** Detection uses **key presence in file**, not non-empty values.

### Write logic (lines 262–279)

| Condition | `GITHUB_AUTH_MODE` | `ALLOW_LEGACY_GITHUB_PAT` action |
|-----------|-------------------|----------------------------------|
| `GITHUB_APP_ALL == YES` | `github_app` | **Delete** line if present |
| `HAS_GITHUB_PAT == YES` (App incomplete) | `legacy_transition` | **Set** `ALLOW_LEGACY_GITHUB_PAT=true` (sed or append) |
| Neither | `none` | **Delete** line if present |

Legacy transition write (lines 268–274):

```bash
elif [[ "$HAS_GITHUB_PAT" == "YES" ]]; then
  GITHUB_AUTH_MODE=legacy_transition
  # sed replace or printf "ALLOW_LEGACY_GITHUB_PAT=true\n" >> "$RUNTIME_ENV"
```

---

## Exact runtime.env output (PAT-only, current PROD)

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

## Exact runtime.env output (App complete — future state)

When all three App keys exist in SSM and are written:

```env
GITHUB_APP_ID=...
GITHUB_APP_INSTALLATION_ID=...
GITHUB_APP_PRIVATE_KEY_B64=...
# ALLOW_LEGACY_GITHUB_PAT removed
```

Console: `GITHUB_AUTH_MODE=github_app ALLOW_LEGACY_GITHUB_PAT=NO`

---

## Failure modes

| Scenario | Result | Impact |
|----------|--------|--------|
| PAT in SSM, App absent | `ALLOW_LEGACY=true` written | **Intended** — backend starts, PAT APIs work |
| PAT absent, App absent | `ALLOW_LEGACY` removed, mode `none` | Backend **fails startup** on AWS (`factory.py`) |
| PAT present, App partial (1–2 keys) | Treated as App incomplete if all 3 grep fail; if partial keys written, `GITHUB_APP_ALL` may be YES with empty values | Edge case: empty App keys still count as "present" |
| `render_runtime_env.sh` not run on deploy | Existing `runtime.env` kept; may lack `ALLOW_LEGACY` | Backend restart may **fail** if PR #32 active and flag missing |
| `render_runtime_env.sh` fails (workflow `\|\| true`) | Old env retained | Same as above until manual render |
| App keys added later | Next render removes `ALLOW_LEGACY` | PAT blocked unless App mint works |
| Revert this commit | No auto-`ALLOW_LEGACY`; manual flag required | Rollback to pre-transition behavior |

---

## Backend coupling (PR #32)

`github_api_token_configured()` returns true when:

```python
legacy_pat_allowed() and GITHUB_TOKEN  # OR usable GitHub App
```

Without this render patch + `ALLOW_LEGACY_GITHUB_PAT=true`, AWS backend with PAT-only raises `RuntimeError` at startup.

---

## Rollback

1. Revert transition commit.
2. Manually set `ALLOW_LEGACY_GITHUB_PAT=true` in `secrets/runtime.env` on EC2, **or** accept backend startup failure until App provisioned.
3. Re-run `docker compose --profile aws up -d --force-recreate backend-aws`.

No SSM or GitHub App deletion required for rollback.

---

## Validation verdict

**Logic is correct** for stated goal: PAT + missing App → `ALLOW_LEGACY_GITHUB_PAT=true`.

**Depends on:** PR #33 merged (render runs in `/home/ubuntu/crypto-2.0`) and deploy calling `render_runtime_env.sh`.
