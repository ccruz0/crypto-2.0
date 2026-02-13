#!/usr/bin/env bash
# Option A EC2 audit: verify backend-aws compose wiring, docker in container, doctor:auth, report.
# Safe: never prints tokens, secrets, or expanded compose config. No docker compose config.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/ubuntu/automated-trading-platform}"
cd "$REPO_ROOT"

echo ""
echo "========== A) BASELINE (host) =========="
git branch --show-current
git log -1 --oneline
docker compose --profile aws ps 2>/dev/null || true

echo ""
echo "========== B) COMPOSE WIRING (host) — safe grep only =========="
# Read docker-compose.yml only; never run docker compose config (expands secrets).
COMPOSE_YML="$REPO_ROOT/docker-compose.yml"
check() { if grep -q "$1" "$COMPOSE_YML" 2>/dev/null; then echo "OK: $2"; else echo "MISSING: $2"; fi; }
check '/var/run/docker.sock' 'docker.sock volume'
check '/app/docker-compose.yml' 'compose file mount'
check '/app/backend/ai_runs' 'ai_runs mount'
check 'AI_ENGINE_COMPOSE_DIR' 'AI_ENGINE_COMPOSE_DIR'
check 'AI_RUNS_DIR' 'AI_RUNS_DIR'
check 'working_dir: /app/backend' 'working_dir /app/backend'

echo ""
echo "========== WAIT FOR BACKEND READY (/health 200) =========="
for i in $(seq 1 100); do
  code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 http://127.0.0.1:8002/health 2>/dev/null || echo "000")
  if [ "$code" = "200" ]; then echo "OK: /health 200"; break; fi
  if [ "$i" -eq 100 ]; then echo "FAIL: /health did not return 200 after 100 tries"; exit 1; fi
  sleep 2
done

echo ""
echo "========== C) DOCKER INSIDE CONTAINER (backend-aws) =========="
docker compose --profile aws exec -T backend-aws bash -lc '
set -e
echo "sock:"; test -S /var/run/docker.sock && echo OK || echo MISSING
echo "compose_file:"; test -f /app/docker-compose.yml && echo OK || echo MISSING
echo "ai_runs_dir:"; test -d /app/backend/ai_runs && echo OK || echo MISSING
echo "docker_cli:"; command -v docker >/dev/null && echo OK || echo MISSING
echo "docker_compose_v2:"; docker compose version >/dev/null 2>&1 && echo OK || echo MISSING
echo "compose_ps_from_/app:"; (cd /app && docker compose --profile aws ps >/dev/null 2>&1) && echo OK || echo FAIL
# Do not echo AI_ENGINE_COMPOSE_DIR or AI_RUNS_DIR values (safety).
' 2>/dev/null || true

echo ""
echo "========== D) ROUTE CHECK (host) =========="
for _ in 1 2 3; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 http://127.0.0.1:8002/api/ai/run 2>/dev/null || echo "000")
  [ -n "$code" ] && break; sleep 1
done
echo "GET /api/ai/run status: $code"
for _ in 1 2 3; do
  curl -sS --connect-timeout 5 -o /tmp/openapi.json http://127.0.0.1:8002/openapi.json 2>/dev/null && break
  sleep 1
done
python3 -c "
import json
try:
    d = json.load(open('/tmp/openapi.json'))
    paths = d.get('paths') or {}
    print('has_/api/ai/run:', '/api/ai/run' in paths)
except Exception as e:
    print('parse error:', e)
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
echo "run_dir: $RUN_DIR"

echo "Host backend/ai_runs exists:"; test -d backend/ai_runs && echo YES || echo NO

if [ -n "$RUN_DIR" ]; then
  docker compose --profile aws exec -T backend-aws python3 -c "
import json, sys, re
try:
    # run_dir may be backend/ai_runs/<id> or similar
    run_dir = '''$RUN_DIR'''.strip()
    base = '/app'
    report_path = run_dir if run_dir.startswith('/') else base + '/' + run_dir
    if not report_path.endswith('report.json'):
        report_path = report_path.rstrip('/') + '/report.json'
    with open(report_path) as f:
        r = json.load(f)
    # Support both top-level and findings.logs_excerpt
    ex = r.get('logs_excerpt') or r.get('findings', {}).get('logs_excerpt', '')
    print('tail_logs_source:', r.get('tail_logs_source'))
    print('compose_dir_used:', r.get('compose_dir_used'))
    print('logs_excerpt length:', len(ex))
    # Only print first 20 lines if they look like normal gunicorn/uvicorn lines (no tokens)
    lines = ex.splitlines()[:20]
    safe = True
    for L in lines:
        if re.search(r'(token|secret|key|password|bearer|authorization)\s*[:=]', L, re.I):
            safe = False
            break
    if safe and lines:
        for L in lines:
            print(L)
    else:
        print('logs_excerpt present (redacted)')
except Exception as e:
    print('report read error:', e)
    sys.exit(1)
" 2>/dev/null || echo "Could not read report"
fi

echo ""
echo "========== F) PASS/FAIL =========="
if [ -n "$RUN_DIR" ]; then
  docker compose --profile aws exec -T backend-aws python3 -c "
import json, sys
try:
    run_dir = '''$RUN_DIR'''.strip()
    base = '/app'
    report_path = run_dir if run_dir.startswith('/') else base + '/' + run_dir
    if not report_path.endswith('report.json'):
        report_path = report_path.rstrip('/') + '/report.json'
    with open(report_path) as f:
        r = json.load(f)
    ex = r.get('logs_excerpt') or r.get('findings', {}).get('logs_excerpt', '')
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
        if not c1: print('  - tail_logs_source != docker_compose (got: %s)' % repr(src))
        if not c2: print('  - compose_dir_used != /app (got: %s)' % repr(comp))
        if not c3: print('  - logs_excerpt contains docker-compose.yml not found')
        if not c4: print('  - logs_excerpt length <= 200 (got %s)' % len(ex))
except Exception as e:
    print('FAIL (could not read report:', e, ')')
    sys.exit(1)
" 2>/dev/null || echo "FAIL (no report or read error)"
else
  echo "FAIL (RUN_DIR empty)"
fi
