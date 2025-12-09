#!/usr/bin/env bash
# Test script to verify Dockerfile paths match GitHub Actions workflow configuration

set -e

echo "🧪 Testing Dockerfile paths (simulating GitHub Actions)..."
echo ""

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

test_path() {
    local context=$1
    local file=$2
    local desc=$3
    
    echo -n "Testing: $desc... "
    
    if [ ! -d "$context" ]; then
        echo -e "${RED}❌ Context not found${NC}"
        return 1
    fi
    
    if [[ "$file" == ./* ]]; then
        actual_path="$file"
    else
        actual_path="$context/$file"
    fi
    
    if [ -f "$actual_path" ]; then
        echo -e "${GREEN}✅ PASS${NC} (found: $actual_path)"
        return 0
    else
        echo -e "${RED}❌ FAIL${NC} (not found: $actual_path)"
        return 1
    fi
}

test_path "./frontend" "Dockerfile" "Frontend (context: ./frontend, file: Dockerfile)"
test_path "./backend" "Dockerfile" "Backend (context: ./backend, file: Dockerfile)"
test_path "./docker/postgres" "Dockerfile" "Postgres (context: ./docker/postgres, file: Dockerfile)"

echo ""
echo "✅ All correct paths verified!"
