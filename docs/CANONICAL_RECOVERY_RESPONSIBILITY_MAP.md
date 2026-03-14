# Canonical Recovery Responsibility Map

## 1. Purpose

The goal of this document is to reduce operational complexity by ensuring each recovery or observability component has **exactly one responsibility**. Overlapping remediation logic leads to confusion, duplicate restarts, and harder debugging. This document defines the **canonical ownership** of recovery, observation, and alerting responsibilities across the Automated Trading Platform so that operators and automation know who owns what.

## 2. Current Production Baseline

The following components are confirmed in production:

**Infrastructure:**

- AWS EC2 instance
- AWS instance status checks
- SSM access

**OS layer:**

- swap enabled
- systemd services

**Runtime layer:**

- Docker containers
- nginx reverse proxy

**Application monitoring:**

- atp-selfheal.timer
- atp-health-alert.timer
- atp-health-snapshot.timer

**External verification:**

- /api/health endpoint

## 3. Canonical Responsibility Model

### Infrastructure Recovery

**Owner:** AWS

**Responsibility:** Recover the instance if the host becomes unreachable (e.g. failed status checks, hardware issues).

**Mechanism:** AWS EC2 status checks and auto-recovery.

---

### Runtime Recovery

**Owner:** atp-selfheal.timer

**Responsibility:** Detect runtime failure and restart application components when the app is unhealthy but the host is up.

**Typical actions:** Restart docker stack or restart failing services.

---

### Observation

**Owner:** atp-health-snapshot.timer

**Responsibility:** Collect health state and system signals for visibility and later analysis.

**Examples:** market data freshness, service health, resource usage.

**No remediation should happen here** — only collection and logging/snapshot.

---

### Notification

**Owner:** atp-health-alert.timer

**Responsibility:** Notify operators when abnormal conditions occur so humans can decide whether to act.

**Examples:** Telegram alerts, health warnings.

**No remediation should happen here** — only notification.

---

### Human Operations

**Owner:** Operator

**Responsibility:** Execute runbooks and intervene when automated recovery is insufficient or when manual decisions are required.

**Examples:** runbook execution, manual inspection, incident response.

## 4. Explicit Non-Overlap Rules

To prevent complexity and duplicate remediation:

- **Only one mechanism performs runtime remediation** — atp-selfheal.timer. No other timer or service should restart Docker or application services for health reasons.
- **Observation components must never restart services** — atp-health-snapshot.timer only collects; it does not trigger restarts.
- **Alerting components must never restart services** — atp-health-alert.timer only notifies; it does not trigger restarts.
- **Infrastructure recovery must not attempt application-level fixes** — AWS recovers the host; it does not run application or container remediation.

## 5. Allowed Recovery Paths

The only allowed recovery paths are:

| Failure type              | Recovery path           |
|---------------------------|-------------------------|
| Host failure              | AWS auto-recovery       |
| Application runtime failure | atp-selfheal.timer    |
| Operational incident      | operator runbook        |

Recovery should not be duplicated by adding another component that restarts services or the host.

## 6. Signals vs Actions

**Signals** (observation and alerting):

- Snapshot metrics
- Health checks (e.g. /api/health)
- Logs and dashboards

**Actions** (remediation):

- Restarting services
- Restarting Docker
- Host recovery (AWS)

Signals must **not** trigger actions directly unless routed through the canonical remediation layer (e.g. atp-selfheal for runtime, AWS for host). Observation and alerting inform operators and may inform selfheal logic, but only the designated owner performs the action.

## 7. Benefits of the Model

- **Clear ownership of recovery** — No ambiguity about which component restarts what.
- **Reduced operational noise** — One remediation path means fewer duplicate restarts and easier reasoning.
- **Easier debugging** — When something restarts, the source is known.
- **Predictable recovery behavior** — Operators can rely on a single, documented recovery stack.

## 8. Implementation Status

The current system already largely follows this model:

- **AWS** handles instance recovery.
- **atp-selfheal.timer** handles runtime remediation.
- **atp-health-snapshot.timer** handles observation.
- **atp-health-alert.timer** handles notification.
- **Runbooks** handle human response.

health_monitor.service is **not** installed on PROD; the runtime recovery stack is already clean and aligned with this map.

## 9. Future Consolidation Principle

- If any script or service overlaps with the canonical responsibilities above, it should be **reviewed** and potentially **retired** after verification that the canonical owner covers the need.
- Consolidation must occur **one mechanism at a time**, with verification and documentation before removing or changing anything.

## 10. Relationship to Other Documents

This document complements:

- **docs/PROD_INCIDENT_2026-03-11_RECOVERY.md** — Incident context and recovery actions.
- **docs/PROD_MEMORY_HARDENING.md** — Memory and swap hardening that support the OS/runtime baseline.
- **docs/HEALTH_RECOVERY_CONSOLIDATION_PLAN.md** — Planning for health and recovery consolidation.
- **docs/OPERATING_MODEL_MOTION_OPENCLOW_CURSOR.md** — Workflow for how changes (including consolidation) are analyzed and implemented.

This map defines **responsibility boundaries**; those documents provide incident history, hardening details, consolidation plans, and the process for making changes safely.
