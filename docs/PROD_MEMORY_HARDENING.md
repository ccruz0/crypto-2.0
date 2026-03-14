# PROD memory hardening

**Purpose:** Document the current PROD memory situation, the rationale for adding swap, what it improves and does not solve, and the recommended order of improvements. No implementation of new monitoring or application logic here — documentation and the minimal swap setup only.

**Instance:** PROD (i-087953603011543c5, atp-rebuild-2026)  
**Context:** Post–2026-03-11 incident; EC2 auto-recovery already added. See **docs/PROD_INCIDENT_2026-03-11_RECOVERY.md**.

---

## Current observed PROD memory situation

- **Total RAM:** ~1.9 GiB (t3.small).
- **Used / free:** Post-recovery observations showed ~1.2 GiB used, ~125 MiB free, ~722 MiB “available” (including reclaimable).
- **Swap:** Disabled.
- **Conclusion:** Memory margin is thin; any spike (e.g. deploy, cron, or brief load) increases the risk of OOM or unresponsive behavior.

---

## Why no-swap on a small Docker host is fragile

- With no swap, the kernel cannot move rarely used pages to disk; all pressure is absorbed by RAM.
- On a small instance running Docker and several containers (backend, db, market-updater, frontend, etc.), even short spikes can push the system close to OOM.
- OOM can kill critical processes (SSM agent, docker daemon, or the app), leading to SSM ConnectionLost and API unreachable — consistent with an instance-level outage.
- A small swap file does not fix underlying capacity limits but gives the kernel a buffer so transient spikes are less likely to cause immediate OOM or lockup.

---

## What the swap change improves

- **Adds a safety margin:** A 2 GB swap file at `/swapfile` (see **infra/aws/prod_swap/**) allows the kernel to swap out inactive pages when RAM is under pressure.
- **Reduces fragility:** Short memory spikes are less likely to trigger OOM or make the instance unresponsive, improving resilience alongside EC2 auto-recovery.
- **Reversible and minimal:** Single file, no change to ATP application code, health scripts, docker, nginx, or timers.

---

## What it does NOT solve

- **Does not replace instance sizing:** If PROD is routinely near memory limit, medium/long-term fix is to resize or optimize workload.
- **Does not replace EC2 auto-recovery:** Instance-level recovery (status-check alarm + recover action) remains the first line of defense for host/guest failures.
- **Does not add monitoring:** No new alarms, scripts, or dashboards are added here; that is a later step.
- **Does not fix application bugs or leaks:** Swap only mitigates pressure; it does not fix memory leaks or inappropriate memory use.

---

## Recommended future order

Implement in this order; only (1) and (2) are in scope for this hardening package.

1. **EC2 auto-recovery** — Done. CloudWatch alarm on status-check failure + EC2 recover action. See **infra/aws/ec2_auto_recovery_prod/**.
2. **Swap safety margin** — This step. Small swap file on PROD via **infra/aws/prod_swap/**.
3. **Memory-pressure monitoring** — Later. Add guidance or lightweight checks (e.g. MemAvailable, swap usage) and optional alerting; do not duplicate existing ATP health scripts.
4. **Instance sizing review** — Later. Revisit t3.small vs. larger instance or reserved capacity based on sustained usage and incidents.
5. **Duplicate-monitor consolidation** — Later. Consolidate overlapping health/alerting mechanisms per **docs/ATP_RUNTIME_HEALTH_RECOVERY_BASELINE.md** and **docs/ATP_EXISTING_HEALTH_RECOVERY_AUDIT.md**.

---

## Possible future monitoring signals

Recommendations only — no implementation in this document. When you add monitoring, consider these signals without duplicating existing ATP health/self-heal logic:

- **MemAvailable threshold:** Alert or log when MemAvailable (or equivalent) drops below a chosen value (e.g. 200 MiB) so you can investigate before OOM.
- **Swap usage threshold:** If swap usage grows and stays high, it may indicate sustained memory pressure and a need for sizing or optimization.
- **OOM detection from dmesg/journal:** Parse `dmesg` or `journalctl` for OOM killer messages to confirm that an outage was OOM-related and to correlate with other events.
- **Docker daemon health:** Ensure existing or new checks do not duplicate ATP self-heal; consider only lightweight “docker info” or daemon liveness if needed for operational visibility.
- **Local /api/health checks:** Existing ATP health endpoints and timers already cover app health; any additional local checks should be clearly scoped (e.g. for a runbook or dashboard) and not duplicate atp-selfheal / health-snapshot / health-alert behavior.

---

## Deployment Status

- **Runbook:** **docs/runbooks/PROD_SWAP_DEPLOYMENT_RUNBOOK.md** — connect to PROD, update repo if needed, run `infra/aws/prod_swap/setup_swap.sh`, verify with `swapon --show`, `free -h`, `grep swapfile /etc/fstab`, optional swappiness, final health check.
- After running the runbook and confirming the expected results (§4 and §6 of the runbook), swap deployment is complete.

## Current Deployment State

Swap is **already enabled and verified** on PROD: `/swapfile` exists, `swapon --show` confirms 2G swap active, and `/etc/fstab` contains the swap entry. nginx, SSM (snap unit), and API health are healthy. Swap was applied via equivalent inline commands through SSM. **The repo working tree on PROD is not yet aligned with Git** (local changes and untracked files prevented a clean `git pull`; `infra/aws/prod_swap` does not exist in the PROD tree). Repo reconciliation is a separate operational follow-up; see **docs/runbooks/PROD_REPO_RECONCILIATION_RUNBOOK.md**.

---

## Next Step

The next phase is **observability only**: use manual checks and system snapshots (see **docs/PROD_OBSERVABILITY_SIGNALS_PLAN.md** and **docs/runbooks/PROD_OBSERVABILITY_CHECKS_RUNBOOK.md**) to build visibility into memory and system pressure before making any further automation changes. Optional helper: **scripts/diag/prod_observability_snapshot.sh** (read-only snapshot).

---

## Summary

- **Current state:** PROD is a small instance with tight memory and no swap.
- **Change:** Add a 2 GB swap file on PROD via **infra/aws/prod_swap/setup_swap.sh** for a safety margin only.
- **Next steps (later):** Memory-pressure monitoring, instance sizing review, and consolidation of duplicate health/monitoring mechanisms, in that order.
