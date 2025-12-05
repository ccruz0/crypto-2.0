#!/usr/bin/env bash
#
# Daily Watchlist Audit Test Runner
# Executes Playwright tests for Watchlist audit and logs results
#
# Usage:
#   bash scripts/run_watchlist_audit_daily.sh
#
# This script is designed to be run via cron at 2 AM Bali time (UTC+8)

set -e  # Exit on error

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
LOG_DIR="$PROJECT_ROOT/logs"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/watchlist_audit_${TIMESTAMP}.log"
REPORT_DIR="$LOG_DIR/watchlist_audit_reports"
HTML_REPORT="$REPORT_DIR/report_${TIMESTAMP}.html"

# API Configuration
DASHBOARD_URL="${DASHBOARD_URL:-https://dashboard.hilovivo.com}"
API_BASE_URL="${API_BASE_URL:-https://dashboard.hilovivo.com/api}"

# ============================================================================
# SETUP
# ============================================================================

# Create log directories if they don't exist
mkdir -p "$LOG_DIR"
mkdir -p "$REPORT_DIR"

# Change to frontend directory
cd "$FRONTEND_DIR"

# ============================================================================
# FUNCTIONS
# ============================================================================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a "$LOG_FILE" >&2
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

log "=========================================="
log "Watchlist Audit Daily Test Run"
log "=========================================="
log "Timestamp: $(date)"
log "Timezone: $(date +%Z)"
log "Dashboard URL: $DASHBOARD_URL"
log "API Base URL: $API_BASE_URL"
log "Log File: $LOG_FILE"
log "Report File: $HTML_REPORT"
log ""

# Check if Playwright is installed
if ! command -v npx &> /dev/null; then
    log_error "npx not found. Please install Node.js and npm."
    exit 1
fi

# Check if we're in the frontend directory
if [ ! -f "package.json" ]; then
    log_error "package.json not found. Are we in the frontend directory?"
    exit 1
fi

# Run the tests
log "Starting Playwright tests..."
log ""

cd "$FRONTEND_DIR"

# Run tests with HTML reporter
DASHBOARD_URL="$DASHBOARD_URL" \
API_BASE_URL="$API_BASE_URL" \
npx playwright test tests/e2e/watchlist_audit.spec.ts \
    --reporter=html \
    --reporter=list \
    2>&1 | tee -a "$LOG_FILE"

TEST_EXIT_CODE=${PIPESTATUS[0]}

# Copy HTML report if it exists
if [ -d "playwright-report" ]; then
    cp -r playwright-report/* "$REPORT_DIR/" 2>/dev/null || true
    # Create a timestamped copy
    if [ -f "playwright-report/index.html" ]; then
        cp "playwright-report/index.html" "$HTML_REPORT" 2>/dev/null || true
    fi
fi

log ""
log "=========================================="
if [ $TEST_EXIT_CODE -eq 0 ]; then
    log "✅ ALL TESTS PASSED"
    RESULT="SUCCESS"
else
    log "❌ SOME TESTS FAILED (exit code: $TEST_EXIT_CODE)"
    RESULT="FAILURE"
fi
log "=========================================="
log "Test run completed at $(date)"
log ""

# Generate summary
SUMMARY_FILE="$LOG_DIR/watchlist_audit_summary.txt"
cat > "$SUMMARY_FILE" << EOF
Watchlist Audit Daily Test Summary
==================================
Date: $(date)
Result: $RESULT
Exit Code: $TEST_EXIT_CODE
Log File: $LOG_FILE
HTML Report: $HTML_REPORT
EOF

# Keep only last 30 days of logs
find "$LOG_DIR" -name "watchlist_audit_*.log" -type f -mtime +30 -delete 2>/dev/null || true
find "$REPORT_DIR" -name "report_*.html" -type f -mtime +30 -delete 2>/dev/null || true

# Exit with test result code
exit $TEST_EXIT_CODE





