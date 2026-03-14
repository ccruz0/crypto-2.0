# PROD Observability Signals Plan

## 1. Purpose

The next phase for PROD hardening is **observability only** — better visibility into memory and system pressure so operators can detect and investigate issues before or after incidents. This plan does **not** add new recovery automation, restart logic, or duplicate alerting. It defines which signals to watch and how to interpret them, so we can later decide whether any consolidation or alert tuning is needed.

---

## 2. Why This Is Needed

- **PROD previously suffered an instance-level outage** (2026-03-11): EC2 reachability failed, SSM went ConnectionLost, API timed out; reboot and ext4 recovery restored service. The failure was below the application layer.
- **Swap is now enabled** on PROD as a safety margin, reducing fragility from short memory spikes. We still need **better visibility** into pressure signals so we can see when the system is under stress and correlate with incidents.
- **Existing self-heal and alert timers already exist** (atp-selfheal, atp-health-snapshot, atp-health-alert). We should **avoid adding overlapping recovery logic**; instead we add **observability** — signals and manual checks — so operators can interpret state and use existing runbooks when needed.

---

## 3. Signals To Watch

Recommendations only; no implementation of automated alerts in this document.

| Signal | What it indicates | Why it matters | Suggested threshold / interpretation | Level |
|--------|-------------------|----------------|-------------------------------------|--------|
| **MemAvailable** | Kernel’s view of reclaimable + free memory | Low value means the system is under memory pressure; OOM risk increases. | e.g. &lt; 200 MiB: investigate; &lt; 100 MiB: high pressure. Use `free` or `/proc/meminfo`. | Host |
| **Swap usage** | How much swap is in use | High or growing swap use indicates sustained memory pressure; may warrant sizing review. | Track trend; sudden growth or &gt; ~50% of swap used under load: note for review. | Host |
| **Disk usage on /** | Root filesystem space | Full disk can break SSM, logging, and app writes. | e.g. &gt; 85%: investigate; &gt; 90%: act (see existing self-heal/runbooks). | Host |
| **OOM evidence (dmesg/journal)** | Kernel OOM killer or out-of-memory events | Confirms that an incident was OOM-related; helps correlate with SSM/app unreachable. | Any OOM line: document; repeated OOM: investigate and consider sizing. | Host |
| **Docker daemon health** | Whether the Docker service is running | If Docker is down, containers (backend, db, etc.) are not running. | `systemctl is-active docker` = active; inactive: use existing recovery runbooks. | Service |
| **Local GET /api/health** | App liveness | Quick check that the backend responds. | 200 + `{"status":"ok",...}` = healthy; 5xx or timeout: app or proxy issue. | App |
| **Local GET /api/health/system** | Full system health (market data, DB, etc.) | Detailed status from the app’s perspective. | Use for post-incident or routine inspection; PASS/WARN/FAIL per component. | App |
| **nginx active state** | Reverse proxy is running | If nginx is down, public API and dashboard are unreachable. | `systemctl is-active nginx` = active. | Service |
| **SSM snap unit active state** | SSM agent (snap) is running | If SSM is inactive, remote management via SSM is lost. | `systemctl is-active snap.amazon-ssm-agent.amazon-ssm-agent` = active. | Service |

---

## 4. Suggested Monitoring Order

Recommended priority for human/operator visibility (manual checks or future dashboards):

1. **Host-level first:** Memory (free, MemAvailable), swap (swapon --show), disk (df -h /). These explain most instance-level outages.
2. **OOM / kernel:** dmesg or journalctl for OOM/ext4/errors — use after an incident or when memory looks tight.
3. **Service-level:** docker, nginx, SSM (snap unit) — quick “is the stack up?” check.
4. **App-level:** Local /api/health and /api/health/system — confirm the app and its view of dependencies.

---

## 5. What Not To Add Yet

- **No new self-heal scripts** — atp-selfheal and related logic already exist.
- **No new restart timers** — do not add additional systemd timers or cron jobs that restart services.
- **No duplicate Telegram alert flows** — atp-health-alert and existing Telegram integration already exist; do not add a second alert path for the same signals.
- **No cross-instance recovery logic yet** — observability is single-instance and human/operator-driven first.

---

## 6. Recommended Future Path

1. **Visibility** — Use the observability runbook and optional snapshot script to collect signal snapshots (manual or ad hoc). Build a habit of checking after incidents or during routine checks.
2. **Review real signal history** — Once we have a history of snapshots or notes, review which signals actually correlated with issues (e.g. MemAvailable before SSM loss, swap growth, OOM in dmesg).
3. **Only then** decide whether any consolidation (e.g. single canonical health check) or alert tuning (e.g. thresholds, Telegram) is needed. Do not add automation until we have evidence from observability.

**Note (consolidation):** After the observability baseline is in place, the next phase is **cautious consolidation planning** (see **docs/HEALTH_RECOVERY_CONSOLIDATION_PLAN.md**), not immediate removal or disabling of existing health/recovery mechanisms.

---

**Related:**  
- **docs/runbooks/PROD_OBSERVABILITY_CHECKS_RUNBOOK.md** — manual commands and interpretation.  
- **scripts/diag/prod_observability_snapshot.sh** — optional read-only snapshot helper (if present).
