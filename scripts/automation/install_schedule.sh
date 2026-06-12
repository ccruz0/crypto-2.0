#!/usr/bin/env bash
# Install Jarvis production automation schedules (systemd timers or crontab).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="${JARVIS_AUTOMATION_PYTHON:-python3}"
MODE="${1:-systemd}"
UNIT_DIR="$REPO_ROOT/scripts/automation/systemd"
ENV_SNIPPET="# Jarvis automations (installed $(date -u +%Y-%m-%dT%H:%M:%SZ))
JARVIS_AUTOMATIONS_ENABLED=true
OPENCLAW_PUBLIC_ALLOWED=false
JARVIS_AUTOMATION_STATE_DIR=/var/lib/atp/jarvis_automations
JARVIS_ALERT_COOLDOWN_MINUTES=30"

usage() {
  cat <<EOF
Usage: $0 [systemd|cron|print-cron]

Install read-only Jarvis automations on this host.

  systemd     Copy systemd units to /etc/systemd/system and enable timers (default)
  cron        Append crontab entries (does not remove existing entries)
  print-cron  Print crontab lines only

Prerequisites:
  - JARVIS_AUTOMATIONS_ENABLED=true in secrets/runtime.env or environment
  - Telegram chat/token configured (TELEGRAM_CHAT_ID_OPS or TELEGRAM_CHAT_ID)
  - DATABASE_URL for task auditor / daily report Jarvis stats

Repo: $REPO_ROOT
EOF
}

render_unit() {
  local file="$1"
  sed "s|@REPO_ROOT@|$REPO_ROOT|g; s|@PYTHON@|$PYTHON|g" "$file"
}

install_systemd() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "systemd install requires root (sudo $0 systemd)" >&2
    exit 1
  fi
  mkdir -p /var/lib/atp/jarvis_automations /var/log/atp
  for f in "$UNIT_DIR"/*.service "$UNIT_DIR"/*.timer; do
    [ -f "$f" ] || continue
    base="$(basename "$f")"
    render_unit "$f" > "/etc/systemd/system/$base"
    echo "installed /etc/systemd/system/$base"
  done
  systemctl daemon-reload
  systemctl enable --now jarvis-health-check.timer
  systemctl enable --now jarvis-daily-report.timer
  systemctl enable --now jarvis-task-auditor.timer
  systemctl enable --now jarvis-openclaw-guard.timer
  echo ""
  echo "Timers:"
  systemctl list-timers 'jarvis-*' --no-pager || true
  echo ""
  echo "Add to secrets/runtime.env if missing:"
  echo "$ENV_SNIPPET"
}

print_cron() {
  cat <<EOF
# Jarvis production automations ($REPO_ROOT)
*/5 * * * * cd $REPO_ROOT && $PYTHON scripts/automation/health_check.py >> /var/log/atp/jarvis-health-check.log 2>&1
0 7 * * * cd $REPO_ROOT && $PYTHON scripts/automation/daily_report.py >> /var/log/atp/jarvis-daily-report.log 2>&1
15 * * * * cd $REPO_ROOT && $PYTHON scripts/automation/task_auditor.py >> /var/log/atp/jarvis-task-auditor.log 2>&1
0 */6 * * * cd $REPO_ROOT && $PYTHON scripts/automation/openclaw_guard.py >> /var/log/atp/jarvis-openclaw-guard.log 2>&1
EOF
}

install_cron() {
  mkdir -p /var/log/atp /var/lib/atp/jarvis_automations
  tmp="$(mktemp)"
  print_cron > "$tmp"
  echo "Appending Jarvis cron entries (review before confirming):"
  cat "$tmp"
  read -r -p "Append to current user crontab? [y/N] " ans
  if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
    (crontab -l 2>/dev/null || true; echo ""; cat "$tmp") | crontab -
    echo "crontab updated"
  else
    echo "skipped crontab update"
  fi
  rm -f "$tmp"
  echo ""
  echo "Add to secrets/runtime.env if missing:"
  echo "$ENV_SNIPPET"
}

case "$MODE" in
  systemd) install_systemd ;;
  cron) install_cron ;;
  print-cron) print_cron ;;
  -h|--help) usage ;;
  *) echo "unknown mode: $MODE" >&2; usage; exit 1 ;;
esac
