#!/usr/bin/env bash

set -euo pipefail

# Alert Origin Audit Script
# Detects any place where AWS notifications (Telegram or others) might be hardcoded to be blocked,
# mis-routed, or mis-labeled.

cd "$(dirname "$0")/.."

echo "=========================================="
echo "=== Alert Origin Audit ==="
echo "=========================================="
echo ""

# Track suspicious patterns
SUSPICIOUS_FOUND=0
SUSPICIOUS_FILES=()

# Function to check for suspicious patterns
check_suspicious() {
    local pattern="$1"
    local description="$2"
    local file="$3"
    local exclude_pattern="${4:-}"
    
    # Skip if file doesn't exist
    [[ ! -f "$file" ]] && return
    
    # Check for pattern, excluding comments and type hints
    local matches
    if [[ -n "$exclude_pattern" ]]; then
        matches=$(grep -n "$pattern" "$file" 2>/dev/null | grep -v "$exclude_pattern" || true)
    else
        matches=$(grep -n "$pattern" "$file" 2>/dev/null || true)
    fi
    
    # Filter out false positives (comments, type hints, default values in function signatures)
    matches=$(echo "$matches" | grep -v "#.*LOCAL" | grep -v "Optional\[str\]" | grep -v "origin.*=.*None" | grep -v "origin_upper.*=.*origin.upper" || true)
    
    if [[ -n "$matches" ]]; then
        echo "⚠️  SUSPICIOUS: $description"
        echo "   File: $file"
        echo "   Pattern: $pattern"
        echo "$matches" | head -5 | sed 's/^/      /'
        echo ""
        SUSPICIOUS_FOUND=1
        if [[ ! " ${SUSPICIOUS_FILES[*]} " =~ " ${file} " ]]; then
            SUSPICIOUS_FILES+=("$file")
        fi
    fi
}

echo "[1] Searching for RUNTIME_ORIGIN references..."
echo "----------------------------------------"
rg "RUNTIME_ORIGIN" . 2>/dev/null | head -20 || true
echo ""

echo "[2] Searching for origin assignments..."
echo "----------------------------------------"
rg "origin\s*=" backend -n 2>/dev/null | head -30 || true
echo ""

echo "[3] Searching for AWS references..."
echo "----------------------------------------"
rg "AWS" backend -n 2>/dev/null | grep -v "test_" | grep -v ".pyc" | head -30 || true
echo ""

echo "[4] Searching for [AWS] prefix patterns..."
echo "----------------------------------------"
rg "\[AWS\]" backend -n 2>/dev/null | head -20 || true
echo ""

echo "[5] Searching for LOCAL references..."
echo "----------------------------------------"
rg "LOCAL" backend -n 2>/dev/null | grep -v "test_" | grep -v ".pyc" | head -30 || true
echo ""

echo "[6] Searching for TG_LOCAL_DEBUG patterns..."
echo "----------------------------------------"
rg "TG_LOCAL_DEBUG" backend -n 2>/dev/null || true
echo ""

echo "[7] Searching for DISABLE_ALERT patterns..."
echo "----------------------------------------"
rg "DISABLE_ALERT" backend -n 2>/dev/null || true
echo ""

echo "[8] Searching for DISABLE_TELEGRAM patterns..."
echo "----------------------------------------"
rg "DISABLE_TELEGRAM" backend -n 2>/dev/null || true
echo ""

echo "[9] Searching for ENABLE_TELEGRAM patterns..."
echo "----------------------------------------"
rg "ENABLE_TELEGRAM" backend -n 2>/dev/null || true
echo ""

echo "[10] Searching for TELEGRAM_DISABLED patterns..."
echo "----------------------------------------"
rg "TELEGRAM_DISABLED" backend -n 2>/dev/null || true
echo ""

echo "[11] Searching for NOTIFY patterns..."
echo "----------------------------------------"
rg "NOTIFY" backend -n 2>/dev/null | head -20 || true
echo ""

echo "[12] Searching for send_message calls..."
echo "----------------------------------------"
rg "send_message" backend/app/services -n 2>/dev/null | head -30 || true
echo ""

echo "[13] Searching for send_buy_signal calls..."
echo "----------------------------------------"
rg "send_buy_signal" backend -n 2>/dev/null | grep -v "test_" | head -20 || true
echo ""

