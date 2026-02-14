#!/usr/bin/env bash
# Option A one-shot verification on EC2. Safe: no secrets, no expanded compose config.
# Run: cd /home/ubuntu/automated-trading-platform && bash scripts/aws/option_a_verify_ec2.sh
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/home/ubuntu/automated-trading-platform}"
cd "$REPO_ROOT"

# Retry curl until success or max attempts (connection reset / not ready)
curl_retry() {
  local url="$1"
  local max="${2:-5}"
  local i=1
  while [ "$i" -le "$max" ]; do
    if curl -sS --connect-timeout 10 --max-time 30 "$url" 2>/dev/null; then
      return 0
    fi
    sleep 2
    i=$((i + 1))
  done
  return 1
}

echo "=== 1) Build + restart backend-aws ==="
docker compose --profile aws build --no-cache backend-aws
docker compose --profile aws up -d backend-aws
docker compose --profile aws ps

echo ""
echo "=== 2) Wait for /health 200 (retry up to 30 times, 2s sleep) ==="
i=1
while [ "$i" -le 30 ]; do
  code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 http://127.0.0.1:8002/api/health 2>/dev/null) || code=""
  if [ "$code" = "200" ]; then
    echo "health: 200"
    break
  fi
  sleep 2
  i=$((i + 1))
done
if [ "$code" != "200" ]; then
  echo "WARN: /health did not return 200 after 60s"
fi

echo ""
echo "=== 3) Inside container — presence only (OK/MISSING) ==="
docker compose --profile aws exec -T backend-aws bash -lc '
test -S /var/run/docker.sock && echo "OK: docker.sock volume" || echo "MISSING: docker.sock volume"
test -f /app/docker-compose.yml && echo "OK: compose file" || echo "MISSING: compose file"
test -d /app/backend/ai_runs && echo "OK: ai_runs dir" || echo "MISSING: ai_runs dir"
command -v docker >/dev/null && echo "OK: docker CLI" || echo "MISSING: docker CLI"
docker compose version >/dev/null 2>&1 && echo "OK: docker compose version" || echo "MISSING: docker compose version"
(cd /app && docker compose --profile aws ps >/dev/null 2>&1) && echo "OK: compose ps from /app" || echo "FAIL: compose ps from /app"
' 2>/dev/null || true

echo ""
echo "=== 4) Route check ==="
code=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 http://127.0.0.1:8002/api/ai/run 2>/dev/null) || code=""
echo "GET /api/ai/run HTTP code: ${code:-unknown}"
curl_retry "http://127.0.0.1:8002/openapi.json" 3 > /tmp/openapi.json 2>/dev/null || true
python3 -c "
import json
try:
    d = json.load(open('/tmp/openapi.json'))
    print('openapi has_/api/ai/run:', '/api/ai/run' in (d.get('paths') or {}))
except Exception:
    print('openapi has_/api/ai/run: False')
" 2>/dev/null || true

echo ""
echo "=== 5) Run doctor:auth ==="
curl -sS -X POST http://127.0.0.1:8002/api/ai/run \
  -H "Content-Type: application/json" \
  -d '{"task":"doctor:auth","mode":"sandbox","apply_changes":false}' \
  -o /tmp/doctor_auth.json 2>/dev/null || true
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

echo ""
echo "=== 6) Report fields (safe only) ==="
if [ -n "$RUN_DIR" ]; then
  docker compose --profile aws exec -T backend-aws python3 -c "
import json, os, sys
run_dir = '''$RUN_DIR'''.strip()
report_path = os.path.join('/app', run_dir, 'report.json')
if not os.path.isfile(report_path):
  base = '/app/backend/ai_runs'
  if os.path.isdir(base):
    dirs = [os.path.join(base, d) for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
    if dirs:
      latest = max(dirs, key=os.path.getmtime)
      report_path = os.path.join(latest, 'report.json')
if not os.path.isfile(report_path):
  print('report.json not found')
  sys.exit(0)
r = json.load(open(report_path))
findings = r.get('findings') or {}
ex = findings.get('logs_excerpt') or r.get('logs_excerpt') or ''
src = r.get('tail_logs_source')
comp = r.get('compose_dir_used')
print('tail_logs_source:', src)
print('compose_dir_used:', comp)
print('logs_excerpt length:', len(ex))
# First 20 lines only if safe (gunicorn/uvicorn-like; no token-like content)
unsafe = any(x in ex.lower() for x in ('token', 'secret', 'key=', 'password', 'authorization', 'bearer ', 'api_key'))
lines = ex.splitlines()[:20]
safe_line = lambda s: not any(x in s.lower() for x in ('token', 'secret', 'password', 'bearer', 'api_key', 'credential'))
if not unsafe and all(safe_line(l) for l in lines if l.strip()):
  for line in lines:
    print(line)
else:
  print('logs_excerpt present (redacted)')
" 2>/dev/null || true
else
  echo "run_dir empty; skip report"
fi

echo ""
echo "=== 7) PASS/FAIL ==="
if [ -n "$RUN_DIR" ]; then
  docker compose --profile aws exec -T backend-aws python3 -c "
import json, os
run_dir = '''$RUN_DIR'''.strip()
report_path = os.path.join('/app', run_dir, 'report.json')
if not os.path.isfile(report_path):
  base = '/app/backend/ai_runs'
  if os.path.isdir(base):
    dirs = [os.path.join(base, d) for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
    if dirs:
      latest = max(dirs, key=os.path.getmtime)
      report_path = os.path.join(latest, 'report.json')
if report_path and os.path.isfile(report_path):
  r = json.load(open(report_path))
  findings = r.get('findings') or {}
  ex = findings.get('logs_excerpt') or r.get('logs_excerpt') or ''
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
    if not c1: print('  tail_logs_source != docker_compose (got:', repr(src), ')')
    if not c2: print('  compose_dir_used != /app (got:', repr(comp), ')')
    if not c3: print('  logs_excerpt contains \"docker-compose.yml not found\"')
    if not c4: print('  len(logs_excerpt) <= 200 (got', len(ex), ')')
  print('tail_logs_source:', src)
  print('compose_dir_used:', comp)
  print('logs_excerpt length:', len(ex))
else:
  print('OPTION A — FAIL (no report.json found)')
" 2>/dev/null || echo "OPTION A — FAIL (script error)"
else
  echo "OPTION A — FAIL (no run_dir)"
fi
