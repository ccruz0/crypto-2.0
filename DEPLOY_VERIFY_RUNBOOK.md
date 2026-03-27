# Portfolio Fix - Deploy & Verify Runbook

## Section 0 — What you're doing

- **Purpose**: Deploy defensive fixes to AWS backend-aws and verify `/api/dashboard/state` returns real Crypto.com portfolio data with reconcile debug enabled
- **Instance**: `i-087953603011543c5` (AWS EC2 via SSM port-forward)
- **Key endpoints**: `/api/health`, `/api/dashboard/state`
- **Success criteria**: Endpoint returns 200, `portfolio_value_source` starts with `"exchange:"`, `portfolio.reconcile.chosen` exists

---

## Phase 0 — Preflight (Mac)

```bash
cd ~/crypto-2.0
lsof -nP -iTCP:8002 -sTCP:LISTEN
CONTAINER=$(docker ps --format "{{.Names}}\t{{.Ports}}" | grep 8002 | awk '{print $1}')
if [ -n "$CONTAINER" ]; then
  docker stop "$CONTAINER" 2>/dev/null || true
  docker compose --profile local stop backend-dev backend 2>/dev/null || true
fi
lsof -nP -iTCP:8002 -sTCP:LISTEN || echo "Port 8002 is free"
```

---

## Phase 1 — Start port-forward (Mac)

```bash
cd ~/crypto-2.0
aws ssm start-session \
  --target i-087953603011543c5 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["127.0.0.1"],"portNumber":["8002"],"localPortNumber":["8002"]}'
```

**Keep this terminal open.**

---

## Phase 2 — Verify tunnel (Mac)

```bash
cd ~/crypto-2.0
curl -i http://localhost:8002/api/health
curl -sS http://localhost:8002/api/dashboard/state | head -120
```

---

## Phase 3 — Deploy on AWS (via SSM shell)

### A) Start interactive SSM shell session

```bash
cd ~/crypto-2.0
aws ssm start-session --target i-087953603011543c5
```

### B) Inside the SSM shell

```bash
cd ~/crypto-2.0
git pull origin main
docker compose --profile aws build backend-aws
docker compose --profile aws restart backend-aws
docker compose --profile aws ps
docker compose --profile aws logs --tail 200 backend-aws
```

### C) Verify deployment (Mac, via port-forward)

```bash
cd ~/crypto-2.0
curl -sS http://localhost:8002/api/dashboard/state | python3 -m json.tool | head -160 | grep -E "(total_value_usd|portfolio_value_source|reconcile)"
```

**Confirm:**
- `portfolio.total_value_usd > 0`
- `portfolio.portfolio_value_source` starts with `"exchange:"`
- `portfolio.reconcile.chosen` exists when debug enabled

---

## Phase 4 — Evidence collection (Mac)

### Backend evidence

```bash
cd ~/crypto-2.0
./evidence/portfolio_reconcile/collect_evidence.sh
LATEST=$(ls -1td evidence/portfolio_reconcile/*/ | head -1)
echo "Evidence folder: $LATEST"
cat "$LATEST/portfolio_extract.txt"
```

### Frontend evidence

**Terminal 1: Start dev server**

```bash
cd ~/crypto-2.0/frontend
export NEXT_PUBLIC_API_BASE_URL="http://localhost:8002"
npm run dev:clean
npm run dev
```

**Terminal 2: Run QA script**

```bash
cd ~/crypto-2.0/frontend
npm run qa:real-portfolio
```

**Terminal 3: Show results**

```bash
cd ~/crypto-2.0/frontend
LATEST_FRONTEND=$(ls -1td tmp/real_portfolio_from_state/*/ | head -1)
echo "Frontend evidence: $LATEST_FRONTEND"
cat "$LATEST_FRONTEND/summary.json"
```

---

## Phase 5 — Acceptance checklist

- [ ] `/api/dashboard/state` returns 200
- [ ] `portfolio.total_value_usd > 0`
- [ ] `portfolio.portfolio_value_source` starts with `"exchange:"`
- [ ] `portfolio.reconcile.chosen` exists (field_path + value + priority) when debug enabled
- [ ] Backend evidence files exist in `evidence/portfolio_reconcile/<timestamp>/`
- [ ] Frontend evidence files exist in `frontend/tmp/real_portfolio_from_state/<timestamp>/`

---

## Troubleshooting

### 1) Port 8002 already in use locally

```bash
cd ~/crypto-2.0
lsof -nP -iTCP:8002 -sTCP:LISTEN
PID=$(lsof -ti :8002 | head -1)
if [ -n "$PID" ]; then
  kill -9 "$PID" 2>/dev/null || true
fi
CONTAINER=$(docker ps --format "{{.Names}}\t{{.Ports}}" | grep 8002 | awk '{print $1}')
if [ -n "$CONTAINER" ]; then
  docker stop "$CONTAINER"
fi
lsof -nP -iTCP:8002 -sTCP:LISTEN || echo "Port 8002 is free"
```

### 2) SSM session not starting / plugin missing

```bash
cd ~/crypto-2.0
aws --version
which session-manager-plugin || echo "Plugin not found"
session-manager-plugin || echo "Plugin not installed"
# If missing, install: curl "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/mac_arm64/session-manager-plugin.pkg" -o "/tmp/session-manager-plugin.pkg" && sudo installer -pkg /tmp/session-manager-plugin.pkg -target /
# Verify IAM permissions: SSM Session Manager access for instance i-087953603011543c5
```

### 3) AWS backend-aws not updating / still old image

```bash
# On AWS (via SSM shell)
cd ~/crypto-2.0
git log -1 --oneline
git pull origin main
docker compose --profile aws build --no-cache backend-aws
docker compose --profile aws stop backend-aws
docker compose --profile aws rm -f backend-aws
docker compose --profile aws up -d backend-aws
docker compose --profile aws ps
docker images | grep backend-aws
docker compose --profile aws logs --tail 100 backend-aws
```
