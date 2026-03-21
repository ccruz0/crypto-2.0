# Verification Unavailable vs Verification Failed

When solution verification runs, the system distinguishes between:

1. **Verification passed** — Output addresses task requirements.
2. **Verification failed** — Output does not address task requirements (investigative failure).
3. **Verification unavailable** — Verification could not run due to environment/configuration (e.g. OpenClaw not configured locally).

## Behavior by outcome

| Outcome | Notion status | Telegram | Log event |
|---------|---------------|----------|-----------|
| Passed | ready-for-deploy | Deploy approval (standard) | `verification_passed` |
| Failed | needs-revision | Re-investigate | `verification_failed` |
| Unavailable | ready-for-deploy | Deploy approval with warning | `verification_unavailable` |

## Verification unavailable

When verification cannot run (e.g. `OPENCLAW_API_URL` / `OPENCLAW_API_TOKEN` not set), the system:

- Does **not** move the task to Needs Revision
- Does **not** send "Re-investigate"
- Advances to **ready-for-deploy**
- Sends a deploy approval message indicating:
  - Patch is ready
  - Verification is unavailable (environment not configured)
  - Approval can proceed manually or verification can be skipped

## Structured logs

- `verification_passed` — Verification ran and passed
- `verification_failed` — Verification ran and failed (bad solution)
- `verification_unavailable` — Verification could not run (env/config)
- `verification_unavailable_reason` — Included in `verification_unavailable` event details

## Validation

1. **OpenClaw unconfigured** — Task should NOT go to Needs Revision; should send patch-ready-with-warning message.
2. **Verification disabled** (`ATP_SOLUTION_VERIFICATION_ENABLED=false`) — Goes directly to deploy approval.
3. **Actual failing verification** — Goes to Re-investigate.
