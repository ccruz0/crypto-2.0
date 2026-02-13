#!/usr/bin/env bash
# Option A one-shot verification on EC2. Safe: no secrets, no expanded compose config.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/ubuntu/automated-trading-platform}"
cd "$REPO_ROOT"

echo "=== 1) Build + restart backend-aws ==="
docker compose --profile aws build --no-cache backend-aws
docker compose --profile aws up -d backend-aws
docker compose --profile aws ps

echo ""
echo "=== 2) Wait for /health == 200 (retry up to 30 x 2s) ==="
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 2 http://127.0.0.1:8002/health 2>/dev/null || echo "000")
  if [ "$code" = "200" ]; then echo "OK: /health 200"; break; fi
  if [ "$i" -eq 30 ]; then echo "FAIL: /health did not return 200"; exit 1; fi
  sleep 2
done

echo ""
echo "=== 3) Container checks (OK/MISSING) ==="
docker compose --profile aws exec -T backend-aws bash -lc '
test -S /var/run/docker.sock && echo "docker.sock: OK" || echo "docker.sock: MISSING"
test -f /app/docker-compose.yml && echo "compose_file: OK" || echo "compose_file: MISSING"
test -d /app/backend/ai_runs && echo "ai_runs_dir: OK" || echo "ai_runs_dir: MISSING"
command -v docker >/dev/null && echo "docker_cli: OK" || echo "docker_cli: MISSING"
docker compose version >/dev/null 2>&1 && echo "docker_compose_v2: OK" || echo "docker_compose_v2: MISSING"
(cd /app && docker compose --profile aws ps >/dev/null 2>&1) && echo "compose_ps_from_/app: OK" || echo "compose_ps_from_/app: FAIL"
' 2>/dev/null || true

echo ""
echo "=== 4) Route check ==="
for _ in 1 2 3; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 http://127.0.0.1:8002/api/ai/run 2>/dev/null || echo "000")
  [ -n "$code" ] && break; sleep 1
done
echo "GET /api/ai/run HTTP code: $code"
for _ in 1 2 3; do
  curl -sS --connect-timeout 5 -o /tmp/openapi.json http://127.0.0.1:8002/openapi.json 2>/dev/null && break
  sleep 1
done
python3 -c "
import json
try:
    j=json.load(open('/tmp/openapi.json'))
    print('openapi has /api/ai/run:', '/api/ai/run' in (j.get('paths') or {}))
except Exception: print('openapi has /api/ai/run: False')
" 2>/dev/null || true

echo ""
echo "=== 5) doctor:auth — run_dir only ==="
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
    d=json.load(open('/tmp/doctor_auth.json'))
    print(d.get('run_dir',''))
except Exception: print('')
" 2>/dev/null) || RUN_DIR=""
echo "run_dir: $RUN_DIR"

echo ""
echo "=== 6) Report fields (safe only) ==="
if [ -n "$RUN_DIR" ]; then
  docker compose --profile aws exec -T backend-aws python3 -c "
import json, re, sys
run_dir = '''$RUN_DIR'''.strip()
base = '/app'
path = (run_dir if run_dir.startswith('/') else base + '/' + run_dir).rstrip('/') + '/report.json'
try:
    with open(path) as f:
        r = json.load(f)
    ex = r.get('logs_excerpt') or r.get('findings', {}).get('logs_excerpt', '')
    print('tail_logs_source:', r.get('tail_logs_source'))
    print('compose_dir_used:', r.get('compose_dir_used'))
    print('logs_excerpt length:', len(ex))
    lines = ex.splitlines()[:20]
    safe = not any(re.search(r'(token|secret|key|password|bearer|authorization)\s*[:=]', L, re.I) for L in lines)
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
echo "=== 7) PASS/FAIL ==="
if [ -n "$RUN_DIR" ]; then
  docker compose --profile aws exec -T backend-aws python3 -c "
import json, sys
run_dir = '''$RUN_DIR'''.strip()
base = '/app'
path = (run_dir if run_dir.startswith('/') else base + '/' + run_dir).rstrip('/') + '/report.json'
try:
    with open(path) as f:
        r = json.load(f)
    ex = r.get('logs_excerpt') or r.get('findings', {}).get('logs_excerpt', '')
    src = r.get('tail_logs_source')
    comp = r.get('compose_dir_used')
    c1 = src == 'docker_compose'
    c2 = comp == '/app'
    c3 = 'docker-compose.yml not found' not in ex
    c4 = len(ex) > 200
    if c1 and c2 and c3 and c4:
        print('OPTION A VERIFIED END-TO-END — PASS')
    else:
        print('OPTION A — FAIL')
        if not c1: print('  tail_logs_source != docker_compose (got: %s)' % repr(src))
        if not c2: print('  compose_dir_used != /app (got: %s)' % repr(comp))
        if not c3: print('  logs_excerpt contains docker-compose.yml not found')
        if not c4: print('  len(logs_excerpt) <= 200 (got %s)' % len(ex))
    print('tail_logs_source:', src)
    print('compose_dir_used:', comp)
    print('logs_excerpt length:', len(ex))
except Exception as e:
    print('OPTION A — FAIL (report error:', e, ')')
    sys.exit(1)
" 2>/dev/null || echo "OPTION A — FAIL (could not read report)"
else
  echo "OPTION A — FAIL (no run_dir)"
fi
