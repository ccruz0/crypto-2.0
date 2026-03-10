# Cómo hacer que Notion “le diga” a Cursor que ejecute algo

Notion no tiene integración nativa que envíe acciones a Cursor (no hay “Notion → Cursor” directo). Estas son las formas en que **la tarea en Notion** acaba indicando qué debe hacer Cursor.

---

## 1. Comentario en la tarea (automático para triage)

Cuando el agente procesa una tarea de **monitoring triage** (por ejemplo “Investigate Telegram failure”):

1. Crea la nota de triage en `docs/runbooks/triage/notion-triage-{task_id}.md`.
2. Crea un handoff para Cursor en `docs/agents/cursor-handoffs/cursor-handoff-{task_id}.md`.
3. **Añade un comentario en la página de la tarea en Notion** con la instrucción para Cursor.

En la tarea de Notion verás algo como:

> **Cursor:** Para ejecutar los cambios, abre Cursor en el repo y di: "Ejecuta los pasos del triage" o "pick the triage and run the changes". Archivo: docs/runbooks/triage/notion-triage-{id}.md. O usa el Cursor Bridge: POST /api/agent/cursor-bridge/run con task_id.

Así **Notion “te dice”** qué hacer en Cursor: abres la tarea, ves el comentario y sigues la instrucción.

---

## 2. En Cursor: regla + frase

Hay una regla en `.cursor/rules/triage-run-fixes.mdc`: cuando dices en Cursor algo como:

- “Ejecuta los pasos del triage”
- “Pick the triage and run the changes”
- “Run the fixes from the triage”

Cursor lee los archivos en `docs/runbooks/triage/` y ejecuta la sección **“Cursor: run these steps”** del triage correspondiente (diagnóstico, runbook, reinicio, etc.).

No hace falta que Notion “llame” a Cursor: tú abres Cursor, usas la frase y Cursor hace el resto.

---

## 3. Cursor Bridge (API en el backend)

Si el backend/OpenClaw tiene acceso al repo (por ejemplo en el servidor):

```bash
curl -X POST https://dashboard.hilovivo.com/api/agent/cursor-bridge/run \
  -H "Content-Type: application/json" \
  -d '{"task_id": "5f1c9779-c707-4dd1-9fc3-801cda6dd55e"}'
```

El bridge carga el handoff `docs/agents/cursor-handoffs/cursor-handoff-{task_id}.md` y puede ejecutar los pasos (según cómo esté configurado el bridge en tu despliegue). Así **el sistema** (que conoce la tarea de Notion) “le dice” al Cursor Bridge qué tarea ejecutar.

---

## 4. Notion Automation → webhook (avanzado)

Puedes crear una **Automation** en Notion, por ejemplo:

- **Cuando:** una tarea pasa a un estado concreto (p. ej. “ready-for-investigation”) o se crea con una etiqueta.
- **Acción:** llamar a un **webhook** (URL de tu backend).

El backend podría:

- Crear o actualizar el handoff para esa tarea, y/o
- Llamar al Cursor Bridge con ese `task_id`.

Así Notion “dispara” la ejecución sin que tengas que copiar nada en Cursor (el flujo sería: Notion → webhook → backend → Cursor Bridge).

---

## Resumen

| Forma | Quién hace qué |
|-------|-----------------|
| **Comentario en la tarea** | El agente escribe en Notion la instrucción; tú la lees y en Cursor dices “ejecuta los pasos del triage”. |
| **Regla en Cursor** | Tú dices la frase en Cursor; la regla busca el triage y ejecuta los pasos. |
| **Cursor Bridge API** | Tu script o backend llama a `/api/agent/cursor-bridge/run` con `task_id`; el bridge usa el handoff de esa tarea. |
| **Notion Automation** | Notion dispara un webhook; el backend puede invocar al Cursor Bridge con el `task_id`. |

La opción más directa para “Notion le dice a Cursor” es la **1 + 2**: el comentario en la tarea te dice qué decir en Cursor, y la regla hace que Cursor ejecute los pasos del triage.
