#!/bin/bash
###############################################################################
# run_trivy_fs.sh
# -----------------------------------------------------------------------------
# Helper script to run Trivy filesystem scan locally.
# This mirrors the behavior of the GitHub Actions workflow.
#
# Usage:
#   bash scripts/run_trivy_fs.sh
#
# Exit codes:
#   0 - Scan completed (may have findings, but non-blocking)
#   1 - Scan failed or critical error
###############################################################################

set -e

# Dynamically resolve repo root based on script location
# This allows the script to work regardless of where the repo is cloned
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# Check if Trivy is available
TRIVY_CMD=""
if command -v trivy &> /dev/null; then
    TRIVY_CMD="trivy"
elif docker run --rm aquasec/trivy version > /dev/null 2>&1; then
    # Quote $REPO_ROOT to handle paths with spaces
    TRIVY_CMD="docker run --rm -v \"$REPO_ROOT:/workspace\" -w /workspace aquasec/trivy"
else
    echo "ERROR: Trivy not found. Install it or ensure Docker can run aquasec/trivy"
    exit 1
fi

# Run filesystem scan with same parameters as workflow
# exit-code: 0 means non-blocking (findings reported but don't fail)
# Uses sh -c "cd \"$REPO_ROOT\" && ..." to match workflow behavior (quoted for paths with spaces)
sh -c "cd \"$REPO_ROOT\" && $TRIVY_CMD fs \
    --severity HIGH,CRITICAL \
    --ignore-unfixed \
    --exit-code 0 \
    --format table \
    ."

exit 0
