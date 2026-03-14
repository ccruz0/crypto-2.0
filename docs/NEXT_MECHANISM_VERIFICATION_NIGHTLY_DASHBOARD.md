# Next Mechanism Verification: Nightly Integrity Audit and Dashboard Health Check

## 1. Purpose

This document prepares the **next low-risk runtime verification step** for two mechanisms whose PROD status is still unknown:

- **nightly-integrity-audit.timer** — systemd timer that runs a once-daily integrity audit (stack, health_guard, portfolio) and sends Telegram on first failure
- **dashboard_health_check** — script and optional timer/cron that checks `/api/market/top-coins-data` and sends Telegram on failure

Verification is **read-only**: no services or timers are disabled, stopped, or removed. The goal is to establish runtime-vs-repo accuracy and update **docs/CANONICAL_MECHANISM_INVENTORY.md** with confirmed PROD status for these two mechanisms.

## 2. Why These Are the Next Targets

- **Lower risk than touching canonical timers:** The canonical stack (atp-selfheal, atp-health-snapshot, atp-health-alert) is already confirmed active; this step only **observes** two additional mechanisms that may or may not be present.
- **Improves runtime-vs-repo accuracy:** The inventory currently marks both as "Unknown" for Confirmed On PROD / Active On PROD. Running the commands below and recording results removes that ambiguity.
- **Incremental and reversible:** No changes are made to the host; only documentation is updated after the operator runs the commands and reports back.
- **Aligned with consolidation plan:** HEALTH_RECOVERY_CONSOLIDATION_PLAN and CANONICAL_MECHANISM_INVENTORY recommend verifying nightly-integrity and dashboard_health_check next, after health_monitor.service was confirmed not installed.

## 3. Mechanisms Under Review

### nightly-integrity-audit.timer

- **Name:** nightly-integrity-audit.timer (and nightly-integrity-audit.service)
- **Expected purpose:** Run at 03:15 local time; executes `scripts/aws/nightly_integrity_audit.sh` (verify_no_public_ports, health_guard, stability_check, reconcile_order_intents, portfolio_consistency_check); on first failure sends one Telegram alert and exits 1; on success prints PASS and exits 0.
- **Likely repo paths:** `scripts/aws/nightly_integrity_audit.sh`, `scripts/aws/systemd/nightly-integrity-audit.service`, `scripts/aws/systemd/nightly-integrity-audit.timer`, `scripts/aws/_notify_telegram_fail.sh`
- **What is still unknown:** Whether the timer and service unit files are installed on PROD, whether the timer is enabled and active, and when it last ran (journal).

### dashboard_health_check

- **Name:** dashboard_health_check (may appear as timer, service, or cron entry)
- **Expected purpose:** Every 20 minutes (if timer) or on cron schedule: check `/api/market/top-coins-data`; on failure send Telegram alert.
- **Likely repo paths:** `scripts/dashboard_health_check.sh`, `install_dashboard_health_check.sh`; systemd units if installed: `scripts/dashboard_health_check.service`, `scripts/dashboard_health_check.timer` (or under docs/runbooks reference)
- **What is still unknown:** Whether a systemd timer/service exists on PROD, whether a cron job is installed (user or root), and whether the script is present and invoked by any scheduler.

## 4. Exact PROD Verification Commands

Run these on the **PROD** instance (e.g. via SSM or SSH). They are **read-only**; no disable, stop, or remove.

```bash
# ---- 1. Systemd unit files (presence) ----
sudo systemctl list-unit-files --no-pager | grep -Ei 'nightly|dashboard'

# ---- 2. Active timers (if any) ----
sudo systemctl list-timers --all --no-pager | grep -Ei 'nightly|dashboard'

# ---- 3. Status: nightly-integrity-audit ----
sudo systemctl status nightly-integrity-audit.timer --no-pager -l
sudo systemctl status nightly-integrity-audit.service --no-pager -l

# ---- 4. Status: dashboard_health_check ----
sudo systemctl status dashboard_health_check.timer --no-pager -l
sudo systemctl status dashboard_health_check.service --no-pager -l

# ---- 5. Cron jobs (user and root) ----
crontab -l
sudo crontab -l

# ---- 6. File presence (unit files / scripts) ----
sudo find /etc/systemd /usr/local/bin /opt /home /root -type f 2>/dev/null | grep -Ei 'nightly|dashboard_health'

# ---- 7. Grep configs for references ----
sudo grep -RinE 'nightly-integrity-audit|dashboard_health_check' /etc /opt /home /root 2>/dev/null | head -200
```

