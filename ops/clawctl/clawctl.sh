#!/bin/zsh
set -euo pipefail

EC2_HOST="ubuntu@YOUR_EC2_IP"
SSH_KEY="$HOME/.ssh/claw_ro_ec2"
PORT=22

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
REQ_DIR="$BASE_DIR/requests"
APP_DIR="$BASE_DIR/approved"
LOG_DIR="$BASE_DIR/logs"
JSONL_FILE="$LOG_DIR/ec2_exec.jsonl"

ts="$(date +"%Y%m%d_%H%M%S")"
req_file="$REQ_DIR/$ts.request.txt"
app_file="$APP_DIR/$ts.approved.txt"
log_file="$LOG_DIR/$ts.output.txt"

cmd="${1:-}"
if [[ -z "$cmd" ]]; then
  echo "Usage:"
  echo "./ops/clawctl/clawctl.sh \"<command>\""
  exit 1
fi

# hard deny dangerous commands (read-only runner)
deny_re='(^|[[:space:];|&`])(sudo|su|rm|mv|cp|dd|mkfs|mount|umount|chmod|chown|reboot|shutdown|poweroff|halt|kill|pkill|killall|iptables|ufw|systemctl[[:space:]]+(stop|restart|disable|mask)|service[[:space:]]+|docker[[:space:]]+(stop|kill|rm|system|compose[[:space:]]+down)|curl[[:space:]].*\|[[:space:]]*(sh|bash)|wget[[:space:]].*\|[[:space:]]*(sh|bash))([[:space:];|&`]|$)'

if echo "$cmd" | perl -0777 -ne 'exit((lc($_)=~/'"$deny_re"'/) ? 0 : 1)'; then
  echo "DENIED (dangerous command detected):"
  echo "$cmd"
  exit 2
fi

# strict allowlist (diagnostics only)
allow_re='^(ps|pstree|top|htop|uptime|uname|hostname|free|vmstat|iostat|sar|ss|netstat|lsof|dmesg|journalctl|systemctl[[:space:]]+status|cat[[:space:]]+/proc/|docker[[:space:]]+(ps|logs|inspect)|grep|awk|sed|head|tail|cut|sort|uniq|wc|find[[:space:]]+/proc|ls|stat)([[:space:]]|$)'

if ! echo "$cmd" | grep -Eqi "$allow_re"; then
  echo "NOT ALLOWED (outside read-only diagnostics scope):"
  echo "$cmd"
  exit 3
fi

echo "$cmd" > "$req_file"

echo ""
echo "Proposed command:"
echo "$cmd"
echo ""
read "answer?Type YES to execute on EC2: "

if [[ "$answer" != "YES" ]]; then
  echo "Cancelled."
  exit 0
fi

cp "$req_file" "$app_file"

AUDIT_FILE="$BASE_DIR/audit.md"
{
  echo "## $ts"
  echo "- host: $EC2_HOST"
  echo "- cmd: \`$cmd\`"
  echo ""
} >> "$AUDIT_FILE"

rc_file="$LOG_DIR/.last_rc"
{
  echo "=== EXECUTION $ts ==="
  echo "HOST: $EC2_HOST"
  echo "CMD:  $cmd"
  echo "----------------------"
  echo ""
  start_epoch="$(date +%s)"
  set +e
  ssh -i "$SSH_KEY" -p "$PORT" "$EC2_HOST" "$cmd"
  rc=$?
  set -e
  echo "$rc" > "$rc_file"
  end_epoch="$(date +%s)"
  duration="$((end_epoch - start_epoch))"
  python3 -c '
import json, sys
ts, host, cmd, rc, duration, req, app, log = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), sys.argv[6], sys.argv[7], sys.argv[8]
print(json.dumps({"ts": ts, "host": host, "cmd": cmd, "rc": rc, "duration_s": duration, "request": req, "approved": app, "log": log}))
' "$ts" "$EC2_HOST" "$cmd" "$rc" "$duration" "$req_file" "$app_file" "$log_file" >> "$JSONL_FILE"
} | tee "$log_file"

rc="$(cat "$rc_file")"
echo ""
echo "Saved output to:"
echo "$log_file"
exit "$rc"
