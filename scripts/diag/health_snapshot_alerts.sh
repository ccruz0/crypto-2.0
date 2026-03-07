#!/usr/bin/env bash
# Quick "are we burning?" queries on health_snapshots.log.
# Usage: sudo bash scripts/diag/health_snapshot_alerts.sh
# Or paste the jq/awk one-liners from this script.
set -euo pipefail

LOG="${ATP_HEALTH_SNAPSHOT_LOG:-/var/log/atp/health_snapshots.log}"
N="${1:-5000}"

if [ ! -r "$LOG" ]; then
  echo "Cannot read $LOG (try sudo)" >&2
  exit 1
fi

echo "=== Last ${N} lines: FAIL count ==="
tail -n "$N" "$LOG" | jq -s '[ .[] | select(.severity=="FAIL") ] | length'

echo ""
echo "=== Last ${N} lines: worst consecutive FAIL streak ==="
tail -n "$N" "$LOG" | jq -s -r '.[].severity' | awk '
  { if($1=="FAIL"){c++; if(c>m)m=c} else c=0 }
  END{print m+0}'

echo ""
echo "(If streak > 3, consider a Telegram ping.)"
