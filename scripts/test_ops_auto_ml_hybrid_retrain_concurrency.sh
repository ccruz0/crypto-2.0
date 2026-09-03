#!/usr/bin/env bash
# Assert ops-auto-ml-hybrid-retrain.yml serializes SSM runs on prod (no overlap).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WF="$ROOT_DIR/.github/workflows/ops-auto-ml-hybrid-retrain.yml"

test -f "$WF" || { echo "FAIL: missing $WF"; exit 1; }

grep -q 'group: auto-ml-hybrid-retrain-prod' "$WF" || {
  echo "FAIL: expected concurrency group auto-ml-hybrid-retrain-prod in $WF"
  exit 1
}

grep -q 'cancel-in-progress: false' "$WF" || {
  echo "FAIL: expected cancel-in-progress: false (queue, do not cancel long retrain)"
  exit 1
}

echo "PASS: ops-auto-ml-hybrid-retrain concurrency group configured (queue, no cancel)"
