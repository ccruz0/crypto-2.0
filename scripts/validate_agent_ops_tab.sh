#!/usr/bin/env bash
# Validate Agent Ops tab against backend API reality.
# Run from repo root. Set BASE_URL to your backend (default: http://localhost:8002/api).
# Example: BASE_URL=https://dashboard.hilovivo.com/api ./scripts/validate_agent_ops_tab.sh

BASE_URL="${BASE_URL:-http://localhost:8002/api}"

echo "=== Validating Agent Ops tab against backend ==="
echo "Base URL: $BASE_URL"
echo ""

if ! curl -sS -o /dev/null -w "%{http_code}" "${BASE_URL}/agent/status" 2>/dev/null | grep -qE '^2'; then
  echo "⚠ Backend not reachable at $BASE_URL. Start the backend or set BASE_URL."
  echo "  Example: BASE_URL=https://dashboard.hilovivo.com/api ./scripts/validate_agent_ops_tab.sh"
  exit 1
fi

# 1. /api/agent/status
echo "--- 1. GET /api/agent/status ---"
STATUS=$(curl -sS "${BASE_URL}/agent/status")
echo "$STATUS" | python3 -m json.tool 2>/dev/null || echo "$STATUS"
echo ""

# Expected keys: scheduler_running, automation_enabled, last_scheduler_cycle, scheduler_interval_s,
#   pending_notion_tasks, tasks_in_investigation, tasks_in_patch_phase, tasks_awaiting_deploy,
#   tasks_deploying, pending_approvals
echo "Status keys check:"
for k in scheduler_running automation_enabled last_scheduler_cycle pending_notion_tasks tasks_in_investigation tasks_in_patch_phase tasks_awaiting_deploy tasks_deploying pending_approvals; do
  if echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if '$k' in d else 1)" 2>/dev/null; then
    echo "  ✓ $k"
  else
    echo "  ✗ $k MISSING"
  fi
done
echo ""

# 2. /api/agent/ops/active-tasks
echo "--- 2. GET /api/agent/ops/active-tasks ---"
ACTIVE=$(curl -sS "${BASE_URL}/agent/ops/active-tasks")
echo "$ACTIVE" | python3 -m json.tool 2>/dev/null || echo "$ACTIVE"
echo ""

echo "Active-tasks keys check:"
for k in ok patching deploying awaiting_deploy_approval; do
  if echo "$ACTIVE" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if '$k' in d else 1)" 2>/dev/null; then
    echo "  ✓ $k"
  else
    echo "  ✗ $k MISSING"
  fi
done
echo ""

# 3. /api/agent/ops/recovery
echo "--- 3. GET /api/agent/ops/recovery?limit=15 ---"
RECOVERY=$(curl -sS "${BASE_URL}/agent/ops/recovery?limit=15")
echo "$RECOVERY" | python3 -m json.tool 2>/dev/null || echo "$RECOVERY"
echo ""

echo "Recovery keys check:"
for k in ok recovery_actions count; do
  if echo "$RECOVERY" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if '$k' in d else 1)" 2>/dev/null; then
    echo "  ✓ $k"
  else
    echo "  ✗ $k MISSING"
  fi
done
echo ""

# 4. /api/agent/ops/smoke-checks
echo "--- 4. GET /api/agent/ops/smoke-checks?limit=15 ---"
SMOKE=$(curl -sS "${BASE_URL}/agent/ops/smoke-checks?limit=15")
echo "$SMOKE" | python3 -m json.tool 2>/dev/null || echo "$SMOKE"
echo ""

echo "Smoke-checks keys check:"
for k in ok smoke_checks count; do
  if echo "$SMOKE" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if '$k' in d else 1)" 2>/dev/null; then
    echo "  ✓ $k"
  else
    echo "  ✗ $k MISSING"
  fi
done
echo ""

# 5. /api/agent/ops/failed-investigations
echo "--- 5. GET /api/agent/ops/failed-investigations?limit=15 ---"
FAILED=$(curl -sS "${BASE_URL}/agent/ops/failed-investigations?limit=15")
echo "$FAILED" | python3 -m json.tool 2>/dev/null || echo "$FAILED"
echo ""

echo "Failed-investigations keys check:"
for k in ok failed_investigations count; do
  if echo "$FAILED" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if '$k' in d else 1)" 2>/dev/null; then
    echo "  ✓ $k"
  else
    echo "  ✗ $k MISSING"
  fi
done
echo ""

# 6. /api/agent/ops/deploy-tracker
echo "--- 6. GET /api/agent/ops/deploy-tracker?limit=8 ---"
DEPLOY=$(curl -sS "${BASE_URL}/agent/ops/deploy-tracker?limit=8")
echo "$DEPLOY" | python3 -m json.tool 2>/dev/null || echo "$DEPLOY"
echo ""

echo "Deploy-tracker keys check:"
for k in ok recent_deploys last_deploy_task_id; do
  if echo "$DEPLOY" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if '$k' in d else 1)" 2>/dev/null; then
    echo "  ✓ $k"
  else
    echo "  ✗ $k MISSING"
  fi
done

# Check recent_deploys item structure (task_id, triggered_at, triggered_by)
echo ""
echo "Deploy item structure (first item):"
echo "$DEPLOY" | python3 -c "
import sys, json
d = json.load(sys.stdin)
items = d.get('recent_deploys', [])
if items:
    i = items[0]
    for k in ['task_id', 'triggered_at', 'triggered_by']:
        print('  ✓' if k in i else '  ✗', k)
else:
    print('  (no deploys)')
" 2>/dev/null || true

echo ""
echo "=== Validation complete ==="
