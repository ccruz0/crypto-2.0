#!/usr/bin/env bash
# Weekly sanity summarizer: stability trends from health_snapshots.log.
# Usage: sudo tail -n 2000 /var/log/atp/health_snapshots.log | jq -s '...'
# Or run this script (reads last N lines, default 2000).
set -euo pipefail

LOG="${ATP_HEALTH_SNAPSHOT_LOG:-/var/log/atp/health_snapshots.log}"
N="${1:-2000}"

if [ ! -r "$LOG" ]; then
  echo "Cannot read $LOG (try sudo)" >&2
  exit 1
fi

# Normalize disk_pct to number (old log lines may have string)
tail -n "$N" "$LOG" | jq -s '
  def to_num: if type == "number" then . else (tonumber? // 0) end;
  {
    total: length,
    by_verify: (group_by(.verify_label) | map({label: .[0].verify_label, n: length})),
    by_global_status: (group_by(.global_status) | map({status: .[0].global_status, n: length})),
    by_market_data: (group_by(.market_data_status) | map({status: .[0].market_data_status, n: length})),
    by_market_updater: (group_by(.market_updater_status) | map({status: .[0].market_updater_status, n: length})),
    avg_disk_pct: ((map(.disk_pct | to_num) | add) / length),
    max_disk_pct: (map(.disk_pct | to_num) | max)
  }
'
