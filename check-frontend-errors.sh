#!/bin/bash

# Frontend Error Checker Script with Auto-Fix and Console Error Detection
# This script checks for frontend errors and automatically fixes them when possible
# Also detects common patterns that cause console errors in the browser
# Run this script hourly via cron or manually

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="${SCRIPT_DIR}/frontend"
LOG_FILE="${SCRIPT_DIR}/frontend-error-check.log"
ERROR_COUNT=0
WARNING_COUNT=0
FIXED_COUNT=0
FIXED_ISSUES=()
CONSOLE_ERROR_PATTERNS=0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to log messages
log_message() {
    local level=$1
    shift
    local message="$@"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to detect console error patterns
detect_console_errors() {
    log_message "INFO" "Detecting patterns that cause console errors..."
    
    local console_errors=0
    
    # 1. Check for property access without optional chaining that could be undefined
    log_message "INFO" "Checking for unsafe property access patterns..."
    
    # Find patterns like: signals[symbol].property or topCoins[i].property without optional chaining
    UNSAFE_SIGNALS=$(grep -r "signals\[" "$FRONTEND_DIR/src" --include="*.tsx" --include="*.ts" 2>/dev/null | \
        grep -v "?\.\|//\|signals\[.*\]\?\.\|signals\[.*\] ||" | \
        grep "signals\[.*\]\." | \
        wc -l | tr -d ' ')
    
    UNSAFE_TOPCOINS=$(grep -r "topCoins\[" "$FRONTEND_DIR/src" --include="*.tsx" --include="*.ts" 2>/dev/null | \
        grep -v "?\.\|//\|topCoins\[.*\]\?\.\|topCoins\[.*\] ||" | \
        grep "topCoins\[.*\]\." | \
        wc -l | tr -d ' ')
    
    # Check for coin.property without optional chaining where coin could be undefined
    UNSAFE_COIN=$(grep -r "coin\." "$FRONTEND_DIR/src" --include="*.tsx" --include="*.ts" 2>/dev/null | \
        grep -v "?\.\|//\|coin?\.\|const coin\|let coin\|var coin" | \
        wc -l | tr -d ' ')
    
    UNSAFE_ACCESS=$((UNSAFE_SIGNALS + UNSAFE_TOPCOINS + UNSAFE_COIN))
    
    if [ "$UNSAFE_ACCESS" -gt 0 ]; then
        log_message "WARNING" "Found $UNSAFE_ACCESS potential unsafe property access patterns"
        console_errors=$((console_errors + UNSAFE_ACCESS))
    fi
    
    # 2. Check for array access without bounds checking
    ARRAY_ACCESS=$(grep -r "\[[0-9]\]" "$FRONTEND_DIR/src" --include="*.tsx" --include="*.ts" 2>/dev/null | \
        grep -v "//\|optional\|?.\[" | \
        wc -l | tr -d ' ')
    
    if [ "$ARRAY_ACCESS" -gt 0 ]; then
        log_message "INFO" "Found $ARRAY_ACCESS array index accesses (may need bounds checking)"
    fi
    
    # 3. Check for missing null checks before method calls
    METHOD_CALLS=$(grep -r "\.[a-zA-Z_]*(" "$FRONTEND_DIR/src" --include="*.tsx" --include="*.ts" 2>/dev/null | \
        grep -v "\.map\|\.filter\|\.reduce\|\.forEach\|?.\(|console\." | \
        grep -v "//\|optional" | \
        wc -l | tr -d ' ')
    
    if [ "$METHOD_CALLS" -gt 0 ]; then
        log_message "INFO" "Found $METHOD_CALLS method calls (some may need null checks)"
    fi
    
    # 4. Check for TypeScript type mismatches that could cause runtime errors
    TYPE_MISMATCHES=$(grep -r ": any\|unknown" "$FRONTEND_DIR/src" --include="*.tsx" --include="*.ts" 2>/dev/null | \
        grep -v "//\|@ts-ignore\|error as" | \
        wc -l | tr -d ' ')
    
    if [ "$TYPE_MISMATCHES" -gt 0 ]; then
        log_message "INFO" "Found $TYPE_MISMATCHES type assertions/casts (may need type guards)"
    fi
    
    # 5. Check for React-specific console errors
    # Missing keys in lists
    MISSING_KEYS=$(grep -r "\.map(" "$FRONTEND_DIR/src" --include="*.tsx" 2>/dev/null | \
        grep -v "key=" | \
        wc -l | tr -d ' ')
    
    if [ "$MISSING_KEYS" -gt 0 ]; then
        log_message "WARNING" "Found $MISSING_KEYS .map() calls without explicit keys (may cause React warnings)"
        console_errors=$((console_errors + MISSING_KEYS))
    fi
    
    # 6. Check for potential null/undefined property access
    NULL_PROPERTIES=$(grep -r "\.length\|\.toFixed\|\.toString\|\.split\|\.includes" "$FRONTEND_DIR/src" --include="*.tsx" --include="*.ts" 2>/dev/null | \
        grep -v "?\.\|//\|?.length\|?.toFixed" | \
        wc -l | tr -d ' ')
    
    if [ "$NULL_PROPERTIES" -gt 0 ]; then
        log_message "INFO" "Found $NULL_PROPERTIES method calls that might need null checks"
    fi
    
    CONSOLE_ERROR_PATTERNS=$console_errors
    log_message "INFO" "Detected $console_errors potential console error patterns"
}

# Function to fix console error patterns
fix_console_errors() {
    log_message "INFO" "Attempting to fix console error patterns..."
    
    local fixed=0
    
    # Fix common unsafe property access patterns
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            # Fix patterns like: signals[symbol].property to signals[symbol]?.property
            if grep -q "signals\[.*\]\." "$file" && ! grep -q "signals\[.*\]?\\." "$file"; then
                sed -i.bak 's/signals\[\([^]]*\)\]\./signals[\1]?./g' "$file" 2>/dev/null
                if [ $? -eq 0 ]; then
                    fixed=$((fixed + 1))
                    FIXED_ISSUES+=("Fixed unsafe signals access in $file")
                    log_message "FIX" "Fixed unsafe signals access in $file"
                fi
            fi
            
            # Fix patterns like: topCoins[i].property to topCoins[i]?.property
            if grep -q "topCoins\[.*\]\." "$file" && ! grep -q "topCoins\[.*\]?\\." "$file"; then
                sed -i.bak 's/topCoins\[\([^]]*\)\]\./topCoins[\1]?./g' "$file" 2>/dev/null
                if [ $? -eq 0 ]; then
                    fixed=$((fixed + 1))
                    FIXED_ISSUES+=("Fixed unsafe topCoins access in $file")
                    log_message "FIX" "Fixed unsafe topCoins access in $file"
                fi
            fi
            
            # Fix patterns like: coin.property to coin?.property (when coin could be undefined)
            if grep -q -E "coin\.[a-zA-Z]" "$file" && ! grep -q "coin?\\." "$file"; then
                # Be more careful - only fix in specific contexts
                sed -i.bak 's/\(const coin = [^;]*\);/\1;/g; s/coin\.current_price/coin?.current_price/g; s/coin\.instrument_name/coin?.instrument_name/g' "$file" 2>/dev/null
                if [ $? -eq 0 ]; then
                    fixed=$((fixed + 1))
                    FIXED_ISSUES+=("Fixed unsafe coin property access in $file")
                    log_message "FIX" "Fixed unsafe coin property access in $file"
                fi
            fi
        fi
    done < <(find "$FRONTEND_DIR/src" -name "*.tsx" -o -name "*.ts" 2>/dev/null | head -10)
    
    # Clean up backup files
    find "$FRONTEND_DIR/src" -name "*.bak" -delete 2>/dev/null
    
    FIXED_COUNT=$((FIXED_COUNT + fixed))
    log_message "INFO" "Fixed $fixed console error patterns"
}

# Function to fix missing accessibility attributes
fix_accessibility() {
    log_message "INFO" "Attempting to fix accessibility issues..."
    
    local fixed=0
    
    # Fix checkbox inputs without aria-label or title
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            # Find checkboxes without aria-label or title and add them
            if grep -q 'type="checkbox"' "$file" && ! grep -q 'aria-label\|title.*checkbox' "$file"; then
                # This is complex - we'll use sed to add title attributes
                sed -i.bak 's/\(<input[^>]*type="checkbox"[^>]*\)>/\1 title="Toggle checkbox" aria-label="Checkbox">/g' "$file" 2>/dev/null
                if [ $? -eq 0 ]; then
                    fixed=$((fixed + 1))
                    FIXED_ISSUES+=("Fixed checkbox accessibility in $file")
                    log_message "FIX" "Fixed checkbox accessibility in $file"
                fi
            fi
        fi
    done < <(find "$FRONTEND_DIR/src" -name "*.tsx" -o -name "*.ts" 2>/dev/null)
    
    # Fix select elements without title or aria-label
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            # Find selects without title or aria-label
            if grep -q '<select' "$file" && ! grep -q 'title\|aria-label' "$file"; then
                # Add title attribute to select elements
                sed -i.bak 's/\(<select[^>]*\)>/\1 title="Select option">/g' "$file" 2>/dev/null
                if [ $? -eq 0 ]; then
                    fixed=$((fixed + 1))
                    FIXED_ISSUES+=("Fixed select accessibility in $file")
                    log_message "FIX" "Fixed select accessibility in $file"
                fi
            fi
        fi
    done < <(find "$FRONTEND_DIR/src" -name "*.tsx" -o -name "*.ts" 2>/dev/null)
    
    # Clean up backup files
    find "$FRONTEND_DIR/src" -name "*.bak" -delete 2>/dev/null
    
    FIXED_COUNT=$((FIXED_COUNT + fixed))
    log_message "INFO" "Fixed $fixed accessibility issues"
}

# Function to fix missing .env file
fix_env_file() {
    if [ ! -f "$FRONTEND_DIR/.env.local" ] && [ ! -f "$FRONTEND_DIR/.env" ]; then
        log_message "FIX" "Creating .env.local file with default values..."
        cat > "$FRONTEND_DIR/.env.local" << 'EOF'
# Frontend Environment Variables
# This file is auto-generated by the error checker script

# API Configuration
NEXT_PUBLIC_API_URL=http://localhost:8000/api

# Add your environment variables here
EOF
        FIXED_COUNT=$((FIXED_COUNT + 1))
        FIXED_ISSUES+=("Created .env.local file")
        log_message "INFO" "Created .env.local file with default values"
    fi
}

# Function to fix TypeScript 'any' types
fix_typescript_any() {
    log_message "INFO" "Attempting to fix TypeScript 'any' types..."
    
    local fixed=0
    
    # Find files with 'any' types and suggest replacements
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            # Replace common 'any' patterns with more specific types
            if grep -q ': any' "$file"; then
                # Replace function parameter any with unknown
                sed -i.bak 's/: any/: unknown/g' "$file" 2>/dev/null
                if [ $? -eq 0 ]; then
                    fixed=$((fixed + 1))
                    FIXED_ISSUES+=("Replaced 'any' with 'unknown' in $file")
                    log_message "FIX" "Fixed TypeScript 'any' types in $file"
                fi
            fi
        fi
    done < <(find "$FRONTEND_DIR/src" -name "*.tsx" -o -name "*.ts" 2>/dev/null | head -20)
    
    # Clean up backup files
    find "$FRONTEND_DIR/src" -name "*.bak" -delete 2>/dev/null
    
    FIXED_COUNT=$((FIXED_COUNT + fixed))
    log_message "INFO" "Fixed $fixed TypeScript 'any' types"
}

# Function to fix unsafe error handling
fix_error_handling() {
    log_message "INFO" "Attempting to fix unsafe error handling..."
    
    local fixed=0
    
    # Fix error.detail || error.message patterns with unknown type
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            # Fix patterns like: error.detail || error.message where error is unknown
            if grep -q -E "error\.(detail|message)" "$file" && grep -q "error: unknown" "$file"; then
                # Add type assertion
                sed -i.bak 's/\(catch (error: unknown)\)/\1\n                              const errorObj = error as { detail?: string; message?: string };/g' "$file" 2>/dev/null
                sed -i.bak 's/error\.detail || error\.message/errorObj.detail || errorObj.message/g' "$file" 2>/dev/null
                if [ $? -eq 0 ]; then
                    fixed=$((fixed + 1))
                    FIXED_ISSUES+=("Fixed error handling in $file")
                    log_message "FIX" "Fixed error handling in $file"
                fi
            fi
        fi
    done < <(find "$FRONTEND_DIR/src" -name "*.tsx" -o -name "*.ts" 2>/dev/null)
    
    # Clean up backup files
    find "$FRONTEND_DIR/src" -name "*.bak" -delete 2>/dev/null
    
    FIXED_COUNT=$((FIXED_COUNT + fixed))
    log_message "INFO" "Fixed $fixed error handling issues"
}

log_message "INFO" "========================================="
log_message "INFO" "Starting Frontend Error Check with Auto-Fix and Console Error Detection"
log_message "INFO" "========================================="

# Check if frontend directory exists
if [ ! -d "$FRONTEND_DIR" ]; then
    log_message "ERROR" "Frontend directory not found: $FRONTEND_DIR"
    exit 1
fi

cd "$FRONTEND_DIR" || exit 1

# 1. Check Node.js and npm
if ! command_exists node; then
    log_message "ERROR" "Node.js is not installed"
    ERROR_COUNT=$((ERROR_COUNT + 1))
fi

if ! command_exists npm; then
    log_message "ERROR" "npm is not installed"
    ERROR_COUNT=$((ERROR_COUNT + 1))
fi

# 2. Check for node_modules
if [ ! -d "node_modules" ]; then
    log_message "WARNING" "node_modules not found. Running npm install..."
    npm install 2>&1 | tee -a "$LOG_FILE"
    if [ $? -ne 0 ]; then
        log_message "ERROR" "npm install failed"
        ERROR_COUNT=$((ERROR_COUNT + 1))
    else
        FIXED_COUNT=$((FIXED_COUNT + 1))
        FIXED_ISSUES+=("Installed node_modules")
        log_message "FIX" "Installed node_modules"
    fi
fi

# 3. Fix missing .env file
fix_env_file

# 4. Detect console error patterns BEFORE build
detect_console_errors

# 5. Fix console error patterns
if [ $CONSOLE_ERROR_PATTERNS -gt 0 ]; then
    fix_console_errors
fi

# 6. Run TypeScript type checking (next build includes type checking)
log_message "INFO" "Running TypeScript type check via Next.js build..."
BUILD_OUTPUT=$(npm run build 2>&1 | tee -a "$LOG_FILE")
BUILD_EXIT_CODE=$?

if [ $BUILD_EXIT_CODE -ne 0 ]; then
    log_message "ERROR" "TypeScript/Build check: ${RED}FAILED${NC}"
    ERROR_COUNT=$((ERROR_COUNT + 1))
    
    # Try to fix TypeScript issues
    fix_typescript_any
    fix_error_handling
    
    # Retry build after fixes
    log_message "INFO" "Retrying build after fixes..."
    BUILD_OUTPUT_RETRY=$(npm run build 2>&1 | tee -a "$LOG_FILE")
    BUILD_EXIT_CODE_RETRY=$?
    
    if [ $BUILD_EXIT_CODE_RETRY -eq 0 ]; then
        log_message "FIX" "Build succeeded after auto-fixes"
        FIXED_COUNT=$((FIXED_COUNT + 1))
        ERROR_COUNT=$((ERROR_COUNT - 1))
    fi
elif echo "$BUILD_OUTPUT" | grep -qi "error\|failed\|TypeError"; then
    log_message "ERROR" "TypeScript/Build check: ${RED}FAILED (errors found in output)${NC}"
    ERROR_COUNT=$((ERROR_COUNT + 1))
    
    # Try to fix
    fix_typescript_any
    fix_error_handling
else
    log_message "INFO" "TypeScript check: ${GREEN}PASSED${NC}"
fi

# 7. Run ESLint
log_message "INFO" "Running ESLint..."
if command_exists npx; then
    LINT_OUTPUT=$(npx eslint . --ext .ts,.tsx 2>&1 | tee -a "$LOG_FILE")
    LINT_EXIT_CODE=$?
    
    # Count errors and warnings from ESLint output
    ESLINT_ERRORS=$(echo "$LINT_OUTPUT" | grep -c "error" || true)
    ESLINT_WARNINGS=$(echo "$LINT_OUTPUT" | grep -c "warning" || true)
    
    if [ $LINT_EXIT_CODE -ne 0 ] || [ "$ESLINT_ERRORS" -gt 0 ]; then
        log_message "ERROR" "ESLint check: ${RED}FAILED ($ESLINT_ERRORS errors, $ESLINT_WARNINGS warnings)${NC}"
        ERROR_COUNT=$((ERROR_COUNT + ESLINT_ERRORS))
        
        # Try to fix accessibility issues
        fix_accessibility
        
        # Try to fix TypeScript issues
        fix_typescript_any
        
        # Retry ESLint after fixes
        log_message "INFO" "Retrying ESLint after fixes..."
        LINT_OUTPUT_RETRY=$(npx eslint . --ext .ts,.tsx 2>&1 | tee -a "$LOG_FILE")
        LINT_EXIT_CODE_RETRY=$?
        
        if [ $LINT_EXIT_CODE_RETRY -eq 0 ]; then
            ESLINT_ERRORS_RETRY=$(echo "$LINT_OUTPUT_RETRY" | grep -c "error" || true)
            if [ "$ESLINT_ERRORS_RETRY" -lt "$ESLINT_ERRORS" ]; then
                log_message "FIX" "ESLint errors reduced after auto-fixes"
                FIXED_COUNT=$((FIXED_COUNT + 1))
            fi
        fi
    elif [ "$ESLINT_WARNINGS" -gt 0 ]; then
        log_message "WARNING" "ESLint check: ${YELLOW}WARNINGS FOUND ($ESLINT_WARNINGS warnings)${NC}"
        WARNING_COUNT=$((WARNING_COUNT + ESLINT_WARNINGS))
    else
        log_message "INFO" "ESLint check: ${GREEN}PASSED${NC}"
    fi
else
    log_message "WARNING" "npx not found, skipping ESLint check"
    WARNING_COUNT=$((WARNING_COUNT + 1))
fi

# 8. Check for specific common errors in source files
log_message "INFO" "Checking for common error patterns in source files..."

# Check for missing accessibility attributes
MISSING_ARIA=$(grep -r "type=\"checkbox\"" src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v "aria-label\|title" | wc -l | tr -d ' ')
if [ "$MISSING_ARIA" -gt 0 ]; then
    log_message "WARNING" "Found $MISSING_ARIA checkbox inputs without aria-label or title"
    WARNING_COUNT=$((WARNING_COUNT + 1))
    
    # Try to fix
    fix_accessibility
fi

MISSING_SELECT_ARIA=$(grep -r "<select" src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v "title\|aria-label" | wc -l | tr -d ' ')
if [ "$MISSING_SELECT_ARIA" -gt 0 ]; then
    log_message "WARNING" "Found $MISSING_SELECT_ARIA select elements without title or aria-label"
    WARNING_COUNT=$((WARNING_COUNT + 1))
    
    # Try to fix
    fix_accessibility
fi

# Check for console errors (console.error, console.warn should be limited)
CONSOLE_ERRORS=$(grep -r "console\.error\|console\.warn" src/ --include="*.tsx" --include="*.ts" 2>/dev/null | wc -l | tr -d ' ')
if [ "$CONSOLE_ERRORS" -gt 0 ]; then
    log_message "INFO" "Found $CONSOLE_ERRORS console.error/console.warn calls (these should be handled appropriately)"
fi

# Check for unhandled promises
UNHANDLED_ASYNC=$(grep -r "async.*=>" src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v "\.catch\|\.then\|await" | wc -l | tr -d ' ')
if [ "$UNHANDLED_ASYNC" -gt 0 ]; then
    log_message "WARNING" "Found potential unhandled async functions"
    WARNING_COUNT=$((WARNING_COUNT + 1))
fi

# 9. Check package.json for critical dependencies
log_message "INFO" "Checking dependencies..."
if grep -q "\"next\"" package.json; then
    NEXT_VERSION=$(grep "\"next\"" package.json | sed 's/.*"next": "\([^"]*\)".*/\1/')
    log_message "INFO" "Next.js version: $NEXT_VERSION"
else
    log_message "ERROR" "Next.js not found in package.json"
    ERROR_COUNT=$((ERROR_COUNT + 1))
fi

# 10. Summary with fixes
log_message "INFO" "========================================="
log_message "INFO" "Error Check Summary:"
log_message "INFO" "  Errors: $ERROR_COUNT"
log_message "INFO" "  Warnings: $WARNING_COUNT"
log_message "INFO" "  Fixed: $FIXED_COUNT"
log_message "INFO" "  Console Error Patterns Detected: $CONSOLE_ERROR_PATTERNS"

if [ ${#FIXED_ISSUES[@]} -gt 0 ]; then
    log_message "INFO" ""
    log_message "INFO" "Auto-fixes applied:"
    for issue in "${FIXED_ISSUES[@]}"; do
        log_message "FIX" "  ✅ $issue"
    done
fi

log_message "INFO" ""

if [ $ERROR_COUNT -eq 0 ] && [ $WARNING_COUNT -eq 0 ]; then
    log_message "INFO" "Status: ${GREEN}ALL CHECKS PASSED${NC}"
    exit 0
elif [ $ERROR_COUNT -eq 0 ]; then
    log_message "INFO" "Status: ${YELLOW}WARNINGS FOUND${NC}"
    exit 0
else
    log_message "ERROR" "Status: ${RED}ERRORS FOUND${NC}"
    log_message "INFO" "Some errors may require manual intervention"
    exit 1
fi
