#!/usr/bin/env bash
# Option A EC2 audit: verify backend-aws compose wiring, docker in container, doctor:auth, report.
# Safe: never prints tokens, secrets, env values, or expanded compose config.
set -euo pipefail

REPO_ROOT="/home/ubuntu/automated-trading-platform"
cd "$REPO_ROOT"

# Wait for backend readiness (retry GET /health until 200)
wait_for_health() {
  local url="http://127.0.0.1:8002/api/health"
  local max=30
  local i=1
  while [ "$i" -le "$max" ]; do
    if code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 --max-time 10 "$url" 2>/dev/null); then
      if [ "$code" = "200" ]; then
        return 0
      fi
    fi
    sleep 2
    i=$((i + 1))
  done
  return 1
}

echo "========== Waiting for /health 200 (up to 60s) =========="
if ! wait_for_health; then
  echo "WARN: /health did not return 200; continuing anyway"
fi

echo ""
echo "========== A) BASELINE (host) =========="
git branch --show-current
git log -3 --oneline
docker compose --profile aws ps

echo ""
echo "========== B) COMPOSE WIRING (host) — safe checks only =========="
# Read docker-compose.yml directly; never run "docker compose config" (expands secrets).
grep -q '/var/run/docker.sock' docker-compose.yml && echo "OK: docker.sock volume" || echo "MISSING: docker.sock volume"
grep -q '/app/docker-compose.yml' docker-compose.yml && echo "OK: compose file mount" || echo "MISSING: compose file mount"
grep -q '/app/backend/ai_runs' docker-compose.yml && echo "OK: ai_runs mount" || echo "MISSING: ai_runs mount"
grep -q 'AI_ENGINE_COMPOSE_DIR' docker-compose.yml && echo "OK: AI_ENGINE_COMPOSE_DIR" || echo "MISSING: AI_ENGINE_COMPOSE_DIR"
grep -q 'AI_RUNS_DIR' docker-compose.yml && echo "OK: AI_RUNS_DIR" || echo "MISSING: AI_RUNS_DIR"
grep -q 'working_dir:.*/app/backend' docker-compose.yml && echo "OK: working_dir /app/backend" || echo "MISSING: working_dir /app/backend"

echo ""
echo "========== C) DOCKER INSIDE CONTAINER (backend-aws) =========="
docker compose --profile aws exec -T backend-aws bash -lc '
set -e
whoami
pwd
test -S /var/run/docker.sock && echo "docker.sock: OK" || echo "docker.sock: MISSING"
test -f /app/docker-compose.yml && echo "compose file: OK" || echo "compose file: MISSING"
# Do not echo env values
test -n "${AI_ENGINE_COMPOSE_DIR:-}" && echo "AI_ENGINE_COMPOSE_DIR: set" || echo "AI_ENGINE_COMPOSE_DIR: unset"
test -n "${AI_RUNS_DIR:-}" && echo "AI_RUNS_DIR: set" || echo "AI_RUNS_DIR: unset"
docker version --format "{{.Client.Version}}" 2>/dev/null | head -1 || echo "docker: not found"
docker compose version 2>/dev/null && echo "docker compose: OK" || echo "docker compose: FAIL"
cd /app && docker compose --profile aws ps >/dev/null 2>&1 && echo "compose ps from /app: OK" || echo "compose ps from /app: FAIL"
' || true

echo ""
echo "========== D) ROUTE CHECK (host) =========="
for _ in 1 2 3; do
  code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 http://127.0.0.1:8002/api/ai/run 2>/dev/null) && break
  sleep 1
done
echo "GET /api/ai/run status: ${code:-unknown}"
for _ in 1 2 3; do
  curl -sS -o /tmp/openapi.json --connect-timeout 5 http://127.0.0.1:8002/openapi.json 2>/dev/null && break
  sleep 1
done
python3 -c "
import json
try:
    d = json.load(open('/tmp/openapi.json'))
    paths = d.get('paths') or {}
    print('has_/api/ai/run:', '/api/ai/run' in paths)
except Exception as e:
    print('openapi parse error:', type(e).__name__)
" 2>/dev/null || true

echo ""
echo "========== E) DOCTOR AUTH + REPORT CHECK =========="
for _ in 1 2 3; do
  curl -sS -X POST http://127.0.0.1:8002/api/ai/run \
    -H "Content-Type: application/json" \
    -d '{"task":"doctor:auth","mode":"sandbox","apply_changes":false}' \
    -o /tmp/doctor_auth.json 2>/dev/null && break
  sleep 2
done

RUN_DIR=$(python3 -c "
import json
try:
    r = json.load(open('/tmp/doctor_auth.json'))
    d = r.get('run_dir', '')
    print(d.replace('/app/', '', 1) if d.startswith('/app/') else d)
except Exception:
    print('')
" 2>/dev/null) || RUN_DIR=""
echo "run_dir: ${RUN_DIR:-<empty>}"

if [ -n "$RUN_DIR" ]; then
  echo "report.json fields (safe only):"
  docker compose --profile aws exec -T backend-aws cat "/app/$RUN_DIR/report.json" 2>/dev/null | python3 -c "
import json, sys
try:
    r = json.load(sys.stdin)
    findings = r.get('findings') or {}
    ex = findings.get('logs_excerpt') or r.get('logs_excerpt') or ''
    print('tail_logs_source:', r.get('tail_logs_source', 'N/A'))
    print('compose_dir_used:', r.get('compose_dir_used', 'N/A'))
    print('logs_excerpt length:', len(ex))
    # Do not print raw excerpt (may contain sensitive lines)
except Exception as e:
    print('parse error:', type(e).__name__)
    sys.exit(1)
" 2>/dev/null || true
fi

echo ""
echo "========== F) PASS/FAIL =========="
if [ -n "$RUN_DIR" ]; then
  docker compose --profile aws exec -T backend-aws cat "/app/$RUN_DIR/report.json" 2>/dev/null | python3 -c "
import json, sys
try:
    r = json.load(sys.stdin)
    findings = r.get('findings') or {}
    ex = findings.get('logs_excerpt') or r.get('logs_excerpt') or ''
    src = r.get('tail_logs_source')
    comp = r.get('compose_dir_used')
    c1 = src == 'docker_compose'
    c2 = comp == '/app'
    c3 = 'docker-compose.yml not found' not in ex
    c4 = len(ex) > 200
    if c1 and c2 and c3 and c4:
        print('PASS (all 4 checks)')
    else:
        print('FAIL')
        if not c1: print('  - tail_logs_source != docker_compose (got:', repr(src), ')')
        if not c2: print('  - compose_dir_used != /app (got:', repr(comp), ')')
        if not c3: print('  - logs_excerpt contains docker-compose.yml not found')
        if not c4: print('  - logs_excerpt length <= 200 (got %s)' % len(ex))
except Exception as e:
    print('FAIL (could not read report:', type(e).__name__, ')')
    sys.exit(1)
" || echo "FAIL (no report or read error)"
else
  echo "FAIL (RUN_DIR empty)"
fi
