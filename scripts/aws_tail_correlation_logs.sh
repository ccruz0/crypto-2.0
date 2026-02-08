#!/usr/bin/env bash
# Print a window of backend container logs around the last line matching a correlation_id.
# Resolves the real log path via docker inspect (container name or short ID works).
#
# Usage (on EC2 host):
#   ./scripts/aws_tail_correlation_logs.sh <container> <correlation_id>
#   ./scripts/aws_tail_correlation_logs.sh backend-aws a1b2c3d4-e5f6-7890-abcd-ef1234567890
#
# If the log file is not readable (permission denied), run with sudo:
#   sudo ./scripts/aws_tail_correlation_logs.sh backend-aws <correlation_id>
#
# Optional: CONTEXT_LINES=80 ./scripts/aws_tail_correlation_logs.sh backend-aws <correlation_id>

set -e
CONTAINER="${1:?Usage: $0 <container_name_or_id> <correlation_id>}"
CORRELATION_ID="${2:?Usage: $0 <container_name_or_id> <correlation_id>}"
CONTEXT_LINES="${CONTEXT_LINES:-60}"

LOG_PATH=$(docker inspect --format '{{.LogPath}}' "$CONTAINER" 2>/dev/null) || {
  echo "Failed to get LogPath for container: $CONTAINER" >&2
  echo "Check container name/id with: docker ps" >&2
  exit 1
}

if [ ! -r "$LOG_PATH" ]; then
  echo "Log file not readable: $LOG_PATH" >&2
  echo "Try: sudo $0 $CONTAINER $CORRELATION_ID" >&2
  exit 1
fi

LAST_LINE=$(grep -n "$CORRELATION_ID" "$LOG_PATH" 2>/dev/null | tail -1 | cut -d: -f1)
if [ -z "$LAST_LINE" ]; then
  echo "No line matching correlation_id '$CORRELATION_ID' in $LOG_PATH" >&2
  exit 1
fi

START=$((LAST_LINE - CONTEXT_LINES))
[ "$START" -lt 1 ] && START=1
END=$((LAST_LINE + CONTEXT_LINES))

echo "--- Last match for correlation_id at line $LAST_LINE (showing $START-$END) ---"
sed -n "${START},${END}p" "$LOG_PATH"
