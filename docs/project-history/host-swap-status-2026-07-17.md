# HostSwapHigh — status 2026-07-17

Read-only synthesis. No infra changes applied. Do **not** suppress `HostSwapHigh`.

## Verdict

| Layer | Status |
|-------|--------|
| Acute dockerd hot-loop (orphaned `docker compose logs`) | **Fixed** 2026-07-06 — see `swap_investigation.md` §6.1 |
| Structural oversubscription on single `t3.small` | **Still open** — Jul 10 host snapshot still showed ~50% swap |
| ADR-0002 (upgrade vs split vs hybrid) | **Recommended, not implemented** |
| Prod code tip | Deployed: `a2e60c93` (#177), healthy |

**`HostSwapHigh` remains a true positive until prod swap stays &lt;25% for a sustained window.** Residual pages after the dockerd kill can keep the alert firing even when `si/so≈0`; only a fresh host snapshot confirms whether pressure is active thrashing or leftover occupancy.

## Timeline (reconciled)

1. **2026-06-26** — Structural diagnosis: ~5.5 GiB Docker limits vs 1.9 GiB RAM; recommend split LAB (ADR-0002).
2. **2026-07-06** — Acute cause of CPU storm: two orphaned `docker compose logs` followers → dockerd ~183% CPU. Killed; dockerd → 0%. That episode’s *CPU-driven* swap pressure is resolved.
3. **2026-07-10** — New read-only snapshot: swap still ~1.0 GiB / 2.0 GiB (~50%), MemAvailable ~395 MiB. Confirms structural headroom problem remains after dockerd fix.
4. **2026-07-17** — Public prod check only (no SSH):
   - Health OK; `x-atp-backend-commit=a2e60c93…`
   - `process_resident_memory_bytes` ≈ **238 MiB** for `backend-aws` (aligned with Jul 10 `docker stats` ~265 MiB)
   - Prometheus/Grafana not exposed publicly → host swap/MemAvailable need paste-back from the instance

## Declared memory budget (compose, still oversubscribed)

| Service | Limit |
|---------|-------|
| `backend-aws` | 2G |
| `backend-aws-canary` | 1G |
| `backend-lab` (`docker-compose.lab.yml`) | 2G |
| `frontend-aws` | 512M |
| market-updater / telegram-alerts | 512M each (where set) |
| postgres / prometheus / grafana / cAdvisor / node-exporter | often unlimited |

Sum of backend+lab+canary limits alone ≈ **5G** on a **1.9G** host when all profiles run together.

## LAB target correction

`INSTANCE_SOURCE_OF_TRUTH.md`: **`atp-lab-ssm-clean` (i-0d82c172235770a0d) = OpenClaw only.**

Do **not** migrate `backend-lab` / Jarvis Builder onto that host. Split options:

- **B1 (preferred structural):** dedicated Jarvis Builder host (`atp-lab-builder` per `LAB_JARVIS_BUILDER_BOOTSTRAP.md`), or stop `backend-lab` on PROD when idle.
- **B2 (wrong):** put trading/Jarvis backend on OpenClaw LAB — rejected by instance SoT.

## Recommendation (unchanged intent, clarified path)

| Priority | Option | When |
|----------|--------|------|
| **1 — Structural** | **B′ Split:** remove `backend-lab` (and idle canary) from PROD; run Jarvis Builder on a dedicated host, not OpenClaw LAB | Best long-term blast-radius + cost (~+$15/mo if new t3.small) |
| **2 — Fast relief** | **A Upgrade:** PROD `t3.small` → `t3.medium` (4 GiB) | If swap thrashing is active *now* and split cannot start immediately |
| **3 — Max isolation** | **C Hybrid:** A + B′ | Only if both prod peaks and always-on LAB are required |

**Zero-cost interim (human-gated, reversible):** stop `backend-lab` and/or canary when unused; avoid unattended `docker compose logs -f` on PROD.

## Decision gate

Needs human approval before: instance resize, stopping prod-adjacent containers, or launching/migrating a Builder host.

## Fresh host snapshot (please paste)

```bash
# Identity
hostname; date -u
curl -sS -D - -o /dev/null http://127.0.0.1:8002/api/health | grep -i x-atp-backend

# Memory / swap / pressure
free -h
vmstat 1 5
cat /proc/pressure/memory 2>/dev/null || true

# Orphan log followers (Jul 6 failure mode)
ps aux | grep -E 'docker compose.*logs|docker-compose.*logs' | grep -v grep || echo 'no compose-logs followers'

# Containers
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' | head -40
docker stats --no-stream

# Top VmSwap (host processes)
sudo awk '/VmSwap|Name:/{printf $2 " " $3} END{print ""}' /proc/[0-9]*/status 2>/dev/null \
  | sort -k2 -n -r | head -20

# PromQL (on host, if Prometheus up)
curl -sS -G 'http://127.0.0.1:9090/api/v1/query' \
  --data-urlencode 'query=(node_memory_SwapTotal_bytes-node_memory_SwapFree_bytes)/clamp_min(node_memory_SwapTotal_bytes,1)'
curl -sS -G 'http://127.0.0.1:9090/api/v1/query' \
  --data-urlencode 'query=node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes'
curl -sS -G 'http://127.0.0.1:9090/api/v1/query' \
  --data-urlencode 'query=ALERTS{alertname=~"HostSwapHigh|HostMemoryHigh|HostMemoryCritical|HostCPUSaturated"}'
```

Success criteria after any approved change: swap used **&lt;25%** for ≥30m, `si/so` near 0, prod `/api/health` OK, no OOM in `dmesg`.
