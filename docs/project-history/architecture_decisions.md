# Decisiones de arquitectura (ADR ligero)

Registro de decisiones de arquitectura de ATP/Jarvis. Formato ADR ligero.
Mantener como fuente de verdad persistente, independiente del chat.

---

## ADR-0001 — Single-host hoy (estado actual)

**Estado:** VIGENTE (estado actual del sistema).

### Contexto

Toda la plataforma corre hoy en **un único host**: AWS `t3.small`, 2 vCPU,
**2 GB RAM**, 50 GB disco, región `ap-southeast-1`. En ese host conviven **13
contenedores**:

- **Producción:** FastAPI backend · Next.js frontend · PostgreSQL · market
  updater · Telegram alerts.
- **Canary:** backend canary.
- **LAB:** backend lab.
- **Observabilidad:** Prometheus · Grafana · Alertmanager · cAdvisor ·
  Node Exporter.

### Consecuencia / problema

Producción, LAB, Canary y Observabilidad **comparten RAM**. Esto genera presión
de memoria y swap (`HostSwapHigh`, swap ~54%) y un **blast radius compartido**:
un consumidor de LAB/Canary/observabilidad puede degradar Producción. Es el
detonante de la decisión ADR-0002.

---

## ADR-0002 — Resolver la presión de memoria/swap: upgrade vs split vs híbrido

**Estado:** RECOMENDADA (investigación 2026-06-26; **sin implementación de capacidad**).
**Actualización 2026-07-17:** ver `host-swap-status-2026-07-17.md` (síntesis + corrección de target LAB).
**Depende de:** `swap_investigation.md`, `host-swap-investigation-2026-07-10.md`.

### Contexto

`HostSwapHigh` es un true positive (PR #76). El disco ya se resolvió (30→50 GB).
El riesgo dominante es la memoria. Investigación read-only en
`i-087953603011543c5` confirmó swap ~50% sostenido, MemAvailable ~19%, y
oversubscription de límites Docker (~5.5 GiB declarados en 1.9 GiB RAM).

Mitigación aguda 2026-07-06 (procesos huérfanos `docker compose logs` → dockerd
CPU 183%) **no sustituye** esta ADR: el snapshot 2026-07-10 seguía con ~50% swap.

### Opciones

#### Opción A — Upgrade del host

Subir el tipo de instancia (p. ej. `t3.small` → `t3.medium` (4 GB) o
`t3.large` (8 GB)).

- **Pros:** mínimo cambio operativo; sigue siendo un solo host; despliegue
  rápido; rollback simple (volver al tipo anterior).
- **Contras:** no aísla blast radius (LAB/Canary siguen junto a Producción);
  coste mensual mayor permanente; no resuelve el conflicto arquitectónico LAB
  compartiendo `runtime.env` con prod.
- **Coste:** ~USD 15/mo incremental (t3.small → t3.medium on-demand,
  ap-southeast-1, orden de magnitud).
- **Riesgo:** bajo (resize instance type, breve reinicio).
- **Blast radius:** sin cambio (compartido).

#### Opción B — Split Producción / Jarvis Builder (hosts separados)

Sacar `backend-lab` / Jarvis Builder del host PROD. **No** usar
`atp-lab-ssm-clean` (`i-0d82c172235770a0d`) — ese host es **OpenClaw only**
(`INSTANCE_SOURCE_OF_TRUTH.md`). Destino correcto: host Builder dedicado
(p. ej. `atp-lab-builder` en `LAB_JARVIS_BUILDER_BOOTSTRAP.md`) o mantener
Builder apagado en PROD cuando idle.

- **Pros:** aísla Producción del ruido de LAB; reduce blast radius; permite
  `runtime.env.lab` sin `cp` a `runtime.env` compartido; alinea docs y diseño.
- **Contras:** migración LAB (compose, secretos, verificación); dos hosts que
  mantener (o coste de un Builder nuevo).
- **Coste:** ~USD 15/mo incremental (segundo t3.small) si se lanza Builder;
  ~$0 si solo se para `backend-lab` en PROD cuando idle.
- **Riesgo:** medio (solo LAB afectado en migración; prod intacto si scope estricto).
- **Blast radius:** reducido para Producción.

#### Opción C — Híbrido

Upgrade prod a t3.medium **y** mover Jarvis Builder fuera de PROD (no a OpenClaw LAB).

- **Pros:** máximo headroom en prod + aislamiento LAB.
- **Contras:** mayor coste y complejidad.
- **Coste:** ~USD 30/mo incremental.
- **Riesgo / Blast radius:** bajo en prod post-upgrade; LAB aislado.

### Matriz de decisión

| Criterio | A. Upgrade | B. Split Builder | C. Híbrido |
|---|---|---|---|
| Coste mensual | ~+$15 | ~+$15 (o $0 si pause) | ~+$30 |
| Riesgo de migración | bajo | medio (solo Builder) | medio-alto |
| Blast radius resultante | sin cambio | reducido | mínimo |
| Complejidad operativa | baja | media | alta |
| Reversibilidad / rollback | alta | media | media |
| Alineación arquitectura LAB | no | **sí** | **sí** |
| Respeta OpenClaw-only LAB | n/a | **sí** (Builder ≠ OpenClaw) | **sí** |

### Decisión

**Recomendación: Opción B (sacar Jarvis Builder de PROD)** — más segura y
coste-efectiva a largo plazo. Destino ≠ OpenClaw LAB.

**Opción A** como paliativo de emergencia si `vmstat` muestra `si/so` activo y
swap thrashing antes de poder migrar/parar Builder.

**Requiere aprobación humana** antes de: resize de instancia, stop de
contenedores en prod, launch/migrate Builder host, o cambios de compose en prod.

**Validación post-implementación:**

- Prod: `HostSwapHigh` resuelto o swap <25% sostenido; prod health OK.
- LAB: backend-lab healthy en host dedicado; Bedrock STS + invoke OK.

**Rollback:** revertir tipo de instancia (A) o recrear backend-lab en host prod
(B) usando snapshot documentado del compose actual.

---

## Plantilla para nuevas ADR

```markdown
## ADR-NNNN — <título>

**Estado:** PROPUESTA / VIGENTE / SUPERADA por ADR-MMMM
**Fecha:** YYYY-MM-DD

### Contexto

### Opciones consideradas

### Decisión

### Consecuencias
```
