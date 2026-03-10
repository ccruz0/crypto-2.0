# Estructura de prompts para Notion — instrucciones para ChatGPT

**Resumen:** Instrucciones para que ChatGPT (u otro LLM) genere prompts listos para copiar en Notion AI y crear o alinear propiedades en la base **AI Task System** con nombres exactos y tipos correctos. Incluye formato de cada línea, tipos de Notion, lista de propiedades que usa el backend y ejemplo completo.

Usa este documento como **contexto para ChatGPT** (o otro LLM). Cuando el usuario pida "crea un prompt para Notion para X", ChatGPT debe generar un prompt que siga la estructura y convenciones siguientes.

---

## Contexto

- Los prompts son para la base de datos de Notion llamada **AI Task System** (sistema de tareas para agentes y deploy).
- Una integración/backend lee y escribe propiedades de esa base; los **nombres de las propiedades deben ser exactos** (incluyendo mayúsculas, minúsculas y espacios). Si el nombre no coincide, el backend no encuentra la propiedad.
- El objetivo del prompt es que **Notion AI** (o un humano) pueda crear o alinear propiedades en esa base sin ambigüedad.

---

## Estructura del prompt para Notion

Todo prompt que genere ChatGPT para Notion debe:

1. **Indicar la base de datos**  
   Empezar con: "En la base de datos **AI Task System**" (o el nombre que el usuario indique).

2. **Decir la acción**  
   Por ejemplo: "añade estas propiedades", "crea estos campos", "asegúrate de que existan estas propiedades".

3. **Listar cada propiedad en una línea** con:
   - **Nombre exacto** entre asteriscos o en negrita: `**Nombre de la propiedad**`
   - Un guión largo o dos guiones: `—` o `--`
   - **Tipo de Notion**: Title, Text, Rich text, Number, Select, Multi-select, URL, Date, Checkbox, etc.
   - Opcional: valores sugeridos para Select (entre paréntesis), rango para Number (ej. 0–100), o una nota breve.

4. **Regla de duplicados**  
   Incluir una frase como: "Si alguna propiedad ya existe, no la dupliques" o "Salta las que ya estén creadas".

5. **Cierre**  
   Opcional: "Los nombres deben ser exactos." / "Usa estos nombres tal cual."

---

## Formato de cada línea de propiedad

```
- **Nombre Exacto de la Propiedad** — Tipo (nota opcional).
```

Ejemplos:

- **Task Title** — Title (o Text si no usas el título de la página).
- **Description** — Rich text (descripción principal).
- **Status** — Select o Rich text (valores: planned, in-progress, testing, awaiting-deploy-approval, deploying, done, blocked).
- **Priority** — Select o Text (ej. High, Medium, Low).
- **Risk Level** — Text o Select (ej. Unknown, Low, High).
- **Deploy Progress** — Number, 0–100 (barra de progreso de deploy).
- **Test Status** — Text (resultado de tests; lo usa el flujo de deploy).
- **GitHub Link** — URL.

---

## Tipos de Notion a usar

- **Title**: título de la página (solo uno por página).
- **Text** / **Rich text**: texto libre; Rich text permite formato.
- **Number**: numérico; indicar rango si importa (ej. 0–100).
- **Select**: una opción; listar valores sugeridos entre paréntesis.
- **Multi-select**: varias opciones.
- **URL**: enlace.
- **Date**: fecha (con o sin hora).
- **Checkbox**: sí/no.

Si el backend escribe la propiedad, preferir **Text/Rich text** o **Select** según lo que ya use el sistema (ver esquema en `notion-ai-task-system-schema.md`).

---

## Propiedades que el backend usa (referencia)

Para no inventar nombres, al generar prompts de "todas las propiedades" o "esquema completo", incluir al menos estas (nombres exactos):

- Task, Name o Task Title (título)
- Description o Details (descripción)
- Project, Type, Status, Priority, Source
- Risk Level, Repo, Environment
- OpenClaw Report URL, Cursor Patch URL
- Test Status, Deploy Approval, Final Result
- Deploy Progress (Number 0–100)
- Current Version, Proposed Version, Approved Version, Released Version, Version Status, Change Summary
- GitHub Link (URL)

---

## Idiomas

- El usuario puede pedir el prompt **en español** o **en inglés**.
- Los **nombres de las propiedades** deben quedarse siempre **en inglés** (así están en el backend y en la base).
- Las instrucciones alrededor ("añade", "si ya existe", "tipo") sí en el idioma que pida el usuario.

---

## Ejemplo completo (para copiar como plantilla)

Cuando el usuario diga "genera un prompt para Notion para crear los campos de investigación", ChatGPT puede producir algo como:

```
En la base de datos **AI Task System**, añade estas propiedades con **estos nombres exactos** (en inglés). Si alguna ya existe, no la dupliques.

- **Task Title** — Title (o Text/Rich text).
- **Description** — Rich text (descripción principal del problema).
- **Objective** — Rich text (objetivo de la tarea).
- **Expected Behaviour** — Rich text (comportamiento esperado).
- **Current Behaviour** — Rich text (comportamiento actual).
- **Investigation Scope** — Rich text (alcance de la investigación).
- **Expected Output from Investigation** — Rich text (resultado esperado).
- **Risk Level** — Text o Select (ej. Unknown, Low, High).
- **Priority** — Text o Select (ej. High, Medium, Low).

Para el flujo de agentes conviene tener también: **Status** (Select o Rich text), **Type** (ej. Bug, Feature), **Project**, **Source**, **Test Status** (Text), **Deploy Progress** (Number 0–100). Los nombres deben ser exactos.
```

---

## Resumen para ChatGPT

- Base: **AI Task System**.
- Cada propiedad: **nombre exacto** + **tipo** + nota opcional.
- Formato: `- **Nombre** — Tipo (nota).`
- Incluir: "no dupliques si ya existe" y "nombres exactos".
- Nombres de propiedades siempre en inglés; el resto del texto en el idioma que pida el usuario.
- Para esquemas completos, usar la lista de propiedades que el backend usa (arriba o en `notion-ai-task-system-schema.md`).
