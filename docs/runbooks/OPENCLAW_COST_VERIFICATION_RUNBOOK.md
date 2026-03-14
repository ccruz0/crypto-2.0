# OpenClaw Cost Verification Runbook

**When:** After enabling cost levers (verification model, etc.) to confirm model usage and token telemetry.

## 1. Run one Notion task

**On PROD (via SSM):**
```bash
./scripts/run_notion_task_pickup_via_ssm.sh
```

**On LAB or local (with Docker):**
```bash
NOTION_TASK_DB=eb90cfa139f94724a8b476315908510a ./scripts/run_notion_task_pickup.sh
```

Ensure at least one **Planned** task exists in the Notion AI Task System DB.

## 2. Check logs

| Log pattern | Meaning |
|-------------|---------|
| `openclaw_client: primary_model=...` | Main chain first model |
| `openclaw_apply_cost task_id=... model_used=... usage=...` | Per-task cost; `usage` shows token counts when gateway returns them |
| Verification-related lines | Verification model used when `ATP_SOLUTION_VERIFICATION_ENABLED=true` |

**Verify:** Model and usage match expectations (cheap-first, verification on cheap model if configured).

## 3. Verify gateway returns usage (optional)

If `openclaw_apply_cost` shows `usage=None`, the gateway may not be forwarding provider token counts. Run:

```bash
OPENCLAW_GATEWAY_URL=http://127.0.0.1:8080 OPENCLAW_API_TOKEN=<token> ./scripts/openclaw/verify_gateway_model_routing.sh
```

The script prints `usage:` when present. If absent, fix in the OpenClaw gateway repo (see `docs/OPENCLAW_COST_OPTIMIZATION_AUDIT.md` §1.2).
