# Prompt para Cursor — habilitar gobernanza de escritura con aprobación por click

Copia lo de abajo en Cursor. Este cambio hace que el agente (Cowork/Claude) pueda hacer
push/PR/deploy **solo tras tu aprobación explícita por acción** (modelo de Gates), en lugar del
bloqueo total actual. Mantiene la revisión automática de las 22:00 en read-only (no hay humano
que apruebe a esa hora).

---

Trabaja en `ccruz0/crypto-2.0`. Objetivo: pasar la gobernanza de "bloqueo total de escrituras" a
"escrituras permitidas tras aprobación humana explícita por-acción (Gates)". NO habilites ejecución
autónoma sin aprobación.

**1. Flags de runtime (solo entorno interactivo/agente, NO la tarea cron de las 22:00)**
Los flags se leen por env en `backend/app/jarvis/change_execution/config.py`:
`JARVIS_PATCH_APPLY_ENABLED`, `JARVIS_PR_CREATION_ENABLED`, `JARVIS_GITHUB_WRITE_ENABLED`
(default false) y `JARVIS_REQUIRE_DOUBLE_APPROVAL` (default true).

Ponlos así en el entorno del agente interactivo (p.ej. el `.env`/compose del servicio de agente,
NO en el worker cron de la revisión diaria):
```
JARVIS_PATCH_APPLY_ENABLED=true
JARVIS_PR_CREATION_ENABLED=true
JARVIS_GITHUB_WRITE_ENABLED=true
JARVIS_REQUIRE_DOUBLE_APPROVAL=true   # mantener: exige Gate 1 (parche+tests) y Gate 2 (PR/push/deploy)
```
Verifica que el proceso de la revisión diaria (cron 22:00) NO herede estos flags: debe seguir en
read-only. Si comparten entorno, añade un override que fuerce los tres a `false` en ese contexto.

**2. Política en `CLAUDE.md`**
Sustituye las líneas de flags:
```
- `github_write_enabled = false`
- `pr_creation_enabled = false`
- `patch_apply_enabled = false`
```
por una sección que refleje el nuevo modelo, p.ej.:
```
Ejecución de cambios (Jarvis Gates): escrituras a producción permitidas SOLO tras aprobación
humana explícita y por-acción de Carlos.
- Gate 1 (aprobación) → aplicar parche + correr tests en sandbox. `patch_apply_enabled = true`
- Gate 2 (aprobación) → crear PR / push / deploy. `pr_creation_enabled = true`, `github_write_enabled = true`
- `require_double_approval = true`: ninguna escritura procede sin ambas aprobaciones.
- Sesiones AUTOMÁTICAS/no supervisadas (revisión diaria 22:00): SIEMPRE read-only, sin excepción.
- Invariables: sin secretos en contexto; no tocar el bucle de trading ni umbrales de alertas de host; no reabrir PR #61.
```

**3. (Opcional, recomendado) Punto de control de aprobación**
Si el flujo de Gates aún no exige una confirmación explícita registrada, añade en
`backend/app/jarvis/change_execution/` un check que exija un token/registro de aprobación por-acción
antes de ejecutar patch_apply (Gate 1) y PR/push/deploy (Gate 2), y que lo audite (quién, qué, cuándo).
Añade tests unitarios del gate (aprobado → procede; sin aprobación → bloquea).

**Restricciones**
- No habilites deploy autónomo. La aprobación por click de Carlos es obligatoria por acción.
- Cambio pequeño y auditable. Rama `chore/governance-approval-gates`, PR contra `main` con
  descripción de riesgo y rollback (revertir = los flags vuelven a false → bloqueo total).

**Entrega**: rama + PR con el link. Explica en el PR qué entornos reciben los flags y cómo se
garantiza que el cron de las 22:00 queda en read-only.
