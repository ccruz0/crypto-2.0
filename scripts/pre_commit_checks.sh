#!/bin/bash
# Pre-commit checks script
# Runs backend tests and frontend lint checks

set -euo pipefail

# Get the repository root directory
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "🔍 Running pre-commit checks..."
echo "Repository root: $REPO_ROOT"
echo ""

# Track whether checks were actually run and passed
BACKEND_CHECKED=false
BACKEND_PASSED=false
FRONTEND_CHECKED=false
FRONTEND_PASSED=false

# Backend: Run pytest
echo "📦 Running backend tests (pytest)..."
if python3 -c "import pytest" 2>/dev/null; then
    cd "$REPO_ROOT/backend"
    # Run pytest, continuing on collection errors to run tests that can be collected
    # Focus on app/tests/ directory which contains the main test suite
    if [ -d "app/tests" ]; then
        BACKEND_CHECKED=true
        # Run pytest with continue-on-collection-errors to skip tests that can't be collected
        # Capture output to check results
        if python3 -m pytest -q app/tests/ --continue-on-collection-errors --tb=line > /tmp/pytest_output.txt 2>&1; then
            echo "✅ Backend tests passed"
            BACKEND_PASSED=true
            rm -f /tmp/pytest_output.txt
        else
            # Check if any tests actually passed by looking at the summary line
            passed_count=$(grep -oE "[0-9]+ passed" /tmp/pytest_output.txt | grep -oE "[0-9]+" | head -1 || echo "0")
            failed_count=$(grep -oE "[0-9]+ failed" /tmp/pytest_output.txt | grep -oE "[0-9]+" | head -1 || echo "0")
            error_count=$(grep -oE "[0-9]+ error" /tmp/pytest_output.txt | grep -oE "[0-9]+" | head -1 || echo "0")
            
            if [ -n "$passed_count" ] && [ "$passed_count" -gt "0" ]; then
                echo "⚠️  Some backend tests passed ($passed_count passed), but some had issues"
                if [ -n "$failed_count" ] && [ "$failed_count" -gt "0" ]; then
                    echo "   Failed tests: $failed_count"
                fi
                if [ -n "$error_count" ] && [ "$error_count" -gt "0" ]; then
                    echo "   Test errors: $error_count"
                fi
                echo "   Review test output below:"
                cat /tmp/pytest_output.txt | tail -15
                echo ""
                echo "❌ Backend tests failed - commit blocked"
                rm -f /tmp/pytest_output.txt
                exit 1
            else
                echo "❌ Backend tests failed - no tests passed"
                cat /tmp/pytest_output.txt | tail -20
                rm -f /tmp/pytest_output.txt
                exit 1
            fi
        fi
    else
        echo "⚠️  app/tests directory not found. Skipping backend tests."
    fi
else
    echo "⚠️  pytest not found. Skipping backend tests."
    echo "   Install with: pip install pytest pytest-asyncio"
fi

echo ""

# Frontend: Run npm lint (excluding generated files)
echo "📦 Running frontend lint (npm run lint)..."
if [ -f "$REPO_ROOT/frontend/package.json" ]; then
    cd "$REPO_ROOT/frontend"
    if [ -d "node_modules" ]; then
        FRONTEND_CHECKED=true
        npm run lint || {
            echo "❌ Frontend lint failed"
            exit 1
        }
        echo "✅ Frontend lint passed"
        FRONTEND_PASSED=true
    else
        echo "⚠️  node_modules not found. Skipping frontend lint."
        echo "   Install with: cd frontend && npm install"
    fi
else
    echo "⚠️  frontend/package.json not found. Skipping frontend lint."
fi

echo ""

# Only report success if all required checks actually ran and passed
if [ "$BACKEND_CHECKED" = false ] && [ "$FRONTEND_CHECKED" = false ]; then
    echo "❌ Pre-commit checks failed - no checks were run"
    echo "   Backend: pytest not available or app/tests not found"
    echo "   Frontend: package.json not found or node_modules missing"
    exit 1
elif [ "$BACKEND_CHECKED" = true ] && [ "$BACKEND_PASSED" = false ]; then
    echo "❌ Pre-commit checks failed - backend tests failed"
    exit 1
elif [ "$FRONTEND_CHECKED" = true ] && [ "$FRONTEND_PASSED" = false ]; then
    echo "❌ Pre-commit checks failed - frontend lint failed"
    exit 1
elif [ "$BACKEND_CHECKED" = true ] && [ "$FRONTEND_CHECKED" = true ]; then
    echo "✅ All pre-commit checks passed!"
elif [ "$BACKEND_CHECKED" = true ]; then
    echo "⚠️  Backend checks passed, but frontend lint was skipped"
    echo "   Install frontend dependencies: cd frontend && npm install"
    exit 1
elif [ "$FRONTEND_CHECKED" = true ]; then
    echo "⚠️  Frontend checks passed, but backend tests were skipped"
    echo "   Install pytest: pip install pytest pytest-asyncio"
    exit 1
fi

