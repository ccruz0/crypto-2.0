# Investigación: HostSwapHigh / Presión de memoria y swap

> **Estado:** CERRADA (investigación read-only completada 2026-06-26).
> **Riesgo de producción actual más alto:** memoria/swap (no disco; disco ~48% usado, OK).
> **Regla cumplida:** solo investigación y recomendación. **Sin cambios de infra**
> aplicados como parte de este cierre — requiere aprobación humana explícita.

---

## 1. Resumen ejecutivo

- **Síntoma:** `HostSwapHigh` disparándose de forma sostenida; swap ~50%; RAM constreñida.
- **Causa raíz (confirmada):** **sobreaprovisionamiento lógico de memoria** en un host
  `t3.small` (1.9 GiB RAM) que ejecuta simultáneamente Producción, Canary, LAB,
  observabilidad completa, PostgreSQL y procesos de desarrollo (Cursor server). Los
  límites Docker suman ~5.5 GiB declarados vs ~1.9 GiB físicos; el kernel compensa
  con swap (~1 GiB / 2 GiB usado = 50%).
- **Recomendación:** **Opción B — split Producción / LAB** a host dedicado
  (`atp-lab-ssm-clean`, i-0d82c172235770a0d), alineado con el diseño original del
  runbook. **Relief rápido alternativo:** Opción A — upgrade a `t3.medium` (4 GiB).
- **Decisión y siguiente paso:** pendiente de aprobación humana antes de cualquier
  cambio de instancia o migración. Ver ADR-0002 en `architecture_decisions.md`.

---

## 2. Contexto del sistema

- Host medido: AWS `t3.small`, 2 vCPU, **1.9 GiB RAM**, 2 GiB swapfile, 48 GB disco
  (~48% usado), `ap-southeast-1`, instancia `i-087953603011543c5` (atp-rebuild-2026).
- **13 contenedores** activos en el host compartido:
  - **Producción:** backend-aws, frontend-aws, postgres, market-updater, telegram-alerts
  - **Canary:** backend-aws-canary
  - **LAB:** backend-lab (Jarvis Builder)
  - **Observabilidad:** Prometheus, Grafana, Alertmanager, cAdvisor, Node Exporter
