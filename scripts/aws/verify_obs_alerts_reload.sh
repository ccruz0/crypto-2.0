#!/usr/bin/env bash
# PROD-safe: sync repo tip, rebuild telegram-alerts, reload Prometheus rules.
# No backend/frontend/trading touch.
set -euo pipefail
REPO="${ATP_REPO_ROOT:-/home/ubuntu/crypto-2.0}"
cd "$REPO"

sudo -u ubuntu git -C "$REPO" fetch origin main
sudo -u ubuntu git -C "$REPO" reset --hard origin/main
echo "GIT_HEAD=$(sudo -u ubuntu git -C "$REPO" rev-parse --short HEAD)"

echo "=== alerts.yml InstanceDown ==="
grep -nE 'alert: InstanceDown|for: |more than' scripts/aws/observability/alerts.yml | head -20

test -f scripts/aws/observability/telegram-alerts/throttle.py && echo THROTTLE_FILE=ok
grep -nE 'filter_alerts_for_telegram|from throttle' scripts/aws/observability/telegram-alerts/server.py
grep -nE 'COPY .*throttle|COPY server' scripts/aws/observability/telegram-alerts/Dockerfile

echo "=== health_snapshot transient throttle ==="
grep -nE 'ATP_HEALTH_MIN_FAIL_MINUTES|transient flap|action_required_skipped' scripts/diag/health_snapshot_telegram_alert.sh | head -10

echo "=== cutover TRANSIENT ==="
grep -nE 'TRANSIENT|transient_suppress' \
  scripts/aws/run_github_app_cutover_monitor_with_alerts.sh \
  scripts/aws/_github_app_cutover_alert_lib.sh 2>/dev/null | head -15 || true

echo "=== rebuild telegram-alerts ==="
docker compose --profile aws build telegram-alerts
docker compose --profile aws up -d --no-deps telegram-alerts
sleep 3
docker inspect -f '{{.State.Status}} {{.State.Running}}' atp-telegram-alerts

echo "=== prometheus reload ==="
if ! curl -sS -o /dev/null -w 'http=%{http_code}\n' -X POST http://127.0.0.1:9090/-/reload; then
  echo "curl reload failed; sending HUP"
  docker kill -s HUP atp-prometheus
fi
sleep 2

echo "=== prometheus rules InstanceDown ==="
curl -sS http://127.0.0.1:9090/api/v1/rules | python3 - <<'PY'
import sys, json
d = json.load(sys.stdin)
for g in d.get("data", {}).get("groups", []):
    for r in g.get("rules", []):
        if r.get("name") == "InstanceDown":
            print("RULE", r.get("name"), "duration", r.get("duration"), "state", r.get("state"), "health", r.get("health"))
PY

echo "=== alerts.yml inside prometheus container ==="
docker exec atp-prometheus sh -c 'grep -nE "InstanceDown|for:" /etc/prometheus/alerts.yml | head -10'
echo DONE_OBS_VERIFY