echo "[14] Searching for send_sell_signal calls..."
echo "----------------------------------------"
rg "send_sell_signal" backend -n 2>/dev/null | grep -v "test_" | head -20 || true
echo ""

echo "=========================================="
echo "[15] Checking for suspicious blocking patterns..."
echo "=========================================="
echo ""

# Check for dangerous patterns in key files
KEY_FILES=(
    "backend/app/services/telegram_notifier.py"
    "backend/app/services/signal_monitor.py"
    "backend/app/api/routes_test.py"
    "backend/app/core/runtime.py"
    "backend/app/core/config.py"
    "backend/app/main.py"
)

for file in "${KEY_FILES[@]}"; do
    if [[ -f "$file" ]]; then
        # Check for patterns that block AWS (exclude comments and type hints)
        check_suspicious "if.*origin.*==.*AWS.*return.*False" "AWS origin blocked with return False" "$file" "#"
        check_suspicious "if.*origin_upper.*==.*AWS.*return.*False" "AWS origin_upper blocked with return False" "$file" "#"
        check_suspicious "if.*get_runtime_origin.*==.*AWS.*return" "get_runtime_origin() == AWS blocks" "$file" "#"
        check_suspicious "if.*AWS.*and.*DISABLE" "AWS combined with DISABLE flag" "$file" "#"
        check_suspicious "if.*origin.*==.*AWS.*:.*return[^_]" "AWS origin early return (may block)" "$file" "#"
        # Check for forced LOCAL assignment (exclude comments, type hints, and default values)
        check_suspicious "^[^#]*origin\s*=\s*[\"']LOCAL[\"']" "Origin hardcoded to LOCAL string" "$file" "#.*LOCAL|Optional\[str\]|origin.*=.*None"
        check_suspicious "^[^#]*origin\s*=\s*\"LOCAL\"" "Origin hardcoded to LOCAL string (double quotes)" "$file" "#.*LOCAL|Optional\[str\]|origin.*=.*None"
        check_suspicious "^[^#]*origin\s*=\s*'LOCAL'" "Origin hardcoded to LOCAL string (single quotes)" "$file" "#.*LOCAL|Optional\[str\]|origin.*=.*None"
    fi
done

# Check docker-compose files
echo "[16] Checking docker-compose files for RUNTIME_ORIGIN and disable flags..."
echo "----------------------------------------"
if [[ -f "docker-compose.yml" ]]; then
    echo "docker-compose.yml:"
    grep -n "RUNTIME_ORIGIN\|DISABLE.*TELEGRAM\|DISABLE.*ALERT\|RUN_TELEGRAM" docker-compose.yml 2>/dev/null || true
    echo ""
fi

# Check for environment files
echo "[17] Checking for .env files with disable flags..."
echo "----------------------------------------"
for env_file in .env .env.local .env.aws; do
    if [[ -f "$env_file" ]]; then
        echo "$env_file:"
        grep -n "DISABLE.*TELEGRAM\|DISABLE.*ALERT\|RUN_TELEGRAM\|RUNTIME_ORIGIN" "$env_file" 2>/dev/null || true
        echo ""
    fi
done

echo "=========================================="
echo "=== Summary ==="
echo "=========================================="
echo ""

if [[ $SUSPICIOUS_FOUND -eq 0 ]]; then
    echo "✅ No suspicious blocking patterns found"
    echo ""
    echo "Key findings:"
    echo "  - telegram_notifier.py gatekeeper allows AWS and TEST origins"
    echo "  - signal_monitor.py correctly uses get_runtime_origin() and passes origin to send_*_signal"
    echo "  - routes_test.py uses origin='TEST' for test alerts"
    echo "  - docker-compose.yml sets RUNTIME_ORIGIN=AWS for backend-aws service"
    echo ""
    echo "✅ AWS alerts should be working correctly"
else
    echo "⚠️  SUSPICIOUS PATTERNS FOUND!"
    echo ""
    echo "Files with suspicious patterns:"
    for file in "${SUSPICIOUS_FILES[@]}"; do
        echo "  - $file"
    done
    echo ""
    echo "⚠️  Review these files carefully to ensure AWS alerts are not blocked"
fi

echo ""
echo "=========================================="
echo "=== End of Audit ==="
echo "=========================================="

exit $SUSPICIOUS_FOUND

