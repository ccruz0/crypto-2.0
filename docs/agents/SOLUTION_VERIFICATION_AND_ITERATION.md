# Solution Verification and Iteration

The agent task lifecycle includes a **solution verification** step before deploy. This ensures the output actually addresses the task requirements, not just passes format checks.

## Flow

1. **Investigation** → OpenClaw produces output (audit note, findings, etc.)
2. **Patch approval** → Human approves moving forward
3. **Validation** → Format check (file exists, structured sections, minimum length)
4. **Solution verification** → OpenClaw evaluates: *Does this output address the task?*
   - **PASS** → Proceed to deploy approval
   - **FAIL** → Task moves to `needs-revision`; feedback stored for next iteration
5. **Re-investigate** → Human clicks button in Telegram; task moves to `ready-for-investigation`; scheduler re-runs apply with feedback
6. **Deploy** → Only when verification passes

## Enabling

Solution verification is **enabled by default**. To disable (legacy behavior):

```bash
ATP_SOLUTION_VERIFICATION_ENABLED=false
```

## Notion: Add `needs-revision` Status

If your Notion "AI Task System" database uses a **Select** property for Status, add:

- **needs-revision** (or "Needs Revision")

If Status is **rich text**, the backend writes the lowercase value; Notion will accept it.

## Telegram: Re-investigate Button

When verification fails, a Telegram message is sent with:

- **Re-investigate** — Moves task to `ready-for-investigation`; scheduler re-runs with feedback
- **View Report** — Shows the current output

## Feedback Storage

Verification feedback is stored in:

```
docs/agents/verification-feedback/<task_id>.txt
```

The next apply run reads this file and appends it to the OpenClaw prompt. The file is deleted after a successful verification pass.
