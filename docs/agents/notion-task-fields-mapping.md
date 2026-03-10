# Mapeo: campos que envías → Notion AI Task System

Cuando creas tareas con campos como **Task Title**, **Description**, **Objective**, etc., así se relacionan con las propiedades de Notion y con lo que usa el backend.

## Campos que estás mandando → Notion / backend

| Campo que envías | Propiedad en Notion (nombre exacto) | Tipo sugerido | Uso en backend |
|------------------|-------------------------------------|---------------|----------------|
| **Task Title** | `Task Title` o `Task` o `Name` | Title o Text | Título de la tarea (`task`) |
| **Description** | `Description` o `Details` | Rich text | Descripción principal (`details`) |
| **Objective** | `Objective` | Rich text | Solo Notion (opcional) |
| **Expected Behaviour** | `Expected Behaviour` | Rich text | Solo Notion (opcional) |
| **Current Behaviour** | `Current Behaviour` | Rich text | Solo Notion (opcional) |
| **Investigation Scope** | `Investigation Scope` | Rich text | Solo Notion (opcional) |
| **Expected Output from Investigation** | `Expected Output from Investigation` | Rich text | Solo Notion (opcional) |
| **Risk Level** | `Risk Level` | Text o Select | Sí (`risk_level`) |
| **Priority** | `Priority` | Text o Select | Sí (`priority`) |

El backend ya acepta **Task Title** y **Description** como alias: si en Notion tienes esas propiedades, las usa para `task` y `details`. El resto (Objective, Expected Behaviour, etc.) puedes guardarlos en Notion para la investigación; el backend no los lee.

## Propiedades mínimas para que el backend funcione

- **Task** o **Name** o **Task Title** → título.
- **Status** → estado (planned, in-progress, awaiting-deploy-approval, etc.).
- **Details** o **Description** → descripción.
- **Priority** → prioridad.
- **Risk Level** (opcional).
- **Test Status**, **Deploy Progress**, etc. (según el resto del esquema).

## Prompt para Notion AI: crear estos campos

Copia y pega esto en Notion AI (o úsalo como checklist) para crear en la base **AI Task System** las propiedades que estás mandando:

---

En la base de datos **AI Task System**, añade estas propiedades con **estos nombres exactos** (en inglés). Si alguna ya existe, no la dupliques.

- **Task Title** — Title (o Text/Rich text si prefieres no usar el título de página).
- **Description** — Rich text (descripción principal del problema).
- **Objective** — Rich text (objetivo de la tarea).
- **Expected Behaviour** — Rich text (comportamiento esperado).
- **Current Behaviour** — Rich text (comportamiento actual).
- **Investigation Scope** — Rich text (alcance de la investigación).
- **Expected Output from Investigation** — Rich text (resultado esperado de la investigación).
- **Risk Level** — Text o Select (ej. Unknown, Low, High).
- **Priority** — Text o Select (ej. High, Medium, Low).

Además, para el flujo de agentes y deploy, conviene tener también: **Status** (Select o Rich text), **Type** (ej. Bug/Feature), **Project**, **Source**, **Test Status** (Text), **Deploy Progress** (Number 0–100). Los nombres deben ser exactos.

---

Con esto, lo que envías (Task Title, Description, Objective, etc.) queda guardado en Notion y el backend puede leer título y descripción aunque uses **Task Title** y **Description**.
