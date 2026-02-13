# Security Audit: check_no_inline_secrets_in_compose.sh

**Scope**: Production security control that enforces no inline secret values in compose files.  
**Files scanned**: By default, all relevant compose files in repo root: `docker-compose.yml`, `docker-compose.*.yml`, `compose*.yml`. Override with `CHECK_COMPOSE_FILE=/path` (e.g. for tests).  
**Audit type**: Adversarial; bypass attempts and strict validation.  
**Constraint**: Do not modify business logic; security audit only.

---

## 1. Findings

### A) Detection correctness

| Case | Expected | Result | Notes |
|------|----------|--------|--------|
| Quoted key `"API_KEY": example_value` | FAIL | **FAIL** | Detected. |
| Hyphenated key `API-KEY=abc` | FAIL | **PASS** | **Bypass** – see §2. |
| YAML mapping `API_KEY: example_value` | FAIL | **FAIL** | Detected. |
| List syntax `- api_key=example_value` | FAIL | **FAIL** | Detected. |
| Multiline value (key: then next line) | FAIL | **FAIL** | Detected via `resolve_val`. |
| Inline comment `KEY: ${VAR} # comment` | PASS | **PASS** | Comment stripped, ref accepted. |
| Single-quoted literal `API_KEY: 'example_value'` | FAIL | **FAIL** | Detected. |
| Double-quoted literal | FAIL | **FAIL** | Detected. |
| Unbraced `$VAR` | PASS | **PASS** | Accepted. |
| Leading/trailing whitespace around value | FAIL | **FAIL** | Normalized then detected. |
| Case-insensitivity (`api_key=example_value`) | FAIL | **FAIL** | Detected. |

### B) False-positive resistance

| Case | Expected | Result |
|------|----------|--------|
| `${VAR}` | PASS | **PASS** |
| `"${VAR}"` | PASS | **PASS** |
| `$VAR` | PASS | **PASS** |
| Full-line commented line | PASS | **PASS** |
| Allowlist `ENABLE_DIAGNOSTICS_ENDPOINTS=1` | PASS | **PASS** |
| Allowlist `pg_password` | PASS | **PASS** (when used as key) |

### C) Security properties

| Property | Status |
|----------|--------|
| Never echoes secret values | **Satisfied** – only variable names in FAIL message; `resolve_val`/`normalize_value` output used only in command substitution, not printed to user. |
| Never resolves env variables | **Satisfied** – no `docker compose config` or env expansion. |
| Never runs `docker compose config` | **Satisfied** – file read + grep/regex only. |
| Exits non-zero only on real violations | **Satisfied** except for hyphen bypass (inline literal with hyphenated key can pass). |

### D) Integration

- **deploy_aws.sh**: Runs `scripts/aws/check_no_inline_secrets_in_compose.sh` at Step 5b; on failure aborts deploy. Correct.
- **.github/workflows/no-inline-secrets.yml**: Runs the script on PR/push to `main`; no config printed. Correct.

---

## 2. Bypass attempts

### Bypass found: hyphenated secret keys

**Snippet (valid YAML, contains literal secret, avoids detection):**

```yaml
services:
  backend:
    environment:
      - API-KEY=example_value
      - DATABASE-URL=postgresql://example
      - MY-API-KEY=dummy_value
      - ADMIN-ACTIONS=allow
```

**Why it bypasses**

- Secret detection uses:
  - Exact key `database_url` (underscore).
  - Substring patterns: `api_key`, `token`, `secret`, `password`, `admin_actions`, etc. (all with **underscore**).
- Keys are normalized only to **lowercase**, not hyphen→underscore.
- So:
  - `API-KEY` → `api-key` → does **not** contain `api_key` → not treated as secret.
  - `DATABASE-URL` → `database-url` → not equal to `database_url` → not treated as secret.
  - `MY-API-KEY` → `my-api-key` → no `api_key` substring → not treated as secret.
  - `ADMIN-ACTIONS` → `admin-actions` → does **not** contain `admin_actions` → not treated as secret.

**Impact**: An attacker or mistake can commit compose with inline secrets by using hyphenated variants of the same logical keys (`API-KEY`, `DATABASE-URL`, etc.). The script passes; secrets are in the file.

**No other bypass found** for:

- Quoted keys, YAML mapping, list syntax, multiline (single continuation), block scalar `|`, inline comments, quoted refs, `$VAR`/`${VAR}`, full-line comments, allowlist, leading/trailing space, case.

