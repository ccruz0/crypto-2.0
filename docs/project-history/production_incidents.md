# Incidentes de producción (historial)

Fuente de verdad persistente de incidentes de producción de ATP/Jarvis,
independiente de cualquier herramienta de chat. Mantener actualizado.

> **Reglas heredadas del `CLAUDE.md` (no relitigar):**
> - El **Signal Monitor está resuelto por PR #62**. No revisitar ni resucitar
>   PR #61 (fue revertido).
> - `HostSwapHigh` y el resto de alertas de host de PR #76 son **true
>   positives**: no suprimir, no cambiar umbrales.

---

## 1. Incidente: Signal Monitor — locking / RUN_LOCKED

**Estado:** RESUELTO (PR #62 en producción).

### Línea temporal

1. **PR #60 — origen del incidente.**
   Introdujo problemas de locking en el Signal Monitor:
   - Tormentas de `RUN_LOCKED`.
   - Ciclos de monitoreo atascados (stuck monitoring cycles).
   - Fugas de advisory locks (advisory lock leaks).

2. **PR #61 — rediseño, REVERTIDO.**
   Intento de rediseño que no quedó como solución. **Fue revertido.**
   → **No revisitar. No resucitar. No relitigar.**

3. **PR #62 — solución final aceptada (lo que corre hoy en producción).**
   Estado verificado en producción:
   - **0 `RUN_LOCKED`.**
   - **0 lock waiters.**
   - **100+ ciclos estables.**

### Lección / guardrail

El locking del Signal Monitor es un tema cerrado. Cualquier trabajo futuro que
toque esta área debe partir de PR #62 como baseline, no reabrir el enfoque de
PR #61.

---

## 2. Observabilidad: alertas de host (PR #76)

**Estado:** DESPLEGADO y ACTIVO. Validado con promtool.

### Cambios

- **Añadidas** las alertas de host:
  - `HostMemoryHigh`
  - `HostMemoryCritical`
  - `HostSwapHigh`
  - `HostCPUSaturated`
- **Eliminada:** `TestTelegramAlert`.

### Estado y guardrail

- `HostSwapHigh` es **correcto / true positive**. **No suprimir ni ajustar sus
  umbrales.**
- **2026-07-22:** host resizeado a `t3.medium`; swap post-reboot ≈ 0%. Ver
  `host-swap-followup-2026-07-22.md` y ADR-0002 (Opción A aplicada). La alerta
  debe poder resolver sola con swap &lt;25% sostenido; no tocar reglas.

---

## 3. Resuelto previamente: presión de disco

**Estado:** RESUELTO como outage (expand 30→50 GB); **reactivado como riesgo
secundario** el 2026-07-22 (~82% usado). Ver follow-up de limpieza (imágenes /
build cache / caches Cursor) — sin prune hasta aprobación humana.

- El disco se expandió **30 GB → 50 GB**.
- Tras el expand el uso bajó ~48%; a 2026-07-22 volvió a ~82% (containerd images
  + Cursor/npm caches).

---

## Plantilla para nuevos incidentes

```markdown
## Incidente: <título>

**Estado:** ABIERTO / MITIGADO / RESUELTO
**Fecha de detección:** YYYY-MM-DD
**Severidad:** _
**Detectado por:** alerta / humano / Jarvis

### Síntoma

### Línea temporal
1. ...

### Causa raíz

### Resolución (PR(s) / cambios)

### Validación

### Lección / guardrail
```
