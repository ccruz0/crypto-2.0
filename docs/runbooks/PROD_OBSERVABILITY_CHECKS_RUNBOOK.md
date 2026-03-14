# PROD Observability Checks Runbook

## 1. Purpose

This runbook is for **manual** post-incident or routine checks on PROD. It collects observability signals (memory, swap, disk, OOM, docker, nginx, SSM, health endpoints, timers) so operators can assess system pressure and correlate with incidents. It is **read-only** and does not restart, heal, or modify anything. Use it to gain visibility before deciding to run any existing recovery runbook.

---

## 2. Preconditions

- **PROD is reachable** via SSM or SSH.
- **Operator has sudo** if needed (e.g. for `dmesg` or `systemctl list-timers`).
- **Read-only / inspection mindset** — no restarts, no config changes, no new automation from this runbook.

---

## 3. Manual Commands

Run these on the PROD instance. If you are `ssm-user`, the repo may be at `/home/ubuntu/automated-trading-platform`; otherwise use the path that applies.

### Memory and swap

```bash
free -h
swapon --show
```

### Disk

```bash
df -h /
```

### OOM / kernel / filesystem indicators

```bash
sudo dmesg -T | grep -Ei 'oom|out of memory|ext4|nvme|error|fail|panic' | tail -200
```

### Docker / nginx / SSM

```bash
systemctl is-active docker
systemctl is-active nginx
systemctl is-active snap.amazon-ssm-agent.amazon-ssm-agent
docker ps
```

### Local health endpoints

```bash
curl -sS http://127.0.0.1:8002/api/health
curl -sS http://127.0.0.1:8002/api/health/system
```

### Existing timers

```bash
sudo systemctl list-timers --all | grep -Ei 'atp|health|nightly|dashboard'
```

---

## 4. How To Interpret Results

- **free -h / swapon --show:** Low “available” memory or high swap use suggests memory pressure; compare with pre-incident if you have history. Swap in use is normal under load; sustained high swap may warrant sizing review.
- **df -h /:** Root &gt; 85% used: investigate; &gt; 90%: risk of full disk (SSM, logging can fail). Use existing disk/self-heal runbooks if action is needed.
- **dmesg OOM/error/panic:** Any OOM or panic line: document and correlate with time of incident. Repeated OOM: investigate and consider instance sizing or app memory use.
- **docker / nginx / SSM:** All should report `active`. If any is `inactive` or `failed`, use existing recovery runbooks (e.g. SSM, nginx, docker) — this runbook does not add new recovery.
- **/api/health:** Expect HTTP 200 and JSON like `{"status":"ok",...}`. 5xx or timeout: app or proxy issue; use app logs and nginx/docker status.
- **/api/health/system:** Use for component-level status (market data, DB, etc.). PASS/WARN/FAIL per component; document for post-incident review.
- **Timers:** atp-selfheal, atp-health-snapshot, atp-health-alert (and optionally nightly, dashboard) should appear if installed; confirms existing health/recovery stack is present.

---

## 5. Escalation Guidance

- **Just document:** When all signals look normal or only mildly concerning (e.g. swap used but stable, disk &lt; 85%). Record the snapshot and move on.
- **Investigate deeper:** When memory is very low (e.g. MemAvailable &lt; 200 MiB), swap is high and growing, disk &gt; 85%, or dmesg shows OOM/errors. Check logs, recent deploys, and runbook history; consider scheduling sizing or cleanup.
- **Consider using an existing recovery path:** When a service is down (docker, nginx, SSM inactive) or API is unhealthy — use the **existing** runbooks (e.g. restore SSM, heal nginx, restart stack) as already documented. **Do not add new recovery mechanisms** from this runbook.

---

## 6. Notes

- This runbook is **observability only**. It does not restart services, send alerts, or change configuration.
- For a compact one-shot snapshot, you can use **scripts/diag/prod_observability_snapshot.sh** (if present); it is read-only and does not trigger alerts or recovery.
- See **docs/PROD_OBSERVABILITY_SIGNALS_PLAN.md** for the rationale and full list of signals.
