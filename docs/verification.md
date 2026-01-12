# Verification Toolkit

## Run verification (EC2)

```bash
cd ~/automated-trading-platform
bash scripts/verify_invariant.sh --hours 12 --limit 500
```

Notes:
- If the AWS backend listens on 8002 (default in `docker-compose.yml`), add `--backend-port 8002`.
- The script uses `docker compose --profile aws` and reads Postgres creds from `.env`/`.env.aws`.

## Expected PASS output

You should see:
- `boot_check: ok`
- `missing_intent: 0`
- `null_decisions: 0`
- `failed_without_telegram: 0`
- `diagnostics pass: True`
- `violations: 0`

## What to do on FAIL

1) Review the report section for which invariant failed.
2) Inspect diagnostics violations (printed at the bottom of the report).
3) Check backend logs for orchestrator errors:

```bash
cd ~/automated-trading-platform
docker compose --profile aws logs --tail 300 backend-aws
```

4) If signals are missing `order_intent`, verify the orchestrator path in `backend/app/services/signal_monitor.py` and re-run the check.

## Safe self-test endpoint (dry run)

This endpoint is protected by diagnostics auth. Set these env vars on the backend service:
- `ENABLE_DIAGNOSTICS_ENDPOINTS=1`
- `DIAGNOSTICS_API_KEY=<your_key>`

Run from inside the backend container:

```bash
cd ~/automated-trading-platform
docker compose --profile aws exec -T backend-aws \
  curl -s -X POST \
  -H "X-Diagnostics-Key: $DIAGNOSTICS_API_KEY" \
  "http://localhost:8002/api/diagnostics/run-e2e-test?dry_run=true"
```

The response includes pipeline stages, simulated outcomes, and created order_intents/decision traces.
