# Phase 7 — Observability (golden signals + alerts)

**Scope:** Prometheus scraping (node, cadvisor, backend, market-updater), alert rules, backend request metrics + slow-call logs, market-updater heartbeat, log retention.

---

## What was added

- **Prometheus** (127.0.0.1:9090): scrapes node-exporter, cadvisor, backend `/api/metrics`, market-updater `/metrics`. Config: `scripts/aws/observability/prometheus.yml`. Alert rules: `scripts/aws/observability/alerts.yml`.
- **Grafana** (127.0.0.1:3001): unchanged bind; image bumped to 10.4.1.
- **Backend:** `prometheus-client`, `/api/metrics` endpoint, `PromMetricsMiddleware` (request count, latency histograms, SLOW_CALL log above 800 ms).
- **Market-updater:** Prometheus gauge `market_updater_heartbeat_age_seconds`, HTTP server on port **9101** (container-only; no host bind) serving `/metrics`, `record_heartbeat()` after each successful update.

---

## Alert rules (alerts.yml)

| Alert | Condition | Severity |
|-------|-----------|----------|
| InstanceDown | `up == 0` for 2m | critical |
| HostDiskFillingUp | disk &lt; 15% for 10m | warning |
| ContainerRestartsHigh | cadvisor restarts in 15m | warning |
| BackendHigh5xxRate | 5xx rate &gt; 2% for 5m | critical |
| BackendP95LatencyHigh | p95 &gt; 800 ms for 10m | warning |
| MarketUpdaterStalled | heartbeat age &gt; 15m for 5m | warning |
| TestTelegramAlert | `vector(1)` for 10s (e2e test) | warning |

---

## Phase 7.1 — Telegram alerts via Alertmanager

- **Alertmanager** (127.0.0.1:9093): receives alerts from Prometheus, routes to Telegram webhook relay. Config: `scripts/aws/observability/alertmanager.yml`.
- **telegram-alerts**: small Flask app that receives Alertmanager webhooks and sends messages via Telegram Bot API. No secrets in git; env from `.env.aws` / `secrets/runtime.env`.

**Secrets on EC2 (do not commit):** In `secrets/runtime.env` set:

In `secrets/runtime.env` set `TELEGRAM_ALERT_BOT_TOKEN` and `TELEGRAM_ALERT_CHAT_ID` (values only on EC2, never in git).

**EC2 run (Phase 7.1):**

```bash
cd /home/ubuntu/automated-trading-platform
git pull --ff-only
docker compose --profile aws build --no-cache telegram-alerts backend-aws market-updater-aws
docker compose --profile aws up -d prometheus grafana alertmanager telegram-alerts
docker compose --profile aws up -d db backend-aws market-updater-aws frontend-aws
```

**One end-to-end test:** After ~30–60s you should receive a Telegram message for `TestTelegramAlert`. Confirm with:

```bash
curl -fsS http://127.0.0.1:9090/api/v1/alerts | jq '.data.alerts[] | select(.labels.alertname=="TestTelegramAlert") | .state'
```

Once verified, you can remove or disable the `TestTelegramAlert` rule in `alerts.yml` if you do not want it to repeat every 2h.

---

## Log retention and slow-call signals

### Docker daemon (container logs)

On the host, configure json-file driver with rotation (apply in a maintenance window; restarts Docker):

**`/etc/docker/daemon.json`** (merge with existing keys if present):

```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  }
}
```

Then: `sudo systemctl restart docker`. Containers will restart.

### Journald (systemd logs)

**`/etc/systemd/journald.conf`** — set:

- `SystemMaxUse=1G`
- `MaxRetentionSec=14day`

Then: `sudo systemctl restart systemd-journald`.

### Slow-call logs

Backend logs a line when a request exceeds 800 ms:

- Format: `SLOW_CALL <path> <status> <method> <elapsed_ms>ms`
- No metric increment beyond the existing latency histogram; use for log-based inspection or alerting.

---

## Verification checklist

1. **Prometheus targets**
   - Open `http://127.0.0.1:9090/targets` (via SSH tunnel if needed). All targets **UP**: node, cadvisor, backend, market_updater.

2. **Backend metrics**
   - Hit any API endpoint a few times, then:
   - `curl -s http://127.0.0.1:8002/api/metrics | grep http_requests_total`
   - `curl -s http://127.0.0.1:8002/api/metrics | grep http_request_duration_seconds_bucket`

3. **Market-updater metrics**
   - `curl -s http://127.0.0.1:8002/api/metrics` is backend; from another container or host that can reach market-updater: `curl -s http://market-updater-aws:8002/metrics` (or from host if you expose 8004:8002 for testing). Expect `market_updater_heartbeat_age_seconds`.

4. **Alerts**
   - Stop backend container; within ~2m, Prometheus Alerts page should show **InstanceDown** for job=backend.

5. **No public ports**
   - `ss -ltnp | grep -E '9090|3001'` — only 127.0.0.1. Phase F remains satisfied.

---

## EC2 verification checklist

```bash
cd /home/ubuntu/automated-trading-platform
git pull --ff-only

# Rebuild the images that changed (backend + updater)
docker compose --profile aws build --no-cache backend-aws market-updater-aws

# Bring up monitoring stack
docker compose --profile aws up -d prometheus grafana

# Restart app containers
docker compose --profile aws up -d db backend-aws market-updater-aws frontend-aws

# Targets
curl -fsS http://127.0.0.1:9090/api/v1/targets | jq -r '.data.activeTargets[] | "\(.labels.job)\t\(.health)\t\(.lastError)"'

# Backend metrics
curl -fsS http://127.0.0.1:8002/api/metrics | egrep -m 5 'http_requests_total|http_request_duration'

# Market updater metrics (via Prometheus query)
curl -fsS http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=market_updater_heartbeat_age_seconds' | jq .
```

**What you should see:**

- Every job health is **up** (node, cadvisor, backend, market_updater).
- `http_requests_total` and `http_request_duration` appear in `/api/metrics` output.
- `market_updater_heartbeat_age_seconds` query returns a number (no empty result).

**Grafana:** Set `GF_SECURITY_ADMIN_PASSWORD` in `.env.aws` or `secrets/runtime.env` on EC2 (never commit). Prometheus datasource and "ATP Overview" dashboard (including "Prometheus target down" panel) should load.


---

## Optional: Alertmanager → Telegram

Alertmanager can be added in a follow-up (Phase 7.1/7.2): run Alertmanager in a container, configure a webhook to `http://backend-aws:8002/api/alerts/prometheus`, and have the backend forward to Telegram.
