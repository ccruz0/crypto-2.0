#!/usr/bin/env bash
set -euo pipefail

cd ~/automated-trading-platform

HOURS=12
LIMIT=500
SERVICE_BACKEND=backend-aws
SERVICE_DB=db
BACKEND_PORT=8000

get_env_value() {
  local name="$1"
  local value=""
  for file in .env .env.aws .env.local; do
    if [ -f "$file" ]; then
      local line=""
      if command -v rg >/dev/null 2>&1; then
        line=$(rg -n "^${name}=" "$file" | head -n 1 || true)
      else
        line=$(grep -E "^${name}=" "$file" | head -n 1 || true)
      fi
      if [ -n "$line" ]; then
        value="${line#${name}=}"
        value="${value%$'\r'}"
        value="${value%\"}"
        value="${value#\"}"
        value="${value%\'}"
        value="${value#\'}"
        break
      fi
    fi
  done
  printf "%s" "$value"
}

POSTGRES_USER=${POSTGRES_USER:-$(get_env_value POSTGRES_USER)}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-$(get_env_value POSTGRES_PASSWORD)}
POSTGRES_DB=${POSTGRES_DB:-$(get_env_value POSTGRES_DB)}

POSTGRES_USER=${POSTGRES_USER:-trader}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-traderpass}
POSTGRES_DB=${POSTGRES_DB:-atp}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hours)
      HOURS="$2"
      shift 2
      ;;
    --limit)
      LIMIT="$2"
      shift 2
      ;;
    --service-backend)
      SERVICE_BACKEND="$2"
      shift 2
      ;;
    --service-db)
      SERVICE_DB="$2"
      shift 2
      ;;
    --backend-port)
      BACKEND_PORT="$2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

compose_cmd=(docker compose --profile aws)

${compose_cmd[@]} ps

# Check backend logs for order_intents table readiness
if ${compose_cmd[@]} logs --tail 300 "$SERVICE_BACKEND" | (command -v rg >/dev/null 2>&1 && rg -q "\[BOOT\] order_intents table OK" || grep -q "\[BOOT\] order_intents table OK"); then
  boot_check="ok"
else
  boot_check="missing"
fi

# Call diagnostics endpoint from inside backend container
${compose_cmd[@]} exec -T "$SERVICE_BACKEND" sh -c "\
  if command -v curl >/dev/null 2>&1; then \
    curl -s http://localhost:${BACKEND_PORT}/api/diagnostics/recent-signals?hours=${HOURS}\&limit=${LIMIT}; \
  elif command -v python3 >/dev/null 2>&1; then \
    python3 -c \"import urllib.request; url='http://localhost:${BACKEND_PORT}/api/diagnostics/recent-signals?hours=${HOURS}&limit=${LIMIT}'; print(urllib.request.urlopen(url, timeout=10).read().decode())\"; \
  else \
    echo '{}'; \
  fi" > /tmp/recent-signals.json

if [ ! -s /tmp/recent-signals.json ]; then
  echo "Diagnostics endpoint returned empty response" >&2
  exit 1
fi

# Parse diagnostics JSON via python3 (no jq dependency)
read -r diag_pass diag_missing_intent diag_null_decisions diag_failed_without_telegram diag_violations diag_non_terminal diag_duplicate <<EOF
$(python3 - <<'PY'
import json
path = "/tmp/recent-signals.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
counts = data.get("counts", {})
violations = data.get("violations", [])
print(
    str(bool(data.get("pass"))),
    str(int(counts.get("missing_intent", 0))),
    str(int(counts.get("null_decisions", 0))),
    str(int(counts.get("failed_without_telegram", 0))),
    str(len(violations)),
    str(int(counts.get("non_terminal_intent", 0))),
    str(int(counts.get("duplicate_intent", 0))),
)
PY
)
EOF

# Run SQL verification queries
sql_output=$(${compose_cmd[@]} exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" "$SERVICE_DB" \
  psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -A -v hours="$HOURS" -v limit="$LIMIT" < scripts/verify_invariant.sql)

sent_signals=0
missing_intent=0
null_decisions=0
failed_without_telegram=0
status_lines=()

while IFS= read -r line; do
  case "$line" in
    Q1_sent_signals=*) sent_signals="${line#Q1_sent_signals=}" ;;
    Q2_missing_intent=*) missing_intent="${line#Q2_missing_intent=}" ;;
    Q4_null_decisions=*) null_decisions="${line#Q4_null_decisions=}" ;;
    Q5_failed_without_telegram=*) failed_without_telegram="${line#Q5_failed_without_telegram=}" ;;
    Q3_status_*) status_lines+=("${line#Q3_status_}") ;;
  esac
done <<< "$sql_output"

# Print compact report
printf "\nInvariant Verification Report (last %sh, limit=%s)\n" "$HOURS" "$LIMIT"
printf "- boot_check: %s\n" "$boot_check"
printf "- sent_signals: %s\n" "$sent_signals"
printf "- with_intent: %s | missing_intent: %s\n" "$((sent_signals - missing_intent))" "$missing_intent"
printf "- null_decisions: %s\n" "$null_decisions"
printf "- order_intents statuses: %s\n" "${status_lines[*]:-none}"
printf "- failed_without_telegram: %s\n" "$failed_without_telegram"
printf "- diagnostics pass: %s | missing_intent: %s | null_decisions: %s | failed_without_telegram: %s | duplicate_intent: %s | non_terminal_intent: %s | violations: %s\n" \
  "$diag_pass" "$diag_missing_intent" "$diag_null_decisions" "$diag_failed_without_telegram" "$diag_duplicate" "$diag_non_terminal" "$diag_violations"

if [ "$diag_violations" -gt 0 ]; then
  printf "\nTop 20 violations (from diagnostics):\n"
  python3 - <<'PY'
import json
path = "/tmp/recent-signals.json"
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
violations = data.get("violations", [])[:20]
for v in violations:
    vid = v.get("id") or v.get("signal_id")
    vtype = v.get("violation_type") or v.get("violation")
    details = v.get("details") or {k: v.get(k) for k in ("message", "order_intent_id") if v.get(k) is not None}
    print(f"- id={vid} type={vtype} details={details}")
PY
fi

# Exit code logic
exit_code=0
if [ "$boot_check" != "ok" ]; then exit_code=1; fi
if [ "$missing_intent" -gt 0 ] || [ "$null_decisions" -gt 0 ] || [ "$failed_without_telegram" -gt 0 ]; then exit_code=1; fi
if [ "$diag_pass" != "True" ]; then exit_code=1; fi
if [ "$diag_duplicate" -gt 0 ] || [ "$diag_non_terminal" -gt 0 ]; then exit_code=1; fi

exit "$exit_code"
