# EC2 DB Reachability and Order Intents Runbook

## Symptom pattern

- `/health` returns **200**
- `/api/health/system` returns **FAIL** (e.g. 503 or timeout)
- Logs show psycopg2 timeout connecting to **172.19.x.x** (or similar Docker IP)

## Root cause

Docker assigns container IPs that can change. If `DATABASE_URL` uses a concrete IP (e.g. `172.19.0.5`) instead of the stable Compose service name, the backend may be pointing at a stale or wrong host. The service name **`db`** is stable on the Compose network.

## Run diagnostic

On the EC2 instance:

```bash
cd /home/ubuntu/automated-trading-platform
bash scripts/aws/diag_db_and_order_intents.sh
```

## Interpret results

| Case | Observation | Meaning |
|------|-------------|--------|
| **A** | TCP to `db` works, TCP to parsed host (IP) fails | `DATABASE_URL` is using a stale IP; switch host to **`db`**. |
| **B** | Both `db` and parsed host TCP checks fail | Network / Compose profile / container network issue (e.g. services not up, wrong network). |
| **C** | DB connect succeeds but `order_intents` is missing | DB is reachable but table not created; restart backend so `init_db` creates it. |

## Safe fix steps (no secrets)

1. Update **`.env.aws`** so the DB host in `DATABASE_URL` is **`db`** (do not paste the actual value in this runbook).
2. Recreate backend and market-updater so they pick up the new env:
   ```bash
   cd /home/ubuntu/automated-trading-platform
   docker compose --profile aws up -d --force-recreate backend-aws market-updater-aws
   ```
3. Verify:
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8002/health
   curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8002/api/health/system
   ```
   Both should return **200**.

## Validation checklist

- [ ] `scripts/aws/diag_db_and_order_intents.sh` exits with code **0**
- [ ] Diagnostic prints **PASS: order_intents exists** and `order_intents_regclass` is not `None`
- [ ] `http://127.0.0.1:8002/health` returns **200**
- [ ] `http://127.0.0.1:8002/api/health/system` returns **200**
- [ ] `docker compose --profile aws ps` shows relevant services as healthy/up
