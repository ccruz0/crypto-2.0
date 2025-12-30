# SELL Diagnostic - Quick Start Commands

## 1. Verify AWS is Running Old Code

```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) grep -c "\[DIAGNOSTIC\]" /app/app/services/signal_monitor.py
```

**If returns 0 or error:** Code not deployed, proceed to step 2.

**If returns 15+:** Code is deployed, skip to step 4.

## 2. Deploy the Patch

```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws build --no-cache backend-aws && \
docker compose --profile aws up -d --force-recreate backend-aws
```

## 3. Verify Deployment

```bash
cd /home/ubuntu/automated-trading-platform && \
docker exec $(docker ps -q -f name=backend-aws) grep -c "FORCE_SELL_DIAGNOSTIC" /app/app/services/signal_monitor.py
```

**Expected:** Should return 2 (two env var checks)

## 4. Enable Force Diagnostics

```bash
cd /home/ubuntu/automated-trading-platform && \
echo "FORCE_SELL_DIAGNOSTIC_SYMBOL=TRX_USDT" >> .env.aws && \
docker compose --profile aws restart backend-aws
```

## 5. Verify Diagnostics Running

**Check startup message:**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs backend-aws | grep "DIAGNOSTIC.*enabled" | tail -3
```

**Watch diagnostic logs (wait ~30 seconds for next cycle):**
```bash
cd /home/ubuntu/automated-trading-platform && \
docker compose --profile aws logs -f backend-aws | grep "\[DIAGNOSTIC\].*TRX"
```

## 6. Disable When Done

```bash
cd /home/ubuntu/automated-trading-platform && \
# Edit .env.aws and remove FORCE_SELL_DIAGNOSTIC_SYMBOL line, then:
docker compose --profile aws restart backend-aws
```

