#!/usr/bin/env bash
# Option A EC2 audit: verify backend-aws compose wiring, docker in container, doctor:auth, report.
# Safe: never prints tokens, secrets, or env file contents.
set -euo pipefail

REPO_ROOT="/home/ubuntu/automated-trading-platform"
cd "$REPO_ROOT"
echo "REPO_ROOT=$REPO_ROOT"

echo ""
echo "========== A) BASELINE (host) =========="
git branch --show-current
git log -3 --oneline
docker compose --profile aws ps

echo ""
echo "========== B) COMPOSE WIRING (host) =========="
docker compose --profile aws config > /tmp/compose.aws.config
echo "--- backend-aws service block ---"
awk '/^  backend-aws:/{f=1} f{print} /^  [a-z].*:/ && !/^  backend-aws:/{if(f) exit}' /tmp/compose.aws.config || true
echo "--- grep: socket, :/app:ro, AI_ENGINE_COMPOSE_DIR, AI_RUNS_DIR, ai_runs, working_dir ---"
grep -E '/var/run/docker\.sock|\.:/app:ro|AI_ENGINE_COMPOSE_DIR|AI_RUNS_DIR|/app/backend/ai_runs|working_dir|backend/ai_runs' /tmp/compose.aws.config || true

echo ""
echo "========== C) DOCKER INSIDE CONTAINER (backend-aws) =========="
docker compose --profile aws exec -T backend-aws bash -lc '
set -e
echo "== inside container =="
whoami
pwd
ls -la /var/run/docker.sock || true
echo "AI_ENGINE_COMPOSE_DIR=$AI_ENGINE_COMPOSE_DIR"
echo "AI_RUNS_DIR=$AI_RUNS_DIR"
test -f /app/docker-compose.yml && echo "compose file OK: /app/docker-compose.yml" || echo "compose file MISSING at /app/docker-compose.yml"
docker version || true
docker compose version || true
cd /app
docker compose --profile aws ps || true
' || true

echo ""
echo "========== D) ROUTE CHECK (host) =========="
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8002/api/ai/run || true
curl -sS -D /tmp/openapi.headers -o /tmp/openapi.json http://127.0.0.1:8002/openapi.json || true
echo "--- openapi headers (first 10 lines) ---"
head -10 /tmp/openapi.headers || true
echo "--- openapi paths ---"
python3 -c "
import json
try:
    d = json.load(open('/tmp/openapi.json'))
    paths = d.get('paths') or {}
    print('num_paths:', len(paths))
    print('has_/api/ai/run:', '/api/ai/run' in paths)
    ai = [p for p in paths if 'ai' in p or 'doctor' in p]
    print('paths containing ai or doctor:', ai)
except Exception as e:
    print('parse error:', e)
" || true

echo ""
echo "========== E) DOCTOR AUTH + REPORT CHECK =========="
curl -sS -X POST http://127.0.0.1:8002/api/ai/run \
  -H "Content-Type: application/json" \
  -d '{"task":"doctor:auth","mode":"sandbox","apply_changes":false}' \
  -o /tmp/doctor_auth.json || true
python3 -m json.tool < /tmp/doctor_auth.json 2>/dev/null || cat /tmp/doctor_auth.json

RUN_DIR=$(python3 -c "
import json
try:
    r = json.load(open('/tmp/doctor_auth.json'))
    d = r.get('run_dir', '')
    print(d.replace('/app/', '', 1) if d.startswith('/app/') else d)
except Exception:
    print('')
") || RUN_DIR=""
echo "RUN_DIR=$RUN_DIR"

echo "--- host: backend/ai_runs and RUN_DIR ---"
ls -la backend/ai_runs 2>/dev/null || true
[ -n "$RUN_DIR" ] && ls -la "$RUN_DIR" 2>/dev/null || true

echo "--- container: /app/backend/ai_runs and /app/RUN_DIR ---"
docker compose --profile aws exec -T backend-aws ls -la /app/backend/ai_runs 2>/dev/null || true
[ -n "$RUN_DIR" ] && docker compose --profile aws exec -T backend-aws ls -la "/app/$RUN_DIR" 2>/dev/null || true

echo "--- report.json (tail_logs_source, compose_dir_used, logs_excerpt len, first 40 lines of file) ---"
if [ -n "$RUN_DIR" ]; then
  docker compose --profile aws exec -T backend-aws cat "/app/$RUN_DIR/report.json" 2>/dev/null | python3 -c "
import json, sys
try:
    r = json.load(sys.stdin)
    print('tail_logs_source:', r.get('tail_logs_source'))
    print('compose_dir_used:', r.get('compose_dir_used'))
    ex = r.get('findings', {}).get('logs_excerpt', '')
    print('logs_excerpt length:', len(ex))
    print('--- first 40 lines of report.json ---')
    raw = json.dumps(r, indent=2)
    for i, line in enumerate(raw.splitlines()[:40]):
        print(line)
    print('--- logs_excerpt (capped 4000 chars) ---')
    print(ex[:4000])
except Exception as e:
    print('parse error:', e)
    sys.exit(1)
" || true
else
  echo "RUN_DIR empty, skip report"
fi

echo ""
echo "========== F) PASS/FAIL =========="
if [ -n "$RUN_DIR" ]; then
  docker compose --profile aws exec -T backend-aws cat "/app/$RUN_DIR/report.json" 2>/dev/null | python3 -c "
import json, sys
try:
    r = json.load(sys.stdin)
    src = r.get('tail_logs_source')
    comp = r.get('compose_dir_used')
    ex = r.get('findings', {}).get('logs_excerpt', '')
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
" || echo "FAIL (no report or read error)"
else
  echo "FAIL (RUN_DIR empty)"
fi
