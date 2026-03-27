#!/usr/bin/env bash
# Forensic: Find exact source of old Telegram /task response on PROD.
#
# Run via SSM:
#   aws ssm send-command --instance-ids i-087953603011543c5 --document-name AWS-RunShellScript \
#     --parameters 'commands=["cd /home/ubuntu/crypto-2.0 2>/dev/null || cd /home/ubuntu/crypto-2.0 || true","bash scripts/aws/forensic_telegram_task_runtime.sh"]' \
#     --region ap-southeast-1 --timeout-seconds 120
#
# Target string: "This task has low impact and was not created"

set -euo pipefail

REPO="${1:-/home/ubuntu/crypto-2.0}"
[[ -d "$REPO" ]] || REPO="/home/ubuntu/crypto-2.0"
cd "$REPO" 2>/dev/null || { echo "Repo not found"; exit 1; }

OLD_STR="low impact and was not created"
OLD_TAIL="clarify urgency or impact"

echo "=== FORENSIC: Telegram /task old message source ==="
echo ""

# 1. Active Telegram runtime
echo "--- 1. ACTIVE TELEGRAM RUNTIME ---"
backend_c=$(docker ps --format '{{.Names}}' 2>/dev/null | grep 'backend-aws' | grep -v canary | head -1)
if [[ -z "$backend_c" ]]; then
  echo "  backend-aws container not found"
else
  echo "  container: $backend_c"
  echo "  image: $(docker inspect "$backend_c" --format '{{.Config.Image}}' 2>/dev/null || echo 'N/A')"
  echo "  image_id: $(docker inspect "$backend_c" --format '{{.Image}}' 2>/dev/null || echo 'N/A')"
  echo "  created: $(docker inspect "$backend_c" --format '{{.Created}}' 2>/dev/null || echo 'N/A')"
  echo "  RUN_TELEGRAM_POLLER: $(docker exec "$backend_c" printenv RUN_TELEGRAM_POLLER 2>/dev/null || echo 'N/A')"
  echo "  hostname: $(docker exec "$backend_c" hostname 2>/dev/null || echo 'N/A')"
  echo "  bind mounts:"
  docker inspect "$backend_c" --format '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' 2>/dev/null | sed 's/^/    /' || echo "    (none)"
fi
echo ""

# 2. Search HOST filesystem (repo, backups, old deploys)
echo "--- 2. SEARCH HOST FILESYSTEM FOR OLD STRING ---"
for dir in "$REPO" /home/ubuntu/crypto-2.0 /home/ubuntu/crypto-2.0; do
  [[ -d "$dir" ]] || continue
  echo "  Searching $dir ..."
  found=$(grep -r -l --include="*.py" -e "$OLD_STR" -e "$OLD_TAIL" "$dir" 2>/dev/null || true)
  if [[ -n "$found" ]]; then
    echo "  FOUND in:"
    echo "$found" | while read -r f; do
      echo "    $f"
      grep -n -e "$OLD_STR" -e "$OLD_TAIL" "$f" 2>/dev/null | head -5
    done
  fi
done
echo ""

# 3. Search INSIDE container
echo "--- 3. SEARCH INSIDE backend-aws CONTAINER ---"
if [[ -n "${backend_c:-}" ]]; then
  found_in_container=$(docker exec "$backend_c" grep -r -l --include="*.py" -e "$OLD_STR" -e "$OLD_TAIL" /app 2>/dev/null || true)
  if [[ -n "$found_in_container" ]]; then
    echo "  FOUND in container:"
    echo "$found_in_container"
  else
    echo "  NOT FOUND in /app (container)"
  fi
fi
echo ""

# 4. Python forensic script (prefer host copy so we run latest; fallback to container)
echo "--- 4. PYTHON RUNTIME INSPECTION ---"
if [[ -n "${backend_c:-}" ]]; then
  if [[ -f "$REPO/backend/scripts/diag/forensic_telegram_task_source.py" ]]; then
    docker cp "$REPO/backend/scripts/diag/forensic_telegram_task_source.py" "$backend_c:/tmp/forensic_task.py" 2>/dev/null && \
      docker exec "$backend_c" python /tmp/forensic_task.py 2>/dev/null || echo "  (copy/run failed)"
  else
    docker exec "$backend_c" python /app/scripts/diag/forensic_telegram_task_source.py 2>/dev/null || echo "  (script not in container - run git pull first)"
  fi
fi
echo ""

# 5. Image build context
echo "--- 5. IMAGE vs REPO ---"
if [[ -n "${backend_c:-}" ]]; then
  img_id=$(docker inspect "$backend_c" --format '{{.Image}}' 2>/dev/null)
  echo "  container image id: $img_id"
  echo "  repo backend task_compiler.py first 5 lines:"
  head -5 "$REPO/backend/app/services/task_compiler.py" 2>/dev/null || echo "  (file not found)"
  echo "  container task_compiler.py first 5 lines:"
  docker exec "$backend_c" head -5 /app/app/services/task_compiler.py 2>/dev/null || echo "  (not found)"
fi
echo ""

# 6. All containers that might have Telegram
echo "--- 6. ALL CONTAINERS WITH TELEGRAM ENV ---"
for c in $(docker ps --format '{{.Names}}' 2>/dev/null); do
  has_tg=$(docker exec "$c" printenv 2>/dev/null | grep -E '^TELEGRAM_BOT_TOKEN|^TELEGRAM_ATP_CONTROL' | head -1 || true)
  if [[ -n "$has_tg" ]]; then
    echo "  $c: has Telegram env"
    run_poller=$(docker exec "$c" printenv RUN_TELEGRAM_POLLER 2>/dev/null || echo "unset")
    echo "    RUN_TELEGRAM_POLLER=$run_poller"
  fi
done 2>/dev/null || true
echo ""

echo "=== END FORENSIC ==="
