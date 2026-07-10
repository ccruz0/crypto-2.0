# Host swap / memory investigation — 2026-07-10

Read-only snapshot from production host (`t3.small`, 2 GB RAM, ap-southeast-1).

## Current pressure signals

| Metric | Value | Notes |
|--------|-------|-------|
| RAM total | 1.9 GiB | |
| RAM available | ~395 MiB | ~20% available |
| Swap total | 2.0 GiB | |
| Swap used | ~1.0 GiB (~50%) | `HostSwapHigh` threshold is 25% for 10m — alert is a true positive |
| Largest containers | `backend-aws` ~265 MiB, `backend-aws-canary` ~184 MiB, `postgres_hardened` ~164 MiB | 13 containers share one host |

## Root cause (working hypothesis)

Single `t3.small` runs production, canary, LAB-adjacent services, PostgreSQL, and full observability stack. Memory headroom is insufficient for simultaneous peaks (exchange sync, signal monitor, Grafana/Prometheus, Postgres buffer cache).

## Options (recommendation order)

1. **Hybrid (recommended):** Upgrade production host to `t3.medium` (4 GB) **and** move canary + non-prod workloads to a small LAB host. Lowest risk, moderate cost, reduces blast radius.
2. **Upgrade only:** `t3.small` → `t3.medium` on same host layout. Fastest fix; all workloads still share one failure domain.
3. **Split only:** Keep `t3.small` for production; move canary/LAB/observability to second host. More ops overhead; production may still swap under load.

## Next investigation steps (read-only)

- `docker stats --no-stream` during signal monitor cycle peak
- PromQL: `node_memory_MemAvailable_bytes`, swap used %, per-container `container_memory_usage_bytes`
- Correlate swap spikes with `exchange_sync` and `signal_monitor` log timestamps

## Decision

Pending human approval before any infra change. Do **not** suppress `HostSwapHigh`.
