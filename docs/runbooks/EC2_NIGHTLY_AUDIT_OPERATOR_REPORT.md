# EC2 Nightly Integrity Audit — Operator Report

**Generated:** After merge of PR #5 and push to main. EC2 deployment and validation must be run on the instance (Cursor environment is local; EC2 path `/home/ubuntu/automated-trading-platform` is not available locally).

---

## A. Merge status (completed)

- **PR #5** merged into `main` (merge commit + conflict resolution in `verify_no_public_ports.sh`, `option_a_audit_ec2.sh`).
- **Origin/main HEAD (GitHub):** `e6ade8f` (after push of deploy script). Previous merge: `22c94bf`.
- **Branch:** `main` pushed to `origin`.

---

## B–G. EC2 execution (run on the instance)

Run the following **on the EC2 host** (e.g. SSH into the box, then):

```bash
cd /home/ubuntu/automated-trading-platform
git fetch --all --prune
git checkout main
git pull --ff-only origin main
bash scripts/aws/run_nightly_audit_deploy_and_validate.sh
```

That script will:

1. Pull latest main (EC2 HEAD will match origin/main).
2. Run `bash -n` on audit scripts and set executable bits.
3. Run `nightly_integrity_audit.sh` once and print PASS/FAIL.
4. Install systemd unit + timer, enable and start timer.
5. Print timer status and next run time (Europe/Madrid).
6. Trigger the service once and print last ~80 lines of `journalctl -u nightly-integrity-audit.service`.
7. Print port binding for 8002/3000 and `docker compose --profile aws ps`.
8. Curl `/health` and `/api/health/system` (status codes only).
9. Print a short summary (EC2_HEAD, LAST_AUDIT_RESULT).

**One-liner (from repo root on EC2):**

```bash
cd /home/ubuntu/automated-trading-platform && git pull --ff-only origin main && bash scripts/aws/run_nightly_audit_deploy_and_validate.sh
```

---

## Evidence to confirm after EC2 run

From the script output (or by running the commands below on EC2), confirm:

| Check | Command / source |
|-------|-------------------|
| **EC2 git HEAD** | `git rev-parse --short HEAD` → should match origin/main (e.g. `e6ade8f`). |
| **Timer status + next run** | `sudo systemctl status nightly-integrity-audit.timer --no-pager` and `sudo systemctl list-timers nightly-integrity-audit.timer --no-pager` → next run at 03:15 Europe/Madrid. |
| **Last service result** | `sudo journalctl -u nightly-integrity-audit.service -n 50 --no-pager` → last line should be PASS or FAIL. If FAIL, exactly one Telegram alert should have been sent (step name + git hash). |
| **Ports 8002/3000** | `ss -ltnp | grep -E '(:8002|:3000)'` → only 127.0.0.1 (no 0.0.0.0). |
| **Containers** | `docker compose --profile aws ps` → backend-aws, frontend (if used), db Up/Healthy. |
| **Health** | `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8002/health` and same for `http://127.0.0.1:8002/api/health/system` → 200. |

---

## Summary

- **Merge:** PR #5 merged and pushed to `main`. Origin/main HEAD: `e6ade8f`.
- **EC2:** Pull main on the instance and run `scripts/aws/run_nightly_audit_deploy_and_validate.sh` to install systemd, enable the timer, run the audit once, and collect the evidence above. No secrets are printed by the script or the audit.
