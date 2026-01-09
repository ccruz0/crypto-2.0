# Deploy Portfolio Fix to AWS - Execute Now

## Current Status
- ✅ Code committed: `fd44bca Fix: portfolio reconcile diagnostics + equity field selection + evidence tooling`
- ✅ Pushed to `origin/main`
- ⚠️  SSM port-forward not active (needs to be started)

## Deployment Steps

### Terminal 1: Start Port-Forward (keep open)

```bash
cd ~/automated-trading-platform
aws ssm start-session \
  --target i-08726dc37133b2454 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["127.0.0.1"],"portNumber":["8002"],"localPortNumber":["8002"]}'
```

### Terminal 2: Deploy on AWS (SSM shell)

```bash
cd ~/automated-trading-platform
aws ssm start-session --target i-08726dc37133b2454
```

**Inside AWS SSM shell:**

```bash
cd ~/automated-trading-platform
git pull origin main
docker compose --profile aws build --no-cache backend-aws
docker compose --profile aws restart backend-aws
docker compose --profile aws ps
docker compose --profile aws logs --tail 200 backend-aws | grep -E "(ERROR|Exception|Started|Uvicorn|RECONCILE)" | tail -20
exit
```

### Terminal 3: Verify and Collect Evidence (Mac)

```bash
cd ~/automated-trading-platform
curl -i http://localhost:8002/api/health | grep -E "(HTTP|X-ATP-Backend)"
cd ~/automated-trading-platform
python3 evidence/portfolio_reconcile/fetch_reconcile_evidence.py --api-base-url http://localhost:8002
cd ~/automated-trading-platform
LATEST=$(ls -1td evidence/portfolio_reconcile/*/ | head -1)
cat "$LATEST/summary.txt"
```

## If Still Derived

```bash
cd ~/automated-trading-platform
curl -sS http://localhost:8002/api/diagnostics/portfolio/reconcile | python3 -m json.tool > /tmp/reconcile.json
cd ~/automated-trading-platform
python3 - <<'PY'
import json
d=json.load(open('/tmp/reconcile.json'))
print("CHOSEN:", d.get("chosen"))
rf=d.get("raw_fields",{})
keys=[k for k in rf.keys() if any(x in k.lower() for x in ["haircut","wallet","balance","equity","net","total","margin"])]
for k in sorted(keys)[:30]:
    print(f"{k}: {rf[k]}")
PY
```

Then set `PORTFOLIO_EQUITY_FIELD_OVERRIDE` in docker-compose.yml or .env.aws and restart.

