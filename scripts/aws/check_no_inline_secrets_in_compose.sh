#!/usr/bin/env bash
# Inline-secrets guard for compose files.
# Current behavior: Scans KEY: / "KEY": (YAML) and - KEY= / - "KEY"= (env list).
# Secret keys: exact DATABASE_URL or key containing (case-insensitive, '-' treated as '_'):
#   token, secret, password, api_key, private, chat_id, diagnostics, admin_actions.
# Allowlist: ENABLE_DIAGNOSTICS_ENDPOINTS, pg_password.
# Safe values: ${VAR}, "${VAR}", $VAR; full-line comments ignored.
# Gaps closed: hyphen normalization; multi-file scan; optional secret-like value detection.
# Output: names and file paths only; never values. Never runs docker compose config.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Override: scan only this file (used by tests). If set, COMPOSE_FILES is built from it.
CHECK_COMPOSE_FILE="${CHECK_COMPOSE_FILE:-}"

# Optional: also fail if any env value looks like a secret (sk-, postgres://, etc.). Never prints values.
DETECT_SECRET_LIKE_VALUES="${DETECT_SECRET_LIKE_VALUES:-0}"

SECRET_PATTERNS=( token secret password api_key private chat_id diagnostics admin_actions )
EXACT_SECRET_NAME="database_url"
SKIP_KEYS=( ENABLE_DIAGNOSTICS_ENDPOINTS pg_password )

# Global: violations as "KEY|FILE"
VIOLATIONS=()

is_secret_key() {
  local key="$1"
  local lower
  lower="$(echo "$key" | tr '[:upper:]' '[:lower:]')"
  lower="${lower//-/_}"
  for skip in "${SKIP_KEYS[@]}"; do
    if [[ "$(echo "$skip" | tr '[:upper:]' '[:lower:]')" == "$lower" ]]; then
      return 1
    fi
  done
  if [[ "$lower" == "$EXACT_SECRET_NAME" ]]; then
    return 0
  fi
  for p in "${SECRET_PATTERNS[@]}"; do
    if [[ "$lower" == *"$p"* ]]; then
      return 0
    fi
  done
  return 1
}

