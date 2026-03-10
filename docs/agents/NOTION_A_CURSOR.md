# Cómo hace Notion que Cursor ejecute algo

Notion no tiene una integración directa con Cursor (el IDE). La forma de que “Notion le diga a Cursor” que haga algo es a través del **backend** y de los **handoffs**.

---

## 1. Flujo automático (recomendado): Tarea → triage → handoff → Cursor Bridge

Cuando el agente (OpenClaw/backend) procesa una **tarea de Notion** de tipo monitoring triage:

1. Crea la nota de triage en `docs/runbooks/triage/notion-triage-{task_id}.md`.
2. **Desde este cambio:** también crea un **Cursor handoff** en `docs/agents/cursor-handoffs/cursor-handoff-{task_id}.md` con la instrucción de ejecutar los pasos del triage.

Luego tú puedes hacer que Cursor ejecute ese handoff de dos maneras:

| Cómo | Qué hacer |
|------|-----------|
| **Telegram** | Cuando apruebes la tarea en Telegram, si existe el handoff aparecerá el botón **"🛠️ Run Cursor Bridge"**. Al pulsarlo, el backend envía a Cursor el contenido del handoff (ejecutar los pasos del triage). |
| **API** | Llamar `POST /api/agent/cursor-bridge/run` con `{"task_id": "ID_DE_LA_PAGINA_NOTION"}`. El backend usa el handoff de ese `task_id` y lo pasa a Cursor. |

Así, **Notion “le dice” a Cursor** de forma indirecta: la tarea en Notion hace que el backend genere el triage + el handoff; al usar Telegram o la API, Cursor recibe la instrucción de ejecutar ese triage.

---

## 2. Notion Automation (webhook) — opcional

Si quieres que **Notion dispare** la ejecución sin tocar Telegram ni la API a mano:

1. En Notion: **Automations** de la base “AI Task System” → cuando se cumpla una condición (por ejemplo “Status = ready-for-patch” o “Página editada”).
2. Acción: **Send webhook** a una URL de tu backend, por ejemplo:
   - `POST https://dashboard.hilovivo.com/api/agent/cursor-bridge/run`
   - Body: `{"task_id": "<page_id de la página>"}` (el page_id lo puede enviar la automation con la variable de la página).

Requisitos: el endpoint debe estar accesible desde Notion (y, en producción, protegido con un token o IP si lo expones). En el repo no hay aún un endpoint específico para “webhook de Notion”; hoy se usa el mismo `POST /api/agent/cursor-bridge/run` con `task_id`.

---

## 3. Manual: instrucción en la tarea

En la **descripción o detalles** de la tarea en Notion puedes poner, por ejemplo:

- “Para ejecutar en Cursor: di ‘Ejecuta los pasos del triage para esta tarea’ o abre `docs/runbooks/triage/notion-triage-<id>.md` y sigue la sección **Cursor: run these steps**.”
- O: “Trigger: POST /api/agent/cursor-bridge/run con task_id = [id de esta página].”

Así Notion “le dice” a una persona (o a un agente que lea la tarea) qué hacer en Cursor o qué API llamar.

---

## Resumen

| Método | Quién “dice” | Quién ejecuta en Cursor |
|--------|----------------|--------------------------|
| Tarea → triage → handoff + **Telegram “Run Cursor Bridge”** | Notion (tarea) → backend (handoff) | Tú pulsas el botón → backend invoca Cursor con el handoff |
| Tarea → triage → handoff + **API** `cursor-bridge/run` | Tú (o un script) llamas API con `task_id` | Backend invoca Cursor con el handoff de esa tarea |
| **Notion Automation** → webhook a `cursor-bridge/run` | Notion automation envía `task_id` | Backend invoca Cursor con el handoff |
| **Texto en la tarea** | Lo que escribes en Details | Tú (o un agente) lees y ejecutáis en Cursor o vía API |

Para la tarea **Investigate Telegram failure** (`5f1c9779-c707-4dd1-9fc3-801cda6dd55e`) ya existe el handoff; puedes usar **Telegram (Run Cursor Bridge)** o **POST /api/agent/cursor-bridge/run** con ese `task_id` para que Cursor ejecute los pasos del triage.
