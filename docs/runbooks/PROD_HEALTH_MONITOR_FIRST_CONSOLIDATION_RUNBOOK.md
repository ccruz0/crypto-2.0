# PROD Health Monitor First Consolidation Runbook

**Date:** 2026-03-11  
**Status:** Operational runbook for the first safe consolidation action. Execute only when PROD is healthy and preconditions are met.

---

## 1. Purpose

This runbook is the **first safe consolidation action** on PROD. It targets **only** `health_monitor.service` because that mechanism appears to **overlap with atp-selfheal remediation**: both can restart Docker services and nginx. Running both can cause double-restarts, race with atp-selfheal’s lock, and make recovery behavior harder to reason about. The canonical remediation path is **atp-selfheal.timer** (verify.sh → heal.sh). This action verifies whether `health_monitor.service` exists and is active on PROD; if it is, we disable and stop it as the single first consolidation step. If it does not exist, we document that and make no host change. No files are deleted and no ATP timers are changed.

---

## 2. Preconditions

Before running this runbook:

- **PROD must be healthy:** EC2 status checks pass, docker and nginx active, backend responding.
- **External GET /api/health must be healthy:** e.g. `curl -sS https://dashboard.hilovivo.com/api/health` returns 200 and OK.
- **SSM or SSH access must work** so you can run the commands on the PROD instance.
- **No ongoing incident:** Do not run consolidation during an active outage or recovery.
- **Existing ATP timers must already be running:** atp-selfheal.timer, atp-health-snapshot.timer, atp-health-alert.timer confirmed active.
- **Operator must have sudo** on the PROD host to run systemctl and inspection commands.

---

## 3. First Inspection Step

Run this **exact** command on PROD (via SSM or SSH):

```bash
sudo systemctl status health_monitor.service --no-pager -l
```

**Two possible outcomes:**

- **Unit not found** (e.g. “Unit health_monitor.service could not be found”): Document that `health_monitor.service` is not installed on PROD. **Stop here.** No host change is needed. Record the result and consider this first consolidation step complete (nothing to disable).
- **Unit exists** (status output shows loaded/active or inactive): Continue to **Section 4** to run the full verification set before deciding whether to disable.

---

## 4. Verification Commands

Run these on PROD and record the output before making any change:

```bash
sudo systemctl is-enabled health_monitor.service
sudo systemctl is-active health_monitor.service
sudo journalctl -u health_monitor.service -n 200 --no-pager
sudo find /etc/systemd /usr/local/bin /opt /home /root -type f 2>/dev/null | grep -Ei 'health_monitor|health-monitor'
sudo grep -RinE 'health_monitor|health-monitor' /etc /opt /home /root 2>/dev/null | head -200
sudo systemctl list-timers --all | grep -Ei 'atp|health|nightly|dashboard'
curl -sS https://dashboard.hilovivo.com/api/health
```

Use the results to confirm: (1) whether `health_monitor.service` is enabled and active, (2) that ATP timers are still present and expected, (3) that external health is OK before any change.

---

## 5. Decision Point

- **If `health_monitor.service` is not present** (already determined in Section 3): Stop and record that no host change is needed. First consolidation action complete.
- **If present but inactive** (is-enabled and/or is-active show disabled/inactive): Stop and record that no host change is needed. No need to disable an already inactive service.
- **If present and active:** Proceed to **Section 6** to perform the single safe consolidation change.

---

## 6. Single Safe Consolidation Change

**Only** if Section 5 determined that `health_monitor.service` is present and active, run these **exact** commands on PROD:

```bash
sudo systemctl disable health_monitor.service
sudo systemctl stop health_monitor.service
```

**State clearly:**

- **Do not delete files** (no removal of scripts, unit files, or docs in this step).
- **Do not disable ATP timers** (atp-selfheal, atp-health-snapshot, atp-health-alert remain enabled and running).
- **Do not change any scripts yet** (no edits to health_monitor.sh or install_health_monitor.sh).

---

## 7. Immediate Post-Change Verification

Right after the change in Section 6, run:

```bash
sudo systemctl is-enabled health_monitor.service
sudo systemctl is-active health_monitor.service
sudo systemctl list-timers --all | grep -Ei 'atp|health|nightly|dashboard'
curl -sS https://dashboard.hilovivo.com/api/health
```

**Expected results:**

- **health_monitor:** disabled and inactive (is-enabled may show “disabled”, is-active “inactive”).
- **ATP timers:** Still present and listed (atp-selfheal, atp-health-snapshot, atp-health-alert).
- **External health:** Still OK (HTTP 200 and healthy payload from /api/health).

If any of these are not met, consider rollback (Section 9) and investigate before leaving.

---

## 8. Observation Window

- **Observe for 24–48 hours** after the change. Ensure no new incidents, unexpected restarts, or alert anomalies that could be attributed to disabling health_monitor.
- **Do not make another consolidation change** (e.g. disable another service or timer) during this window. One change at a time.
- Watch for: incidents, repeated restarts, Telegram alert gaps or duplicates, and atp-selfheal journal (PASS/HEALED/STILL_FAIL) to confirm the canonical stack is handling recovery.

---

## 9. Rollback

If you need to re-enable `health_monitor.service` (e.g. unexpected regression or need to revert the consolidation step), run on PROD:

```bash
sudo systemctl enable health_monitor.service
sudo systemctl start health_monitor.service
sudo systemctl status health_monitor.service --no-pager -l
```

Confirm the service is enabled and active. No file restore is needed if no files were deleted.

---

## 10. What Not To Do

- **Do not delete scripts yet** (e.g. health_monitor.sh, install_health_monitor.sh, health_monitor.service in repo or on host).
- **Do not remove docs yet** (no removal of README_HEALTH_MONITOR.md or consolidation/review docs).
- **Do not disable atp-selfheal** (or atp-health-snapshot / atp-health-alert). This runbook only disables health_monitor.service.
- **Do not combine this with any other consolidation step** (e.g. cron, dashboard_health_check, nightly-integrity). One target per run.
- **Do not run broad cleanups** (no mass disable, no filesystem cleanup, no nginx/docker-compose/backend changes).

---

## 11. Exit Criteria

This first consolidation action is **complete** only when:

1. **health_monitor** was confirmed **absent** on PROD (no unit) **or** was **disabled and stopped** safely.
2. **ATP timers** (atp-selfheal, atp-health-snapshot, atp-health-alert) remain **healthy** and running.
3. **External /api/health** remains **OK** after the change.
4. The **observation window** (24–48 hours) passes without new issues attributable to this change.

Document the outcome (e.g. “health_monitor not present” or “health_monitor disabled on &lt;date&gt;”) and then consider the next consolidation candidate only after a separate review and runbook.

---

**Related:**

- **docs/HEALTH_MONITOR_FIRST_CONSOLIDATION_REVIEW.md** — Detailed review, overlap analysis, and rationale.
- **docs/HEALTH_RECOVERY_CONSOLIDATION_PLAN.md** — Overall consolidation strategy.
