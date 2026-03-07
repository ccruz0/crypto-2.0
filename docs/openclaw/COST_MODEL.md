# OpenClaw — AWS Cost Optimization Plan

**Assumptions:** EC2 instance type not yet finalized; OpenClaw must run permanently. Goal: cost-optimized, always-on Lab.

---

## 1. Recommended Instance Type (Cost vs Performance)

| Option | Instance | vCPU | Memory | Use case | Est. monthly (ap-southeast-1, Linux) |
|--------|----------|------|--------|----------|--------------------------------------|
| **Recommended** | **t3.small** or **t4g.small** | 2 | 4 GiB | OpenClaw + clone + tests | **~20–35 USD** |
| More headroom | t3.medium | 2 | 4 GiB (burstable) | Heavier analysis / parallel jobs | **~45–60 USD** |
| ARM (cost-saving) | t4g.small | 2 | 4 GiB | Same as t3.small; lower $/vCPU if image is ARM | **~18–32 USD** |

**Recommendation:** Start with **t3.small** (or **t4g.small** if OpenClaw image supports ARM). Sufficient for one OpenClaw container plus OS; upgrade to t3.medium only if you see sustained CPU credit exhaustion or need heavier parallel test runs.

**Notes:**

- t4g requires ARM-compatible base image (e.g. Alpine ARM, or multi-arch).
- Spot is not recommended for “permanently running” OpenClaw; use On-Demand for predictable uptime.
- Reserved capacity (1-year) can reduce cost by ~30–40% if Lab is long-term.

---

## 2. CPU and Memory Limits for Container

To avoid one process starving the host and to align with cost expectations:

| Resource | Limit | Rationale |
|----------|--------|-----------|
| **CPU** | 1 core | OpenClaw: clone, small scripts, occasional test runs; 1 vCPU is enough. |
| **Memory** | 2 GB | Limit to 2G so host (4 GiB) keeps ~2 GiB for OS, Docker, logs, and buffers. |

Example (Docker Compose):

```yaml
deploy:
  resources:
    limits:
      cpus: "1.0"
      memory: 2G
```

Optional reservations (not required for cost cap):

```yaml
    reservations:
      cpus: "0.25"
      memory: 512M
```

---

## 3. Autoscaling or Not

| Approach | Recommendation | Reason |
|----------|----------------|--------|
| **Autoscaling** | **No** | OpenClaw is a single long-running agent; scaling out multiple OpenClaw instances adds complexity and risk (e.g. duplicate PRs). One instance, one container. |
| **Manual resize** | Optional | If load grows (e.g. many parallel analyses), resize instance (e.g. t3.small → t3.medium) and/or raise container limits; no ASG. |

**Conclusion:** No ASG; single EC2 On-Demand (or Reserved) for Lab.

---

## 4. Logging Strategy with Minimal CloudWatch Cost

| Strategy | Action | Cost impact |
|----------|--------|-------------|
| **Prefer local logs** | Write OpenClaw logs to files on host (e.g. under `/var/log/openclaw/`) with rotation. | No CloudWatch ingestion for routine logs. |
| **Log rotation** | Use logrotate (or container-side rotation): e.g. daily rotate, keep 7 days, compress. | Keeps disk small and avoids unbounded growth. |
| **No verbose CloudWatch** | Do **not** ship all stdout/stderr to CloudWatch Logs by default. | Saves ingestion and storage. |
| **Optional: critical only** | If desired, ship only ERROR-level or “alert” events to a single log group with short retention (e.g. 7 days). | Minimal ingestion/storage. |
| **Metrics** | Avoid custom metrics unless needed; use default EC2 metrics (CPU, network) for basic health. | No extra metric cost. |

**Concrete:**

- **Container:** Log to stdout/stderr; Docker captures to host path (e.g. `docker compose logs` or bind-mounted log dir).
- **Host:** logrotate for `/var/log/openclaw/*.log` (and any Docker json-log under `/var/lib/docker/containers/` if you keep them): `rotate 7`, `daily`, `compress`.
- **CloudWatch:** Omit or limit to one log group with 7-day retention for errors/alerts only.

---

## 5. Idle Resource Control Strategy

| Resource | Control | Notes |
|----------|--------|--------|
| **EC2** | Single instance; no scale-in/scale-out | “Idle” = low CPU when OpenClaw is not running heavy jobs; t3.small burstable handles spikes. |
| **EBS** | One volume (e.g. 20–30 GB gp3) for root + data | No extra volumes unless needed for backups; gp3 is cheaper than gp2. |
| **Data transfer** | Lab → GitHub (egress to internet) | Minimal; clone/PR traffic is small. No need for Data Transfer tiering. |
| **Snapshots** | Optional AMI/snapshot for Lab; infrequent | Only if you want quick rebuild; not required for cost. |
| **IP** | Elastic IP only if you need fixed outbound IP for allowlisting | Adds small cost if unused; attach only if required. |

**Idle:** OpenClaw runs 24/7 but is mostly waiting (poll or schedule); CPU credits (t3/t4g) cover short bursts. No “shutdown at night” recommended if the goal is “permanently running”; otherwise you could stop instance outside business hours (not in scope for “permanent” requirement).

---

## 6. Estimated Monthly Cost

**Assumptions:** ap-southeast-1 (Singapore), On-Demand, Linux, single Lab instance, 30 GB gp3.

| Item | Est. monthly (USD) |
|------|--------------------|
| **EC2 t3.small** (On-Demand) | ~15–18 |
| **EBS 30 GB gp3** | ~2.5–3 |
| **Data transfer (egress, small)** | ~1–2 |
| **CloudWatch (minimal or none)** | 0–2 |
| **Elastic IP (if used)** | ~3.6 if attached to running instance; 0 if not used |
| **Total (no EIP)** | **~20–25** |
| **Total (with EIP)** | **~24–29** |

With **t4g.small** (ARM): similar or slightly lower (~18–24 USD without EIP).

With **t3.medium**: **~45–60 USD** (EC2 ~38–45 + EBS + transfer).

**Rough target:** **20–35 USD/month** for permanent, cost-optimized OpenClaw Lab (t3.small/t4g.small, 2 GB container limit, local logs, no autoscaling).

---

## 7. Summary Table

| Dimension | Choice |
|-----------|--------|
| Instance type | t3.small or t4g.small |
| Container CPU limit | 1 core |
| Container memory limit | 2 GB |
| Autoscaling | No |
| Logging | Local + logrotate; CloudWatch minimal or none |
| Idle control | Single instance; optional EIP only if needed |
| Estimated monthly cost | **20–35 USD** (t3/t4g.small); **45–60 USD** (t3.medium) |