- Alerta `HostSwapHigh` (PR #76): `(SwapTotal - SwapFree) / SwapTotal > 0.25` durante
  10m. **True positive — no suprimir, no tocar umbrales.**

### 2.1 Hallazgos de configuración

| Área | Hallazgo | Fuente |
|---|---|---|
| Límites memoria backend-aws | 2 GiB | `docker-compose.yml` backend-aws deploy.resources |
| Límites memoria backend-aws-canary | 1 GiB | `docker-compose.yml` backend-aws-canary |
| Límites memoria backend-lab | 2 GiB | `docker-compose.lab.yml` backend-lab |
| Límites memoria frontend-aws | 512 MiB | `docker-compose.yml` frontend-aws |
| postgres / observabilidad | **sin límite** (`mem_limit=0`) | `docker inspect` |
| Workers backend | 1 worker Gunicorn + UvicornWorker | compose command |
| Suma límites declarados | ~5.5 GiB vs 1.9 GiB RAM física | oversubscription |
| Solapamiento LAB/Canary/Prod | los tres backends Gunicorn en el mismo host | `docker ps` |

---

## 3. Datos del host (2026-06-26, read-only)

### 3.1 Memoria y swap

```text
               total        used        free      shared  buff/cache   available
Mem:           1.9Gi       1.5Gi        66Mi        40Mi       538Mi       359Mi
Swap:          2.0Gi       1.0Gi       1.0Gi

MemAvailable ≈ 19%  →  HostMemoryHigh (<10%) NO dispara
Swap usado ≈ 50%    →  HostSwapHigh (>25% por 10m) DISPARA (true positive)

Load average: 2.59, 2.25, 2.40  (2 vCPU — saturación sostenida)
Uptime host: 15 días
```

`vmstat 1 3` (muestra): `si/so` activo (swap in/out), CPU idle ~30–62% — thrashing
intermitente bajo presión de memoria.

### 3.2 Consumo por contenedor (`docker stats --no-stream`)

| Contenedor | RSS aprox. | Límite | CPU% |
|---|---|---|---|
| backend-lab | 215 MiB | 2 GiB | 72% (post-recreate) |
| backend-aws (prod) | 168 MiB | 2 GiB | 12% |
| backend-aws-canary | 55 MiB | 1 GiB | 8% |
| cAdvisor | 64 MiB | unlimited | 12% |
| postgres_hardened | 58 MiB | unlimited | 6% |
| prometheus | 55 MiB | unlimited | 1% |
| grafana | 37 MiB | unlimited | 0% |
| market-updater | 31 MiB | unlimited | 0% |
| frontend-aws | 5 MiB | 512 MiB | 0% |
| resto observabilidad | ~40 MiB | unlimited | — |

**Suma RSS contenedores:** ~704 MiB (stats). El resto de presión viene de procesos
host: `dockerd` (~212 MiB RSS), **Cursor extension host** (~212 MiB RSS + ~185 MiB
swap), `containerd`, workers Gunicorn visibles en `/proc`.

### 3.3 Top procesos por swap (VmSwap)

| Proceso | VmSwap |
|---|---|
| node (Cursor extension host) | ~185 MiB |
| python (canary gunicorn worker) | ~131 MiB |
| python (lab gunicorn worker) | ~81–131 MiB |
| dockerd | ~63 MiB |
| python3 (market-updater) | ~63 MiB |
| next-server (frontend) | ~49 MiB |

### 3.4 OOM killer

No ejecutado `dmesg`/`journalctl -k` en este cierre (requiere revisión explícita).
Sin incidentes OOM reportados en producción durante la ventana de investigación.

### 3.5 Umbrales de alerta (PR #76)

| Alerta | Expr | Estado 2026-06-26 |
|---|---|---|
| HostMemoryHigh | MemAvailable < 10% | NO (≈19%) |
| HostMemoryCritical | MemAvailable < 5% | NO |
| HostSwapHigh | Swap > 25% por 10m | **SÍ (~50%)** |
| HostCPUSaturated | CPU non-idle > 85% por 10m | borderline (load ~2.6/2) |

---

## 4. Análisis

- **Mayores consumidores:** tres backends Python (prod + canary + lab), dockerd,
  Cursor dev server en el host de producción, postgres + stack observabilidad sin
  límite cgroup.
- **Causa raíz:** no es una fuga puntual — es **capacidad insuficiente** para la
  carga acumulada de todos los perfiles en un solo `t3.small`, agravada por
  oversubscription de límites Docker y presencia de tooling de desarrollo (Cursor)
  en el host prod.
- **¿Sostenido o picos?** Swap ~50% de forma sostenida → presión **estructural**,
  no un pico transitorio del market updater.

---

## 5. Opciones y tradeoff

| Opción | Coste est. (ap-southeast-1 on-demand) | Riesgo | Blast radius | Notas |
|---|---|---|---|---|
| **A. Upgrade → t3.medium** (4 GiB) | ~+$15/mo vs t3.small | Bajo | Sin cambio (single-host) | Relief más rápido; LAB sigue junto a prod |
| **B. Split prod / LAB** | ~+$15/mo (2º t3.small) | Medio (migración LAB) | **Reducido para prod** | Alineado con `atp-lab-ssm-clean`; elimina conflicto `runtime.env` |
| **C. Híbrido** | ~+$30/mo | Medio-alto | Reducido | Upgrade prod + LAB fuera; máximo aislamiento |

**Mitigaciones sin coste (aprobadas por separado):**

- No ejecutar Cursor server en horario prod / mover sesiones dev fuera del host prod
- Reducir `backend-lab` mem limit de 2G → 512–768M mientras comparta host
- Pausar canary cuando no se esté probando activamente

---

## 6. Recomendación final

**Recomendar Opción B (split LAB)** como solución estructural:

- **Causa raíz:** single-host oversubscription en t3.small.
- **Alcance:** migrar `backend-lab` (+ opcional frontend-lab) a `i-0d82c172235770a0d`;
  prod host conserva aws profile + observabilidad.
- **Validación:** post-migración, `HostSwapHigh` debe bajar (<25% swap) en prod;
  LAB opera con creds en `runtime.env.lab` sin `cp` a `runtime.env` compartido.
- **Riesgo:** downtime de LAB durante migración; bajo riesgo para prod si solo se
  mueve el perfil `lab`.
- **Rollback:** revertir compose en host LAB; recrear backend-lab en prod host si
  necesario (estado actual documentado).

**Opción A** como paliativo inmediato si se necesita headroom esta semana sin migrar.

**Ningún cambio de instancia/contenedor aplicado en este cierre.**

---

## 7. Bitácora

| Fecha | Quién | Acción | Resultado |
|---|---|---|---|
| 2026-06-XX | Carlos / agente | Apertura del documento | Plantilla creada |
| 2026-06-26 | Cursor agent | Runbook read-only ejecutado en i-087953603011543c5 | Datos pegados; causa raíz confirmada |
| 2026-06-26 | Cursor agent | Cierre investigación + ADR-0002 actualizado | Recomendación: split LAB (B) |
