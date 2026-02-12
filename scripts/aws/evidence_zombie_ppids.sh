#!/usr/bin/env bash
# Step A — Evidence: map zombie PPIDs to parent owners (run on EC2 host).
# No secrets. Output is paste-friendly for runbook decision.
# Usage: cd /home/ubuntu/automated-trading-platform && bash scripts/aws/evidence_zombie_ppids.sh
set -euo pipefail

echo "=== Zombie list (first 60) ==="
ps -eo stat,ppid,pid,cmd 2>/dev/null | awk '$1 ~ /Z/ {print}' | head -60 || echo "(none)"

echo ""
echo "=== Top 10 zombie parent PIDs (count) ==="
ps -eo ppid,stat,cmd 2>/dev/null | awk '$2 ~ /Z/ {print $1}' | sort | uniq -c | sort -nr | head -10 || echo "(none)"

echo ""
echo "=== Top 3 PPIDs — owner process ==="
for p in $(ps -eo ppid,stat,cmd 2>/dev/null | awk '$2 ~ /Z/ {print $1}' | sort | uniq -c | sort -nr | head -3 | awk '{print $2}'); do
  echo "--- PPID $p ---"
  ps -p "$p" -o pid,ppid,stat,cmd 2>/dev/null || echo "(process $p not found)"
done

echo ""
echo "=== containerd-shim processes (first 20) ==="
ps aux 2>/dev/null | grep containerd-shim | grep -v grep | head -20 || echo "(none)"

echo ""
echo "=== Decision: if top zombie PPIDs match containerd-shim PIDs above → proceed to Step B. Else: INSUFFICIENT EVIDENCE (report top 5 PPID mappings). ==="
