# AI Task System — Notion schema (all fields the backend uses)

Use this list to add or align properties in your **AI Task System** Notion database. Property **names** must match exactly (including spelling and spaces); types can be the suggested ones so the backend can read and write them.

## Core task properties (usually already present)

| Property name   | Notion type   | Notes |
|-----------------|---------------|--------|
| **Task** or **Name** | Title | Task title (backend accepts either "Task" or "Name"). |
| **Project**     | Select or Text | e.g. "pto Trading", "Trading-bot". |
| **Type**        | Select or Text | e.g. "Bug", "Feature". |
| **Status**      | Select or Rich text | Values: `planned`, `in-progress`, `testing`, `awaiting-deploy-approval`, `deploying`, `done`, `blocked`, or legacy: `Planned`, `Deployed`, etc. Backend writes Status when advancing tasks. |
| **Priority**     | Select or Text | e.g. critical, high, medium, low. |
| **Source**      | Select or Text | e.g. "Trading-bot". |
| **Details**     | Rich text or Text | Optional description. |
| **GitHub Link** | URL | Optional link. |

## Versioning (optional)

| Property name        | Notion type   | Notes |
|----------------------|---------------|--------|
| **Current Version**  | Text / Rich text | Written by versioning flow. |
| **Proposed Version** | Text / Rich text | |
| **Approved Version** | Text / Rich text | |
| **Released Version** | Text / Rich text | |
| **Version Status**   | Text / Rich text or Select | e.g. proposed, approved, released, rejected. |
| **Change Summary**   | Text / Rich text | |

## Extended metadata (agent / deploy)

| Property name            | Notion type   | Notes |
|--------------------------|---------------|--------|
| **Risk Level**           | Text / Rich text or Select | Optional. |
| **Repo**                 | Text / Rich text | Optional. |
| **Environment**          | Text / Rich text | Optional. |
| **OpenClaw Report URL**  | URL or Text | Written when OpenClaw report exists. |
| **Cursor Patch URL**      | URL or Text | Written when Cursor bridge produces a patch/PR. |
| **Test Status**          | Text / Rich text | Written after tests run; read by deploy approval gate. **Add this** to avoid fallback message. |
| **Deploy Approval**      | Text / Rich text | Optional audit. |
| **Final Result**         | Text / Rich text | Optional. |
| **Deploy Progress**      | **Number** | 0–100; used as progress bar during deploy. Set display to "Progress" in Notion if available. |

## Status values the backend uses

When **Status** is a Select, these values are used by the backend:

- `planned`, `backlog`
- `in-progress`, `ready-for-investigation`, `investigation-complete`
- `ready-for-patch`, `patching`, `testing`
- `awaiting-deploy-approval`, `deploying`
- `done`, `blocked`
- Legacy: `Planned`, `Deployed`, `Monitoring`, etc. (backend accepts both cases)

If Status is **Rich text**, the backend writes the same values as text.

## One-time setup

1. Open the **AI Task System** database in Notion.
2. For each property in the tables above that you want the backend to use, add it with the **exact** name and a compatible type (Text/Rich text for most; Number for Deploy Progress; URL for URL fields).
3. For **Status**, either use a Select with the values above or keep it as Rich text so the backend can write any status string.