normalize_value() {
  local v="$1"
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  if [[ "$v" =~ ^(.*)[[:space:]]+# ]]; then
    v="${BASH_REMATCH[1]}"
    v="${v%"${v##*[![:space:]]}"}"
  fi
  echo "$v"
}

is_value_reference() {
  local val
  val="$(normalize_value "$1")"
  if [[ ${#val} -ge 2 && "$val" == \"*\" ]]; then
    val="${val:1:${#val}-2}"
  fi
  if [[ ${#val} -ge 2 && "$val" == \'*\' ]]; then
    val="${val:1:${#val}-2}"
  fi
  val="$(normalize_value "$val")"
  [[ "$val" =~ ^[[:space:]]*\$\{ ]] && return 0
  [[ "$val" =~ ^[[:space:]]*\$[A-Za-z_][A-Za-z0-9_]*$ ]] && return 0
  return 1
}

# Returns 0 if value looks like a secret (pattern-based). Never prints the value.
looks_like_secret_value() {
  local val
  val="$(normalize_value "$1")"
  if [[ ${#val} -ge 2 && "$val" == \"*\" ]]; then
    val="${val:1:${#val}-2}"
  fi
  if [[ ${#val} -ge 2 && "$val" == \'*\' ]]; then
    val="${val:1:${#val}-2}"
  fi
  val="$(normalize_value "$val")"
  # Reject refs
  [[ "$val" =~ ^[[:space:]]*\$\{ ]] && return 1
  [[ "$val" =~ ^[[:space:]]*\$[A-Za-z_][A-Za-z0-9_]*$ ]] && return 1
  local lower
  lower="$(echo "$val" | tr '[:upper:]' '[:lower:]')"
  # sk- prefix (e.g. Stripe, API keys)
  [[ "$lower" == sk-* ]] && return 0
  # postgres(ql)://
  [[ "$lower" == *"postgresql://"* ]] && return 0
  [[ "$lower" == *"postgres://"* ]] && return 0
  # PEM
  [[ "$lower" == *"-----begin"* ]] && return 0
  # JWT-like
  [[ "$val" == eyJ* ]] && return 0
  # Long base64-ish: >= 32 chars, mostly [A-Za-z0-9+/=_-]
  if [[ ${#val} -ge 32 ]]; then
    local stripped
    stripped="$(echo -n "$val" | tr -d 'A-Za-z0-9+/=_-' || true)"
    [[ ${#stripped} -le 2 ]] && return 0
  fi
  return 1
}

# Scan one compose file; append to VIOLATIONS as "KEY|FILE" (never print value).
scan_one_file() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    echo "ERROR: compose file not found: $file" >&2
    exit 1
  fi
  local CONTENT LINES N line key val i next curr_indent next_indent
  CONTENT="$(grep -v -E '^[[:space:]]*#' "$file" || true)"
  LINES=()
  while IFS= read -r line; do
    LINES+=("$line")
  done <<< "$CONTENT"
  N=${#LINES[@]}

  resolve_val() {
    local val="$1" idx="$2" current_line="$3"
    [[ "$val" != "" ]] && { echo "$val"; return; }
    (( idx + 1 >= N )) && { echo ""; return; }
    next="${LINES[idx+1]}"
    curr_indent="${current_line%%[^[:space:]]*}"
    next_indent="${next%%[^[:space:]]*}"
    if [[ "$next" =~ ^[[:space:]]+ && ${#next_indent} -gt ${#curr_indent} ]]; then
      echo "${next#"$next_indent"}"
    else
      echo ""
    fi
  }

  i=0
  while (( i < N )); do
    line="${LINES[i]}"
    if [[ "$line" =~ ^[[:space:]]+-[[:space:]]+[\"\']?([A-Za-z0-9_-]+)[\"\']?[[:space:]]*=[[:space:]]*(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      val="$(resolve_val "${BASH_REMATCH[2]}" "$i" "$line")"
      [[ "${BASH_REMATCH[2]}" == "" && "$val" != "" && $(( i + 1 )) -lt $N ]] && (( i++ )) || true
      if ! is_value_reference "$val"; then
        if is_secret_key "$key"; then
          VIOLATIONS+=("$key|$file")
        elif [[ "$DETECT_SECRET_LIKE_VALUES" == "1" ]] && looks_like_secret_value "$val"; then
          VIOLATIONS+=("$key|$file")
        fi
      fi
    fi
    (( i++ )) || true
  done

  i=0
  while (( i < N )); do
    line="${LINES[i]}"
    if [[ "$line" =~ ^[[:space:]]+-[[:space:]]+[\"\']?([A-Za-z0-9_-]+)[\"\']?[[:space:]]*:[[:space:]]*(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      val="$(resolve_val "${BASH_REMATCH[2]}" "$i" "$line")"
      [[ "${BASH_REMATCH[2]}" == "" && "$val" != "" && $(( i + 1 )) -lt $N ]] && (( i++ )) || true
      if ! is_value_reference "$val"; then
        if is_secret_key "$key"; then
          VIOLATIONS+=("$key|$file")
        elif [[ "$DETECT_SECRET_LIKE_VALUES" == "1" ]] && looks_like_secret_value "$val"; then
          VIOLATIONS+=("$key|$file")
        fi
      fi
    fi
    (( i++ )) || true
  done

  i=0
  while (( i < N )); do
    line="${LINES[i]}"
    if [[ "$line" =~ ^[[:space:]]+[\"\']?([A-Za-z0-9_-]+)[\"\']?[[:space:]]*:[[:space:]]*(.*)$ ]]; then
      key="${BASH_REMATCH[1]}"
      val="$(resolve_val "${BASH_REMATCH[2]}" "$i" "$line")"
      [[ "${BASH_REMATCH[2]}" == "" && "$val" != "" && $(( i + 1 )) -lt $N ]] && (( i++ )) || true
      if ! is_value_reference "$val"; then
        if is_secret_key "$key"; then
          VIOLATIONS+=("$key|$file")
        elif [[ "$DETECT_SECRET_LIKE_VALUES" == "1" ]] && looks_like_secret_value "$val"; then
          VIOLATIONS+=("$key|$file")
        fi
      fi
    fi
    (( i++ )) || true
  done
}

# Discover compose files: CHECK_COMPOSE_FILE or docker-compose.yml + docker-compose.*.yml + compose*.yml
COMPOSE_FILES=()
if [[ -n "$CHECK_COMPOSE_FILE" ]]; then
  COMPOSE_FILES=("$CHECK_COMPOSE_FILE")
else
  [[ -f "$ROOT/docker-compose.yml" ]] && COMPOSE_FILES+=("$ROOT/docker-compose.yml")
  for f in "$ROOT"/docker-compose.*.yml; do
    [[ -f "$f" ]] && COMPOSE_FILES+=("$f")
  done
  for f in "$ROOT"/compose*.yml; do
    [[ -f "$f" ]] && COMPOSE_FILES+=("$f")
  done
fi

if (( ${#COMPOSE_FILES[@]} == 0 )); then
  echo "PASS: no compose files found to scan"
  exit 0
fi

VIOLATIONS=()
for f in "${COMPOSE_FILES[@]}"; do
  scan_one_file "$f"
done

if (( ${#VIOLATIONS[@]} > 0 )); then
  # Dedupe by KEY|FILE; output KEY@FILE only (no values, no line content)
  SEEN=()
  for entry in "${VIOLATIONS[@]}"; do
    if [[ " ${SEEN[*]:-} " != *" $entry "* ]]; then
      SEEN+=("$entry")
    fi
  done
  echo "FAIL: inline secret variables detected:" >&2
  for entry in "${SEEN[@]}"; do
    key="${entry%%|*}"
    path="${entry#*|}"
    echo "  ${key}@${path}" >&2
  done
  echo "Move these to env_file (e.g. secrets/runtime.env, .env.aws) only." >&2
  exit 1
fi

echo "PASS: no inline secrets found"
