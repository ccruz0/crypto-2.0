#!/bin/zsh
set -euo pipefail

EC2_HOST="ubuntu@YOUR_EC2_IP"
SSH_KEY="$HOME/.ssh/claw_ro_ec2"
PORT=22

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
REQ_DIR="$BASE_DIR/requests"
APP_DIR="$BASE_DIR/approved"
LOG_DIR="$BASE_DIR/logs"

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

{
  echo "=== EXECUTION $ts ==="
  echo "HOST: $EC2_HOST"
  echo "CMD:  $cmd"
  echo "----------------------"
  echo ""
  ssh -i "$SSH_KEY" -p "$PORT" "$EC2_HOST" "$cmd"
} | tee "$log_file"

echo ""
echo "Saved output to:"
echo "$log_file"
