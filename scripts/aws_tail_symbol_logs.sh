#!/usr/bin/env bash
# Print a window of backend container logs around the last line matching SYMBOL.
# Resolves the real log path via docker inspect (container name or short ID works).
#
# Usage (on EC2 host):
#   ./scripts/aws_tail_symbol_logs.sh <container> <SYMBOL>
#   ./scripts/aws_tail_symbol_logs.sh backend-aws DOT_USDT
#   ./scripts/aws_tail_symbol_logs.sh abc123 ETH_USDT
#
# If the log file is not readable (permission denied), run with sudo:
#   sudo ./scripts/aws_tail_symbol_logs.sh backend-aws DOT_USDT
#
# Optional: CONTEXT_LINES=50 ./scripts/aws_tail_symbol_logs.sh backend-aws DOT_USDT

set -e
CONTAINER="${1:?Usage: $0 <container_name_or_id> <SYMBOL>}"
SYMBOL="${2:?Usage: $0 <container_name_or_id> <SYMBOL>}"
CONTEXT_LINES="${CONTEXT_LINES:-40}"

LOG_PATH=$(docker inspect --format '{{.LogPath}}' "$CONTAINER" 2>/dev/null) || {
  echo "Failed to get LogPath for container: $CONTAINER" >&2
  echo "Check container name/id with: docker ps" >&2
  exit 1
}

if [ ! -r "$LOG_PATH" ]; then
  echo "Log file not readable: $LOG_PATH" >&2
  echo "Try: sudo $0 $CONTAINER $SYMBOL" >&2
  exit 1
fi

LAST_LINE=$(grep -n "$SYMBOL" "$LOG_PATH" 2>/dev/null | tail -1 | cut -d: -f1)
if [ -z "$LAST_LINE" ]; then
  echo "No line matching '$SYMBOL' in $LOG_PATH" >&2
  exit 1
fi

START=$((LAST_LINE - CONTEXT_LINES))
[ "$START" -lt 1 ] && START=1
END=$((LAST_LINE + CONTEXT_LINES))

echo "--- Last match for $SYMBOL at line $LAST_LINE (showing $START-$END) ---"
sed -n "${START},${END}p" "$LOG_PATH"