---

## 3. Recommended changes

### Minimal patch (close hyphen bypass)

Treat hyphen and underscore as equivalent when deciding if a key is secret. Normalize the key for pattern matching by replacing hyphens with underscores (after lowercasing).

**In `is_secret_key`**, after computing `lower`, add:

```bash
# Treat hyphen as underscore for pattern matching (avoid API-KEY / DATABASE-URL bypass)
lower="${lower//-/_}"
```

So:

- `API-KEY` → `api_key` → contains `api_key` → secret.
- `DATABASE-URL` → `database_url` → exact match → secret.
- `ADMIN-ACTIONS` → `admin_actions` → contains `admin_actions` → secret.

**Placement**: Right after `lower="$(echo "$key" | tr '[:upper:]' '[:lower:]')"` and before the `for skip` loop. No change to allowlist logic or to how keys are reported (still report the original key name, e.g. `API-KEY`).

**Status**: This patch has been applied in `scripts/aws/check_no_inline_secrets_in_compose.sh`. Verified: `API-KEY=example_value` and `DATABASE-URL=postgresql://example` now FAIL; allowlist and repo compose still PASS.

---

## 4. Final verdict

- **Control**: Appropriate and well-integrated (deploy script + CI). Detection covers quoted keys, mapping vs list, multiline continuation, block scalar, refs, comments, allowlist; does not echo values or run `docker compose config`.
- **Bypass**: One concrete bypass: **hyphenated secret keys** (e.g. `API-KEY`, `DATABASE-URL`, `ADMIN-ACTIONS`) with inline literals can pass. Fix: normalize hyphen to underscore for secret-pattern matching only.
- **After patch**: No bypass found under the current logic; residual risk is other YAML edge cases (e.g. very deep multiline, or keys with characters outside `[A-Za-z0-9_-]` if ever used).

---

## 5. What is detected vs allowed (reference)

**Detected (script fails):**

- **Secret keys** with inline literal values: exact key `DATABASE_URL`, or any key containing (case-insensitive; hyphen treated as underscore): `token`, `secret`, `password`, `api_key`, `private`, `chat_id`, `diagnostics`, `admin_actions`. Allowlist: `ENABLE_DIAGNOSTICS_ENDPOINTS`, `pg_password`.
- **Syntax:** YAML mapping (`KEY: value`), list (`- KEY=value`, `- KEY: value`), quoted keys (`"KEY"`), multiline value (key then indented next line).
- **Optional** (`DETECT_SECRET_LIKE_VALUES=1`, off by default): any env assignment whose value looks secret-like (for example, contains `postgresql://` or `postgres://`, contains `BEGIN ... KEY` markers, has a JWT-like prefix, or is base64-ish length ≥32) even if the key name is not in the secret list. Only applied to literal values (not `${VAR}` or `$VAR`). Report as KEY@FILE (or UNKNOWN_KEY@FILE if key is not available). Values are never printed.

**Allowed (script passes):**

- `${VAR}`, `"${VAR}"`, `'${VAR}'`, `$VAR` (variable references).
- Full-line comments (lines that are only whitespace and `#...`).
- Allowlist keys: `ENABLE_DIAGNOSTICS_ENDPOINTS`, `pg_password`.

**Hyphen/underscore normalization:** Key names are normalized so that `-` is treated as `_` before matching (e.g. `API-KEY` matches the `api_key` pattern).

**How to extend patterns safely:**

- **New secret key pattern:** Add a word to `SECRET_PATTERNS` in the script (case-insensitive; hyphen and underscore are equivalent for matching). Do not add keys that are feature flags or non-secret (add those to `SKIP_KEYS` if they appear in compose).
- **New secret-like value pattern:** When `DETECT_SECRET_LIKE_VALUES=1`, extend `looks_like_secret_value()` with additional checks. Never echo the value; only use it for a boolean decision and report key + file.

---

## 6. Confidence level

**High** (after applying the recommended patch; regression tests in `tests/security/test_inline_secrets_checker.sh` guard against weakening)

- The only bypass found (hyphenated keys) is closed by normalizing hyphen→underscore for pattern matching. Repo compose and allowlist unchanged. Residual risk: YAML edge cases (e.g. keys with characters outside `[A-Za-z0-9_-]`, or multi-line block scalars beyond the first continuation line) are not fully exercised; confidence remains High for typical compose usage.
