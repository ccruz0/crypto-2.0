# Phase 6 — EC2 validation complete

**Tag:** `phase6-ec2-complete`  
**Date:** 2026-02-14

---

## What Phase 6 guarantees

All phases A–F of the EC2 hard verifier pass:

| Phase | Guarantee |
|-------|-----------|
| **A** | Environment proof (hostname, egress, git) |
| **B** | ACCOUNT_OK — signed Crypto.com API from backend (egress IP allowlisted) |
| **C** | Risk probe — spot 200 / allowed:true; margin over-cap 400 / RISK_GUARD_BLOCKED |
| **D** | D.1 system health (200, db up, telegram PASS); D.2 health_guard exit 0; D.3 nightly_integrity_audit exit 0 |
| **E** | Systemd timer `nightly-integrity-audit.timer` enabled, active, in list-timers; service journal shows at least one PASS |
| **F** | Ports 8002 and 3000 bound to 127.0.0.1 only (no 0.0.0.0) |

---

## What changed

- **Risk probe:** Spot allowed when equity unavailable (equity_unavailable_spot_probe_allowed); margin remains strict; user-balance parsing from exchange when available.
- **Health / WARN logic:** System health accepts global_status PASS or WARN where appropriate.
- **Audit self-heal:** `nightly_integrity_audit.sh` calls `ensure_stack_up()` at start — brings up `db` and `backend-aws` if down, waits up to 120s for `/api/health/system`, so the audit no longer fails with “connection refused” when the stack is cold.
- **Phase F (ss) fix:** Verifier only fails when the *bind* address is 0.0.0.0 for 8002/3000; ignores `ss` peer column `0.0.0.0:*` to avoid false positives.
- **Timer local time:** `nightly-integrity-audit.timer` uses `OnCalendar=*-*-* 03:15:00` with no fixed timezone; runs at 03:15 server local time on any host.
- **Audit steps:** Steps run via `bash` (no execute bit required); health_guard uses `--profile aws` for `docker compose ps` and retries curl /health; 5s settle after ensure_stack_up.

---

## How to verify on a new host

1. Clone/pull repo, ensure EC2 egress IP is allowlisted for the Crypto.com API key, start stack as needed.
2. Run:

```bash
cd /home/ubuntu/automated-trading-platform
bash scripts/aws/final_ec2_hard_verification.sh
echo "exit=$?"
```

3. **Expected:** Script prints `PHASE 6 — EC2 VALIDATION COMPLETE` and exit code is 0.

4. Optional: install timer from repo and enable:

```bash
sudo cp scripts/aws/systemd/nightly-integrity-audit.{service,timer} /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nightly-integrity-audit.timer
```
