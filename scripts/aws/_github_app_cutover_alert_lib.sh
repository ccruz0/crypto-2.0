#!/usr/bin/env bash
# Shared helpers for GitHub App cutover alert classification.
# Sourced by run_github_app_cutover_monitor_with_alerts.sh and tests.
# Never prints secret values.

# Extract bullet lines under "Failures:" from monitor output.
extract_monitor_failures() {
  local out="$1"
  echo "$out" | awk '
    /^Failures:/ { in_fail=1; next }
    in_fail && /^[[:space:]]*- / { sub(/^[[:space:]]*- /, ""); print; next }
    in_fail && NF == 0 { exit }
    in_fail && /^[A-Za-z]|EXCHANGE_CREDENTIAL|^GITHUB_APP/ { exit }
  '
}

# Classify: TRANSIENT | AUTH | OTHER
# TRANSIENT = cutover OK + only restart/probe-style failures.
classify_failure() {
  local auth_mode="$1"
  local cutover="$2"
  local mint_ok="$3"
  local failures_text="$4"

  if [[ "$auth_mode" != "github_app" || "$cutover" != "YES" || "$mint_ok" != "yes" ]]; then
    echo "AUTH"
    return 0
  fi

  local line non_transient=no
  if [[ -z "${failures_text// }" ]]; then
    echo "OTHER"
    return 0
  fi

  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    case "$line" in
      *"health starting"*|*"ping_fast not ok"*|*"health/ready not ready"*|*"not running"*|*"unhealthy"*|*"health=starting"*)
        ;;
      *"logs contain GitHub auth warnings"*)
        # Cutover mint already OK; usually diagnostic noise or stale log lines.
        ;;
      *"auth_mode is not github_app"*|*"CUTOVER_READY is not YES"*|*"live token mint not confirmed"*)
        echo "AUTH"
        return 0
        ;;
      *)
        non_transient=yes
        ;;
    esac
  done <<< "$failures_text"

  if [[ "$non_transient" == "yes" ]]; then
    echo "OTHER"
  else
    echo "TRANSIENT"
  fi
}

remedy_for_class() {
  local class="$1"
  case "$class" in
    TRANSIENT)
      cat <<'EOF'
Containers were restarting or not ready. Recheck already ran once.
If this persists: check HostSwapHigh / docker restarts, then:
  docker compose --profile aws ps
  docker compose --profile aws logs backend-aws --tail=80
EOF
      ;;
    AUTH)
      cat <<'EOF'
GitHub App auth is broken or not cut over.
On PROD:
  bash scripts/aws/verify_github_app_cutover_ready.sh
  bash scripts/aws/monitor_github_app_cutover.sh
Check SSM params under /automated-trading-platform/prod/github_app/
and container env (GITHUB_APP_ID / INSTALLATION_ID / PRIVATE_KEY_B64).
EOF
      ;;
    *)
      cat <<'EOF'
Investigate on PROD:
  cd /home/ubuntu/crypto-2.0
  bash scripts/aws/monitor_github_app_cutover.sh
  tail -120 logs/github_app_monitor_latest.log
EOF
      ;;
  esac
}
