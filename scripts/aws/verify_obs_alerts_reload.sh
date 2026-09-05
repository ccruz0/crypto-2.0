#!/usr/bin/env bash
# PROD-safe: sync repo tip, rebuild telegram-alerts, reload/recreate Prometheus rules.
# No backend/frontend/trading touch.
set -euo pipefail
REPO="${ATP_REPO_ROOT:-/home/ubuntu/crypto-2.0}"
cd "$REPO"

if [ -d .git ]; then
  sudo chown -R ubuntu:ubuntu .git || true
fi

sudo -u ubuntu git -C "$REPO" fetch origin main
sudo -u ubuntu git -C "$REPO" reset --hard origin/main
echo "GIT_HEAD=$(sudo -u ubuntu git -C "$REPO" rev-parse --short HEAD)"

echo "=== alerts.yml InstanceDown (host) ==="
grep -nE 'alert: InstanceDown|for: |more than' scripts/aws/observability/alerts.yml | head -20
grep -qE 'for:[[:space:]]*15m' scripts/aws/observability/alerts.yml

test -f scripts/aws/observability/telegram-alerts/throttle.py && echo THROTTLE_FILE=ok
grep -nE 'filter_alerts_for_telegram|from throttle' scripts/aws/observability/telegram-alerts/server.py
grep -nE 'COPY .*throttle|COPY server' scripts/aws/observability/telegram-alerts/Dockerfile

echo "=== health_snapshot transient throttle ==="
grep -nE 'ATP_HEALTH_MIN_FAIL_MINUTES|transient flap|action_required_skipped' scripts/diag/health_snapshot_telegram_alert.sh | head -10 || true

echo "=== cutover TRANSIENT ==="
grep -nE 'TRANSIENT|transient_suppress' \
  scripts/aws/run_github_app_cutover_monitor_with_alerts.sh \
  scripts/aws/_github_app_cutover_alert_lib.sh 2>/dev/null | head -15 || true

echo "=== rebuild telegram-alerts ==="
docker compose --profile aws build telegram-alerts
docker compose --profile aws stop telegram-alerts || true
docker compose --profile aws rm -f telegram-alerts || true
docker ps -aq --filter name=telegram-alerts | while read -r cid; do docker rm -f "$cid" || true; done
docker compose --profile aws up -d --no-deps --force-recreate telegram-alerts
sleep 3
docker inspect -f 'telegram={{.State.Status}} running={{.State.Running}} started={{.State.StartedAt}}' atp-telegram-alerts

echo "=== prometheus reload / remount ==="
# alerts.yml entra por bind-mount DE FICHERO, que fija el inodo. git reset --hard
# reemplaza el fichero en vez de editarlo, asi que el contenedor se queda con el
# viejo para siempre y ni /-/reload ni SIGHUP lo arreglan: hay que recrearlo.
#
# La deteccion de obsolescencia era 'grep -q "for: 15m"' dentro del contenedor.
# El fichero VIEJO ya tiene for: 15m (es InstanceDown), asi que la condicion no
# se cumplia nunca y la rama de recreacion no saltaba. El 5-sep-2026 el workflow
# termino en verde DOS VECES sin desplegar tres alertas nuevas. Ese detector solo
# podia funcionar para la migracion concreta para la que se escribio.
#
# Ahora se compara el contenido real, host contra contenedor, que detecta
# cualquier cambio y no caduca. El hash se calcula en el host (docker exec cat)
# para no depender de que la imagen de Prometheus traiga md5sum.
host_alerts_md5() { md5sum scripts/aws/observability/alerts.yml | awk '{print $1}'; }
# El '|| true' no es decorativo: con set -euo pipefail, un docker exec fallido
# (contenedor caido o reiniciandose) mataria el script en la asignacion en vez de
# dejarlo llegar a la rama que lo recrea. Verificado que sin el aborta.
container_alerts_md5() { docker exec atp-prometheus cat /etc/prometheus/alerts.yml 2>/dev/null | md5sum | awk '{print $1}' || true; }

curl -sS -o /dev/null -w 'http=%{http_code}\n' -X POST http://127.0.0.1:9090/-/reload || docker kill -s HUP atp-prometheus || true
sleep 2
HOST_MD5="$(host_alerts_md5)"
CONTAINER_MD5="$(container_alerts_md5)"
echo "alerts_md5 host=${HOST_MD5} container=${CONTAINER_MD5}"
if [ "$HOST_MD5" != "$CONTAINER_MD5" ]; then
  echo "stale bind mount detected; force-recreate prometheus only"
  docker compose --profile aws up -d --no-deps --force-recreate prometheus
  sleep 5
fi

echo "=== prometheus container age ==="
docker inspect -f 'prom={{.State.Status}} started={{.State.StartedAt}}' atp-prometheus || true

echo "=== prometheus rules InstanceDown ==="
tmp=$(mktemp)
curl -sS http://127.0.0.1:9090/api/v1/rules >"$tmp"
python3 - "$tmp" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as f:
    d = json.load(f)
found = False
for g in d.get("data", {}).get("groups", []):
    for r in g.get("rules", []):
        if r.get("name") == "InstanceDown":
            found = True
            print("RULE", r.get("name"), "duration", r.get("duration"), "state", r.get("state"), "health", r.get("health"))
            # duration is seconds; 15m => 900
            if float(r.get("duration") or 0) < 900:
                raise SystemExit("InstanceDown duration still < 900s (want 15m)")
if not found:
    print("RULE InstanceDown NOT_FOUND")
    raise SystemExit(2)
PY
rm -f "$tmp"

echo "=== alerts.yml inside prometheus container ==="
docker exec atp-prometheus sh -c 'grep -nE "InstanceDown|for:" /etc/prometheus/alerts.yml | head -10'
docker exec atp-prometheus sh -c 'grep -qE "for:[[:space:]]*15m" /etc/prometheus/alerts.yml'

# Puerta dura: sin esto el workflow puede volver a decir "success" habiendo
# dejado a Prometheus con el fichero viejo. Un despliegue de alertas que miente
# es peor que uno que falla, porque nadie va a mirar.
CONTAINER_MD5="$(container_alerts_md5)"
echo "alerts_md5_final host=${HOST_MD5} container=${CONTAINER_MD5}"
if [ "$HOST_MD5" != "$CONTAINER_MD5" ]; then
  echo "FAIL: prometheus sigue sirviendo un alerts.yml distinto al del host"
  exit 1
fi
echo DONE_OBS_VERIFY