**Optional (to confirm last run and next run for nightly-integrity):**

```bash
sudo journalctl -u nightly-integrity-audit.service -n 50 --no-pager
sudo systemctl list-timers nightly-integrity-audit.timer --no-pager
```

## 5. Interpretation Rules

Use the command outputs to classify each mechanism as follows:

| Result | Meaning | Inventory fields to set |
|--------|---------|---------------------------|
| **not installed** | No unit file in `/etc/systemd`, no cron entry, no relevant file under /etc /opt /home /root | Confirmed On PROD: No. Active On PROD: No. Canonical Status: not installed (nightly) or legacy / not installed (dashboard). |
| **installed but inactive** | Unit file or script present but timer/service disabled or not running (e.g. `is-enabled` = disabled, `is-active` = inactive) | Confirmed On PROD: Yes. Active On PROD: No. Canonical Status: optional (nightly) or legacy (dashboard). |
| **active and canonical candidate** | (Rare for these two; they are optional/legacy.) Only if explicitly decided that the mechanism is part of the canonical set. | Confirmed On PROD: Yes. Active On PROD: Yes. Canonical Status: optional (nightly) or legacy (dashboard)—usually keep as optional/legacy per inventory. |
| **active but review candidate** | Timer or cron is enabled and has run; may overlap with atp-health-alert (Telegram). | Confirmed On PROD: Yes. Active On PROD: Yes. Canonical Status: optional (nightly) or legacy (dashboard). Note in Next Action: review vs atp-health-alert if Telegram overlap. |
| **unknown** | Commands were not run or output was ambiguous. | Leave Confirmed On PROD / Active On PROD as Unknown until re-verification. |

## 6. Inventory Update Rules

After the operator has run the verification commands and classified each mechanism:

1. **Open docs/CANONICAL_MECHANISM_INVENTORY.md** and locate the rows for **nightly-integrity-audit.timer** and **dashboard_health_check** in the Inventory Table (Section 3).

2. **Update the row(s)** with:
   - **Confirmed On PROD** — Yes or No (or leave Unknown if not determined).
   - **Active On PROD** — Yes, No, or N/A (e.g. not installed).
   - **Canonical Status** — Set to one of: **canonical** / **optional** / **legacy** / **not installed** / **unknown** per Interpretation Rules above. For these two, typical outcomes are **optional** (nightly) or **legacy** / **not installed** (dashboard).
   - **Next Action** — Short note, e.g. "Documented active 20YY-MM-DD; no change" or "Not installed on PROD; no action" or "Active; review Telegram overlap with atp-health-alert."

3. **Optionally update** Section 5 (Confirmed Non-Installed or Non-Active) or Section 6 (Legacy / Review Candidates) if the verification result changes the status of either mechanism (e.g. if dashboard_health_check is confirmed not installed, add a one-line note in Section 5).

4. **Do not** remove or rename any mechanism from the inventory; only update the status columns and Next Action.

## 7. Safety Rules

- **Verification only** — This step is for observing and documenting PROD state.
- **No disable** — Do not run `systemctl disable` for any unit.
- **No stop** — Do not run `systemctl stop` for any unit.
- **No remove** — Do not delete unit files, scripts, or cron entries.
- **No timer changes** — Do not change timer or service unit files on the host.
- **No script changes** — Do not modify any script in the repo or on the host as part of this verification.

If a future consolidation decision is made to disable one of these mechanisms, that will be a **separate** step with its own runbook and approval.

## 8. Next Step After Verification

Once both **nightly-integrity-audit.timer** and **dashboard_health_check** are verified and **docs/CANONICAL_MECHANISM_INVENTORY.md** is updated:

- **Next candidate** for verification is **infra/monitor_health.py** (cron): run `crontab -l` and `sudo crontab -l` (if not already done in this package), document presence or absence, and update the inventory row for that mechanism.
- Do **not** choose a new verification target until this package’s inventory updates are done and the two mechanisms are no longer "Unknown" for PROD status where determinable.
