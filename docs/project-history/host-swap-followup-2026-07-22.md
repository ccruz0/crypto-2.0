# Host swap / disk follow-up — 2026-07-22

Read-only investigation + canary restart on `i-087953603011543c5`
(`atp-rebuild-2026`, ap-southeast-1).

## Memory / swap

| Moment | Instance | RAM avail | Swap used | Notes |
|--------|----------|-----------|-----------|-------|
| 01:32 UTC | t3.small | ~424 MiB | ~1.1 / 2.0 GiB (~55%) | HostSwapHigh true positive |
| 01:41 UTC | — | — | — | System reboot (resize) |
| 01:44 UTC | **t3.medium** | ~1.7 GiB | ~68 KiB (~0%) | Option A of ADR-0002 applied |

Largest non-container consumer on PROD: Cursor server / extensionHost / Prisma MCP
≈ **1.0 GiB RSS** (larger than the ATP container stack ≈ 0.8 GiB).

## Canary

- After resize: `backend-aws-canary` **Exited (137)** (`restart: "no"` in compose).
- Restarted 2026-07-22 with `sudo docker compose --profile aws up -d backend-aws-canary`.
- Note: compose briefly recreated `postgres_hardened` as a dependency; primary
  `/api/health/ready` stayed OK; canary reached **healthy** / ready on `:8003`.

## Disk (root 82% — secondary risk)

```text
/dev/root  48G  39G  8.8G  82%
```

| Location | Size | Notes |
|----------|------|-------|
| `/var/lib/containerd` | ~18 G | Image layers (containerd) |
| `/home/ubuntu` | ~8.8 G | Cursor + npm + caches |
| `/home/ubuntu/.cursor-server` | ~4.6 G | IDE on PROD |
| `/opt/openclaw` | ~3.8 G | OpenClaw install |
| Docker images (logical) | ~18.8 G | many historical `atp-backend:<sha>` tags |
| Docker build cache | ~2.6 G | ~1.6 G reclaimable |
| Unused images (docker df) | — | ~4.2 G reclaimable |

### Safe reclaim candidates (need explicit approval before running)

1. `docker builder prune` — build cache (~1.6 G reclaimable).
2. Prune dangling / old unused `atp-backend:<old-sha>` images keep current + rollback tag (~4 G).
3. Clear stale npm / playwright caches under `/home/ubuntu/.npm` and
   `/home/ubuntu/.cache/ms-playwright` if unused (~1–2 G).
4. Do **not** delete postgres volumes or active container layers.

## Decision / next

- ADR-0002 Opción A: **done**.
- Do not suppress `HostSwapHigh`.
- Disk cleanup: propose dry-run commands; wait for human OK before prune.
- Opción B (split): backlog, not emergency.
