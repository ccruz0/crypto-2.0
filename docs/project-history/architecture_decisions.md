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

**Estado:** RECOMENDADA (investigación cerrada 2026-06-26; **sin implementación**).
**Depende de:** `swap_investigation.md` (datos del host 2026-06-26).

### Contexto

`HostSwapHigh` es un true positive (PR #76). El disco ya se resolvió (30→50 GB).
El riesgo dominante es ahora la memoria. Investigación read-only en
`i-087953603011543c5` confirmó swap ~50% sostenido, MemAvailable ~19%, y
oversubscription de límites Docker (~5.5 GiB declarados en 1.9 GiB RAM).

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

#### Opción B — Split Producción / LAB (hosts separados)

Mover LAB (Jarvis Builder) al host dedicado `atp-lab-ssm-clean`
(`i-0d82c172235770a0d`), como describe el runbook original.

- **Pros:** aísla Producción del ruido de LAB; reduce blast radius; permite
  `runtime.env.lab` sin `cp` a `runtime.env` compartido; alinea docs y diseño.
- **Contras:** migración LAB (compose, secretos, verificación); dos hosts que
  mantener.
- **Coste:** ~USD 15/mo incremental (segundo t3.small).
- **Riesgo:** medio (solo LAB afectado en migración; prod intacto si scope estricto).
- **Blast radius:** reducido para Producción.

#### Opción C — Híbrido

Upgrade prod a t3.medium **y** mover LAB a host dedicado.

- **Pros:** máximo headroom en prod + aislamiento LAB.
- **Contras:** mayor coste y complejidad.
- **Coste:** ~USD 30/mo incremental.
- **Riesgo / Blast radius:** bajo en prod post-upgrade; LAB aislado.

### Matriz de decisión

| Criterio | A. Upgrade | B. Split | C. Híbrido |
|---|---|---|---|
| Coste mensual | ~+$15 | ~+$15 | ~+$30 |
| Riesgo de migración | bajo | medio (solo LAB) | medio-alto |
| Blast radius resultante | sin cambio | reducido | mínimo |
| Complejidad operativa | baja | media | alta |
| Tiempo a implementar | horas | 1–2 días | 2–3 días |
| Reversibilidad / rollback | alta | media | media |
| Alineación arquitectura LAB | no | **sí** | **sí** |

### Decisión

**Recomendación: Opción B (split LAB)** — más segura y coste-efectiva a largo plazo
para aislar prod de Jarvis Builder y eliminar el antipatrón de secretos LAB en el
host prod.

**Opción A** como paliativo de emergencia si swap supera umbrales críticos antes de
poder migrar LAB.

**Requiere aprobación humana** antes de: resize de instancia, launch/migrate LAB host,
o cambios de compose en prod.

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
