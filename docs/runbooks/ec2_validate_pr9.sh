#!/usr/bin/env bash
set -euo pipefail

echo "=== 0) Host sanity ==="
whoami || true
uname -a || true
pwd || true
echo

REPO_DIR="/home/ubuntu/automated-trading-platform"

if [[ ! -d "$REPO_DIR" ]]; then
  echo "ERROR: Expected EC2 repo dir not found: $REPO_DIR"
  echo "You are probably not on EC2."
  exit 2
fi

cd "$REPO_DIR"

echo "=== 1) Git main ==="
git fetch origin
git checkout main
git pull --ff-only origin main
MAIN_HEAD="$(git rev-parse HEAD)"
echo "main HEAD: $MAIN_HEAD"
echo

echo "=== 2) Deploy backend-aws ==="
docker compose --profile aws build --no-cache backend-aws
docker compose --profile aws up -d backend-aws
PS_LINE="$(docker compose --profile aws ps --format '{{.Name}} {{.Status}}' | head -1 || true)"
echo "compose ps (backend-aws): ${PS_LINE:-"(empty)"}"
echo

echo "=== 3) Health ==="
HEALTH_CODE="$(curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8002/api/health || true)"
echo "health: ${HEALTH_CODE:-"(empty)"}"
echo

echo "=== 4) OpenAPI path check (/api/ai/run) ==="
OPENAPI_OK="$(curl -sS http://127.0.0.1:8002/openapi.json | python3 -c 'import json,sys; j=json.load(sys.stdin); print("/api/ai/run" in (j.get("paths") or {}))' 2>/dev/null || echo "False")"
echo "openapi_has_/api/ai/run: $OPENAPI_OK"
echo

echo "=== 5) doctor:sltp ==="
curl -sS -X POST http://127.0.0.1:8002/api/ai/run \
  -H "Content-Type: application/json" \
  -d '{"task":"doctor:sltp","mode":"sandbox","apply_changes":false}' \
  | python3 -m json.tool > /tmp/doctor.json

python3 - <<'PY'
import json,glob,sys
r = json.load(open("/tmp/doctor.json"))
print("doctor_json_keys:", sorted(list(r.keys()))[:20])

paths = sorted(glob.glob("backend/ai_runs/*/report.json"))
if not paths:
  print("NO_REPORT")
  sys.exit(3)

rep = json.load(open(paths[-1]))
ex = ((rep.get("findings") or {}).get("logs_excerpt") or "")
print("tail_logs_source:", rep.get("tail_logs_source"))
print("compose_dir_used:", rep.get("compose_dir_used"))
print("logs_excerpt_len:", len(ex))
print("payload_numeric_validation:", rep.get("payload_numeric_validation"))
print("scientific_notation_detected:", rep.get("scientific_notation_detected"))
print("environment_mismatch_detected:", rep.get("environment_mismatch_detected"))
print('compose_not_found:', ("docker-compose.yml not found" in ex))
PY
echo

echo "=== 6) Tests (container) ==="
set +e
docker compose --profile aws exec -T backend-aws bash -lc '
pip install -q pytest 2>/dev/null
cd /app
python -m pytest -q tests/test_crypto_com_sltp_140001_fallback.py tests/test_exchange_formatting_week6.py
'
TEST_EXIT=$?
echo "$TEST_EXIT" > /tmp/ec2_validate_tests_exit
set -e
if [[ $TEST_EXIT -eq 0 ]]; then
  TESTS_STATUS="passed"
else
  TESTS_STATUS="failed"
fi
echo "tests: $TESTS_STATUS"
echo

echo "=== 7) Evidence block ==="
python3 - <<'PY'
import json,glob,subprocess

def sh(cmd):
  return subprocess.check_output(cmd, shell=True, text=True).strip()

head = sh("git rev-parse HEAD")
ps_line = sh("docker compose --profile aws ps --format '{{.Name}} {{.Status}}' | head -1 || true")
health = sh("curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8002/api/health || true")

paths = sorted(glob.glob("backend/ai_runs/*/report.json"))
rep = json.load(open(paths[-1])) if paths else {}
ex = ((rep.get("findings") or {}).get("logs_excerpt") or "")

tail_logs_source = rep.get("tail_logs_source")
compose_dir_used = rep.get("compose_dir_used")
logs_excerpt_len = len(ex)
payload_numeric_validation = rep.get("payload_numeric_validation")
scientific_notation_detected = rep.get("scientific_notation_detected")
environment_mismatch_detected = rep.get("environment_mismatch_detected")
compose_not_found = ("docker-compose.yml not found" in ex)

print(f"main HEAD: {head}")
print(f"compose ps (backend-aws): {ps_line}")
print(f"health: {health}")
print(f"tail_logs_source: {tail_logs_source}")
print(f"compose_dir_used: {compose_dir_used}")
print(f"logs_excerpt_len: {logs_excerpt_len}")
print(f"payload_numeric_validation: {payload_numeric_validation}")
print(f"scientific_notation_detected: {scientific_notation_detected}")
print(f"environment_mismatch_detected: {environment_mismatch_detected}")
print(f"compose_not_found: {compose_not_found}")
PY

echo
echo "=== 8) OVERALL PASS/FAIL ==="
# Recompute a strict pass/fail gate from report + health + openapi + tests
python3 - <<'PY'
import json,glob,subprocess,sys

def sh(cmd):
  return subprocess.check_output(cmd, shell=True, text=True).strip()

health = sh("curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8002/api/health || true")
openapi_ok = sh("curl -sS http://127.0.0.1:8002/openapi.json | python3 -c 'import json,sys; j=json.load(sys.stdin); print(\"/api/ai/run\" in (j.get(\"paths\") or {}))' 2>/dev/null || echo False")

paths = sorted(glob.glob("backend/ai_runs/*/report.json"))
rep = json.load(open(paths[-1])) if paths else {}
ex = ((rep.get("findings") or {}).get("logs_excerpt") or "")

tail_logs_source = rep.get("tail_logs_source")
compose_dir_used = rep.get("compose_dir_used")
logs_excerpt_len = len(ex)
compose_not_found = ("docker-compose.yml not found" in ex)

try:
  with open("/tmp/ec2_validate_tests_exit") as f:
    tests_ok = (f.read().strip() == "0")
except Exception:
  tests_ok = False

pass_all = (
  str(health).strip() == "200"
  and str(openapi_ok).strip() == "True"
  and tail_logs_source == "docker_compose"
  and compose_dir_used == "/app"
  and logs_excerpt_len > 200
  and (not compose_not_found)
  and tests_ok
)

print("OVERALL:", "PASS" if pass_all else "FAIL")
if not pass_all:
  print("Failed conditions:")
  if str(health).strip() != "200": print("- health != 200")
  if str(openapi_ok).strip() != "True": print("- openapi missing /api/ai/run")
  if tail_logs_source != "docker_compose": print("- tail_logs_source != docker_compose")
  if compose_dir_used != "/app": print("- compose_dir_used != /app")
  if logs_excerpt_len <= 200: print("- logs_excerpt_len <= 200")
  if compose_not_found: print('- logs_excerpt contains "docker-compose.yml not found"')
PY

echo
echo "If FAIL and you need logs:"
echo "cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs --tail=120 backend-aws"
