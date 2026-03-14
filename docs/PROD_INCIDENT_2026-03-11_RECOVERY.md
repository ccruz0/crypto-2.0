# PROD Incident 2026-03-11 — Recovery

**Date:** 2026-03-11  
**Instance:** i-087953603011543c5 (atp-rebuild-2026)  
**Region:** ap-southeast-1

---

## Summary

PROD experienced loss of access (SSM ConnectionLost, public API timeout). Access was restored; post-recovery verification confirmed the outage was **instance-level**, not primarily an ATP application-layer failure. The app stack (docker, nginx, backend API) was healthy once the instance was reachable again; SSM and EC2 reachability had failed at the instance/OS level.

---

## Final Confirmed Runtime Facts (Post-Recovery)

- **PROD API healthy:** `GET /api/health` returns `200` with `{"status":"ok","path":"/api/health"}`.
- **EC2 status:** System and instance reachability checks both OK.
- **SSM:** PingStatus **Online** again.
- **nginx:** active (systemctl).
- **docker:** active (systemctl).
- **SSM agent — corrected unit name:** The real SSM service on this instance is **`snap.amazon-ssm-agent.amazon-ssm-agent.service`** (snap package), not `amazon-ssm-agent.service`. The snap service is active and running.
- **During reboot:** Console output showed ext4 recovery and orphan inode cleanup (filesystem consistency check).
- **ATP health/recovery stack on PROD:** The following timers are running:
  - **atp-selfheal.timer**
  - **atp-health-snapshot.timer**
  - **atp-health-alert.timer**

---

## Conclusion

This was an **instance-level outage**, not primarily an ATP app-layer outage. Evidence:

- **The application stack (nginx, docker, backend) recovered normally once the instance recovered.** This confirms the failure was below the application layer.
- Once the instance was reachable again (after reboot/recovery), the application stack and **GET /api/health** were healthy without app or config changes.
- SSM and public API were both unreachable during the incident; recovery coincided with instance reboot and ext4/orphan inode cleanup, pointing to an OS/instance or filesystem-related issue rather than a bug in the ATP app or nginx config.
- The SSM agent on PROD runs as the **snap** unit (`snap.amazon-ssm-agent.amazon-ssm-agent.service`). Scripts or runbooks that check or restart `amazon-ssm-agent` should use the snap unit on instances where SSM is installed via snap.

---

## Recommendations (Implementation Priority)

Implement in this order; no implementation in this document — plan only.

1. **AWS instance-level recovery on status-check failure**  
   Configure automatic recovery (e.g. EC2 status-check alarm + recovery action, or equivalent) so that when the instance fails system or instance status checks, AWS can recover the instance without waiting for manual reboot.

2. **Confirm and harden SSM agent behavior**  
   - Use the correct unit for checks and restarts: **`snap.amazon-ssm-agent.amazon-ssm-agent.service`** on PROD.  
   - Update any scripts/runbooks that assume `amazon-ssm-agent.service`.  
   - Optionally add a small health check or watchdog that verifies SSM agent (snap) is active and restarts it if needed, with appropriate guardrails.

3. **Add a small swap file on PROD**  
   PROD is a t3.small with limited RAM; memory pressure was observed during the incident. Adding a small swap file (e.g. 1–2 GiB) reduces fragility under memory pressure and can help avoid OOM kills of SSM agent or critical processes.

4. **Add local memory-pressure monitoring**  
   Monitor memory usage (and optionally swap) on PROD and alert or log when usage exceeds a threshold, so that memory pressure can be detected before it leads to loss of SSM or app responsiveness.

5. **Later: consolidate duplicate health mechanisms**  
   Per docs/ATP_EXISTING_HEALTH_RECOVERY_AUDIT.md and ATP_RUNTIME_HEALTH_RECOVERY_BASELINE.md, avoid running overlapping monitors (e.g. health_monitor.service alongside atp-selfheal, or multiple Telegram alert paths). Decide on the canonical stack and disable or repurpose duplicates.

---

**Related docs:**  
- docs/ATP_RUNTIME_HEALTH_RECOVERY_BASELINE.md — PROD runtime inventory and one-page stack updated with post-recovery facts.  
- docs/PROD_ACCESS_RECOVERY_AND_INSPECTION_PLAN.md — Recovery and inspection plan used to regain access.
