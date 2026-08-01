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

See **`host-swap-status-2026-07-17.md`** for the reconciled recommendation (OpenClaw LAB must stay OpenClaw-only).

1. **Split Builder off PROD (recommended):** Stop or migrate `backend-lab` / Jarvis Builder to a dedicated Builder host — **not** `atp-lab-ssm-clean` (OpenClaw only). Optionally pause idle canary.
2. **Upgrade only:** `t3.small` → `t3.medium` on same host layout. Fastest relief if thrashing is active; blast radius unchanged.
3. **Hybrid:** Upgrade prod **and** remove Builder from PROD. Highest isolation; highest cost.

## Next investigation steps (read-only)

- Paste-back commands in `host-swap-status-2026-07-17.md` (fresh `free`/`vmstat`/`docker stats`/PromQL).
- Confirm whether Jul 6 residual swap is inert (`si/so≈0`) or still thrashing.
- Correlate swap spikes with `exchange_sync` and `signal_monitor` log timestamps if active.

## Decision

Pending human approval before any infra change. Do **not** suppress `HostSwapHigh`.
